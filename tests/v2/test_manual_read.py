"""Manual speech admission and silent Windows child behavior on original fixtures."""
from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from uuid import uuid4

import pytest

from lvc.platform.windows.manual_read import (
    AUDIO_PYTHON,
    MAX_TEXT_CHARS,
    SPOOL_ROOT,
    ManualReadController,
    OutputDevice,
)
from lvc.vision.binding import PixelRect
from lvc.vision.comparison import ReviewState


def test_manual_read_requires_current_human_confirmation() -> None:
    controller = ManualReadController()
    device = OutputDevice("explicit-synthetic-device", "Silent")
    source = ReviewState.empty().load(PixelRect(0, 0, 100, 50), None,
                                      "Lanterns glow tonight.")
    assert not controller.read(source, "bf_emma", device, silent=True)
    assert controller.events.get_nowait()[0] == "ERROR"
    assert not controller.read(source.edit("Corrected words"), "bf_emma", device,
                               silent=True)
    assert not controller.read(source.edit("x" * (MAX_TEXT_CHARS + 1)).confirm(),
                               "bf_emma", device, silent=True)
    assert not controller.read(source.confirm(), "unknown-voice", device, silent=True)
    assert not controller.busy
    controller.close()


def _synthetic_wav() -> bytes:
    samples = [round(math.sin(index * math.tau * 220 / 48_000) * 1_000)
               for index in range(4_800)]
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(struct.pack("<4800h", *samples))
    return stream.getvalue()


def _child(payload: dict[str, object]) -> tuple[int, list[dict[str, object]]]:
    run = subprocess.run(
        [str(AUDIO_PYTHON), "-u", "-m", "lvc.platform.windows.manual_audio_child",
         "--silent"], cwd=Path(__file__).resolve().parents[2],
        input=(json.dumps(payload) + "\n").encode(), capture_output=True,
        timeout=10, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert len(run.stdout) < 16_384
    return run.returncode, [json.loads(line) for line in run.stdout.splitlines()]


@pytest.mark.skipif(sys.platform != "win32" or not AUDIO_PYTHON.is_file(),
                    reason="Windows Qt development runtime required")
def test_silent_child_validates_artifacts_and_drains_two_ordered_units() -> None:
    SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SPOOL_ROOT) as directory:
        spool = Path(directory)
        wav = _synthetic_wav()
        rows = []
        for index in range(2):
            path = spool / f"{index:02d}.wav"
            path.write_bytes(wav)
            rows.append({"path": str(path), "sha256": hashlib.sha256(wav).hexdigest(),
                         "frames": 4_800})
        payload: dict[str, object] = {
            "session_id": str(uuid4()), "request_id": str(uuid4()),
            "generation": 1, "page_digest": "a" * 64, "source": "cache",
            "device_id": "explicit-synthetic-device", "device_description": "Silent",
            "units": rows,
        }
        code, events = _child(payload)
        assert code == 0
        assert [item["event"] for item in events] == [
            "READY", "UNIT_STARTED", "UNIT_DONE", "UNIT_STARTED", "UNIT_DONE",
            "COMPLETED",
        ]
        assert [item["index"] for item in events if item["event"] == "UNIT_DONE"] == [1, 2]

        broken = dict(payload, units=[dict(rows[0], sha256="0" * 64)])
        code, events = _child(broken)
        assert code != 0 and events == [{"code": "AUDIO_UNIT_HASH_INVALID", "event": "ERROR"}]

        external = dict(payload, units=[dict(rows[0], path=str(Path(__file__).resolve()))])
        code, events = _child(external)
        assert code != 0 and events[0]["event"] == "ERROR"
