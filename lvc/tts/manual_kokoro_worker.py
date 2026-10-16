"""One offline, private, supervised Kokoro render request from stdin."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from lvc.tts.kokoro_cpu import VOICE_SHA256, IncompletePhonemes, KokoroCpu
from lvc.voice.cache import validate_complete_wav
from lvc.voice.text_plan import chunk_speech

ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT_BYTES = 16_384
MAX_TEXT_CHARS = 3_000
MAX_UNITS = 32


def render_request(command: dict[str, object], output: Path) -> list[dict[str, object]]:
    text, voice = command.get("text"), command.get("voice")
    if (set(command) != {"text", "voice"} or not isinstance(text, str)
            or not text.strip() or len(text) > MAX_TEXT_CHARS
            or not isinstance(voice, str) or voice not in VOICE_SHA256):
        raise ValueError("TEXT_OR_VOICE_INVALID")
    units = chunk_speech(text, max_codepoints=180)
    if not 1 <= len(units) <= MAX_UNITS or "".join(unit.text for unit in units) != text:
        raise ValueError("TEXT_TOO_LONG")
    cpu = KokoroCpu(ROOT / ".audition" / "assets", voice)
    rows: list[dict[str, object]] = []
    for index, unit in enumerate(units):
        rendered = cpu.render(unit.text)
        frames = validate_complete_wav(rendered.wav)
        destination = output / f"{index:02d}.wav"
        temporary = output / f".{index:02d}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(rendered.wav)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        rows.append({"path": str(destination),
                     "sha256": hashlib.sha256(rendered.wav).hexdigest(),
                     "frames": frames})
        print(json.dumps({"event": "UNIT_RENDERED", "index": index + 1,
                          "total": len(units)}), flush=True)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_root = (ROOT / ".audition" / "tmp" / "manual-read").resolve()
    output = args.output.resolve()
    if (not output.is_relative_to(expected_root) or output.parent != expected_root
            or not output.is_dir()):
        print('{"event":"ERROR","code":"OUTPUT_NOT_PRIVATE"}', flush=True)
        return 2
    raw = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        print('{"event":"ERROR","code":"INPUT_TOO_LARGE"}', flush=True)
        return 2
    try:
        command = json.loads(raw)
        if not isinstance(command, dict):
            raise TypeError("TEXT_OR_VOICE_INVALID")
        rows = render_request(command, output)
    except (FileNotFoundError, ImportError) as exc:
        _ = exc
        print('{"event":"ERROR","code":"VOICE_ASSET_UNAVAILABLE"}', flush=True)
        return 2
    except (IncompletePhonemes, ValueError, TypeError) as exc:
        code = "TEXT_UNSPEAKABLE" if isinstance(exc, IncompletePhonemes) else str(exc)
        if code not in {"TEXT_OR_VOICE_INVALID", "TEXT_TOO_LONG", "TEXT_UNSPEAKABLE"}:
            code = "VOICE_ASSET_INVALID"
        print(json.dumps({"event": "ERROR", "code": code}), flush=True)
        return 2
    except Exception:  # noqa: BLE001 - never print private text from a model exception
        print('{"event":"ERROR","code":"TTS_FAILED"}', flush=True)
        return 2
    print(json.dumps({"event": "DONE", "units": rows}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
