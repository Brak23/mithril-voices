"""Supervised, offline, local-only CPU audition; no playback or game access."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from lvc.tts.kokoro_cpu import MODEL_SHA256, VOICE_SHA256, GenerationCanceled, KokoroCpu
from lvc.voice.cache import validate_complete_wav


class WorkerProcess(Protocol):
    def poll(self) -> int | None: ...
    def kill(self) -> None: ...
    def wait(self) -> int: ...


def wait_worker(process: WorkerProcess, expected_generation: UUID,
                read_generation: Callable[[], UUID], *,
                now: Callable[[], float] = time.monotonic,
                pause: Callable[[float], None] = time.sleep,
                timeout_s: float = 900, started_at: float | None = None) -> int:
    """Reap a stopped worker before any of its artifacts may be admitted."""
    if started_at is None:
        started_at = now()
    if timeout_s <= 0:
        raise ValueError("Positive worker deadline required")
    while True:
        if read_generation() != expected_generation:
            process.kill()
            process.wait()
            raise GenerationCanceled("Audition generation was revoked")
        status = process.poll()
        if status is not None:
            return status
        if now() - started_at >= timeout_s:
            process.kill()
            process.wait()
            raise TimeoutError("Audition worker exceeded its deadline")
        pause(0.1)


def _fixtures(path: Path) -> list[dict[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(rows, list) or len(rows) != 6
            or any(not isinstance(row, dict) or set(row) != {"id", "text"}
                   or not isinstance(row["id"], str)
                   or not re.fullmatch(r"[a-z0-9-]{1,50}", row["id"])
                   or not isinstance(row["text"], str) or not row["text"].strip()
                   or len(row["text"]) > 500 for row in rows)
            or len({row["id"] for row in rows}) != len(rows)):
        raise ValueError("Audition fixtures must be six distinct bounded original passages")
    return rows


def _atomic_bytes(path: Path, data: bytes) -> None:
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _child(assets: Path, fixtures: Path, output: Path, voice: str,
           generation: UUID) -> None:
    passages = _fixtures(fixtures)
    cpu = KokoroCpu(assets, voice)
    rows: list[dict[str, Any]] = []
    for passage in passages:
        rendered = cpu.render(passage["text"])
        filename = f"{voice}-{passage['id']}.wav"
        _atomic_bytes(output / filename, rendered.wav)
        rows.append({"id": passage["id"], "filename": filename,
                     "sha256": hashlib.sha256(rendered.wav).hexdigest(),
                     "frames": validate_complete_wav(rendered.wav),
                     "units": rendered.unit_count,
                     "phoneme_lengths": rendered.phoneme_lengths,
                     "first_unit_ready_ms": round(rendered.first_unit_ready_ms, 2),
                     "render_ms": round(rendered.render_ms, 2)})
    receipt = {"generation": str(generation), "voice": voice, "status": "GENERATED_UNHEARD",
               "model_sha256": MODEL_SHA256, "voice_sha256": VOICE_SHA256[voice],
               "passages": rows}
    _atomic_bytes(output / f"{voice}-receipt.json",
                  (json.dumps(receipt, indent=2) + "\n").encode("utf-8"))


def _verify_receipt(output: Path, voice: str, generation: UUID,
                    fixtures: Path) -> dict[str, Any]:
    receipt_path = output / f"{voice}-receipt.json"
    if receipt_path.stat().st_size > 32_768:
        raise ValueError("Worker receipt exceeds the bounded size")
    data = json.loads(receipt_path.read_text(encoding="utf-8"),
                      parse_constant=lambda _value: (_ for _ in ()).throw(
                          ValueError("Nonfinite worker receipt value")))
    expected_ids = {row["id"] for row in _fixtures(fixtures)}
    if not isinstance(data, dict):
        raise TypeError("Worker receipt is not an object")
    rows = data.get("passages")
    if (data.get("generation") != str(generation) or data.get("voice") != voice
            or data.get("status") != "GENERATED_UNHEARD" or not isinstance(rows, list)
            or data.get("model_sha256") != MODEL_SHA256
            or data.get("voice_sha256") != VOICE_SHA256[voice]
            or len(rows) != 6 or any(not isinstance(row, dict) for row in rows)
            or {row.get("id") for row in rows} != expected_ids):
        raise ValueError("Worker receipt is incomplete or from a stale generation")
    for row in rows:
        if (not isinstance(row.get("units"), int) or row["units"] < 1
                or not isinstance(row.get("phoneme_lengths"), list)
                or len(row["phoneme_lengths"]) != row["units"]
                or any(type(length) is not int or not 1 <= length <= 510
                       for length in row["phoneme_lengths"])):
            raise ValueError("Worker receipt contains invalid phoneme evidence")
        filename = f"{voice}-{row['id']}.wav"
        if row.get("filename") != filename:
            raise ValueError("Worker receipt referenced an unexpected file")
        wav = (output / filename).read_bytes()
        if hashlib.sha256(wav).hexdigest() != row.get("sha256"):
            raise ValueError("Worker WAV hash differs from receipt")
        if validate_complete_wav(wav) != row.get("frames"):
            raise ValueError("Worker WAV frame count differs from receipt")
    return data


def _parent(assets: Path, fixtures: Path, output_root: Path) -> Path:
    _fixtures(fixtures)
    generation = uuid4()
    output = output_root / str(generation)
    output.mkdir(parents=True, exist_ok=False)
    for voice in VOICE_SHA256:
        env = os.environ.copy()
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1", "TMP": str(output), "TEMP": str(output)})
        command = [sys.executable, "-m", "lvc.tts.kokoro_worker", "--child",
                   "--assets", str(assets), "--fixtures", str(fixtures),
                   "--output", str(output), "--voice", voice,
                   "--generation", str(generation)]
        with (output / f"{voice}-worker.log").open("wb") as log:
            process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                                       stderr=log, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                status = wait_worker(process, generation, lambda: generation)
            except BaseException:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                raise
        if status != 0:
            raise RuntimeError(f"Offline {voice} worker failed; inspect its local worker log")
        _verify_receipt(output, voice, generation, fixtures)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate local, unheard Kokoro audition WAVs")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--voice", choices=tuple(VOICE_SHA256), help=argparse.SUPPRESS)
    parser.add_argument("--generation", type=UUID, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.voice is None or args.generation is None:
            parser.error("Child requires a voice and generation")
        _child(args.assets, args.fixtures, args.output, args.voice, args.generation)
        return 0
    output = _parent(args.assets.resolve(), args.fixtures.resolve(), args.output.resolve())
    print(f"Generated 12 unheard local WAVs in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
