"""Experimental resident, offline Kokoro phrase producer; no audio device.

One complete verified WAV is emitted per NEXT acknowledgment. Stop is enforced
by the host's generation fence and termination of this owned worker process;
inference itself is not assumed interruptible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from lvc.tts.kokoro_cpu import VOICE_SHA256, KokoroCpu
from lvc.voice.cache import validate_complete_wav
from lvc.voice.text_plan import chunk_speech

ROOT = Path(__file__).resolve().parents[2]
SPOOL_ROOT = ROOT / ".audition" / "tmp" / "manual-read"
MAX_LINE = 16_384
MAX_TEXT = 3_000
MAX_UNITS = 32


class Renderer(Protocol):
    def render(self, text: str) -> object: ...


def read_command(stream) -> dict[str, object] | None:
    raw = stream.readline(MAX_LINE + 1)
    if not raw:
        return None
    if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
        raise ValueError("COMMAND_TOO_LARGE_OR_INCOMPLETE")
    try:
        def unique_pairs(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("COMMAND_INVALID")
                result[key] = item
            return result

        value = json.loads(raw, object_pairs_hook=unique_pairs,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               ValueError("COMMAND_INVALID")))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("COMMAND_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError("COMMAND_INVALID")  # noqa: TRY004 - wire error code
    return value


def request_units(command: dict[str, object], voice: str) -> tuple[UUID, int, tuple[str, ...]]:
    if set(command) != {"action", "request_id", "generation", "voice", "text"}:
        raise ValueError("COMMAND_INVALID")
    request_id, generation, selected, text = (command[key] for key in
                                               ("request_id", "generation", "voice", "text"))
    if (command["action"] != "render" or not isinstance(request_id, str)
            or type(generation) is not int or generation < 1
            or selected != voice or not isinstance(text, str)
            or not 0 < len(text) <= MAX_TEXT):
        raise ValueError("COMMAND_INVALID")
    try:
        parsed = UUID(request_id)
    except ValueError as exc:
        raise ValueError("COMMAND_INVALID") from exc
    units = tuple(unit.text for unit in chunk_speech(text, max_codepoints=180))
    if not 1 <= len(units) <= MAX_UNITS or "".join(units) != text:
        raise ValueError("TEXT_TOO_LONG")
    return parsed, generation, units


def write_unit(directory: Path, index: int, wav: bytes) -> dict[str, object]:
    frames = validate_complete_wav(wav)
    destination = directory / f"{index:02d}.wav"
    temporary = directory / f".{index:02d}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(wav)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(destination), "sha256": hashlib.sha256(wav).hexdigest(),
            "frames": frames}


def next_matches(value: dict[str, object] | None, request: UUID,
                 generation: int, index: int) -> bool:
    return (value == {"action": "next", "request_id": str(request),
                     "generation": generation, "after_index": index}
            and value is not None and type(value["generation"]) is int
            and type(value["after_index"]) is int)


def messages(command: dict[str, object], voice: str, renderer: Renderer,
             directory: Path, next_command: Callable[[], dict[str, object] | None]
             ) -> Iterator[dict[str, object]]:
    request, generation, units = request_units(command, voice)
    request_dir = directory / str(request)
    request_dir.mkdir(exist_ok=False)
    for index, unit in enumerate(units):
        rendered = renderer.render(unit)
        wav = getattr(rendered, "wav", None)
        if not isinstance(wav, bytes):
            raise ValueError("RENDER_RESULT_INVALID")  # noqa: TRY004 - wire error code
        row = write_unit(request_dir, index, wav)
        yield {"event": "UNIT_READY", "request_id": str(request),
               "generation": generation, "index": index, "total": len(units), **row}
        if index + 1 < len(units) and not next_matches(next_command(), request, generation, index):
            raise ValueError("NEXT_INVALID")
    yield {"event": "DONE", "request_id": str(request), "generation": generation,
           "total": len(units)}


def emit(message: dict[str, object]) -> None:
    print(json.dumps(message, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    try:
        if args.voice not in VOICE_SHA256:
            raise ValueError("VOICE_UNAVAILABLE")
        nonce = UUID(args.nonce)
        if args.spool.is_symlink():
            raise ValueError("SPOOL_INVALID")
        spool = args.spool.resolve(strict=True)
        if (spool.parent != SPOOL_ROOT.resolve(strict=True)
                or not spool.is_dir()):
            raise ValueError("SPOOL_INVALID")
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                           "HF_HUB_DISABLE_TELEMETRY": "1"})
        renderer = KokoroCpu(ROOT / ".audition" / "assets", args.voice)
        emit({"event": "READY", "nonce": str(nonce), "voice": args.voice})
        while True:
            command = read_command(sys.stdin.buffer)
            if command is None or command == {"action": "shutdown"}:
                return 0
            for message in messages(command, args.voice, renderer, spool,
                                    lambda: read_command(sys.stdin.buffer)):
                emit(message)
    except Exception as exc:  # noqa: BLE001 - model errors may contain private text
        code = str(exc) if isinstance(exc, ValueError) and str(exc) in {
            "VOICE_UNAVAILABLE", "SPOOL_INVALID", "COMMAND_INVALID",
            "COMMAND_TOO_LARGE_OR_INCOMPLETE", "TEXT_TOO_LONG", "NEXT_INVALID",
            "RENDER_RESULT_INVALID"} else "WORKER_FAILED"
        emit({"event": "ERROR", "code": code})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
