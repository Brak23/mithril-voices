"""Exercise the physical adapter's PySide error enum using no audio device."""
# pyright: reportMissingImports=false
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtMultimedia import QAudioFormat, QtAudio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lvc.qt_physical_backend import QtSinkBackend


class FakeIO:
    def __init__(self) -> None:
        self.written = b""

    def write(self, pcm: bytes) -> int:
        self.written += pcm
        return len(pcm)


class FakeSink:
    def __init__(self) -> None:
        self.io = FakeIO()
        self.reset_count = 0

    def start(self) -> FakeIO:
        return self.io

    def error(self) -> QtAudio.Error:
        return QtAudio.Error.NoError

    def format(self) -> QAudioFormat:
        result = QAudioFormat()
        result.setSampleRate(48_000)
        result.setChannelCount(1)
        result.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return result

    def bufferSize(self) -> int:
        return 4800

    def bytesFree(self) -> int:
        return 4800

    def reset(self) -> None:
        self.reset_count += 1


def main() -> int:
    app = QCoreApplication([])
    backend = object.__new__(QtSinkBackend)
    backend.creator_thread = QThread.currentThread()
    backend.sink = FakeSink()
    backend.io = None
    backend.actual_buffer_bytes = None
    backend.actual_sample_rate = None
    backend.actual_channel_count = None
    backend.actual_sample_format = None
    backend.first_write_ns = None
    backend.last_write_ns = None
    backend.last_reset_ns = None
    backend.accepted_bytes = 0
    backend.reset_count = 0
    backend.error_names = []
    accepted = backend.write(b"\x01\x00\x02\x00")
    sink = backend.sink
    ok = (accepted == 4 and sink.io.written == b"\x01\x00\x02\x00"
          and backend.accepted_bytes == 4 and backend.actual_buffer_bytes == 4800
          and not backend.error_names)
    print(json.dumps({"status": "PASSED" if ok else "FAILED",
                      "accepted_bytes": accepted, "physical_device_opened": False}))
    _ = app
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
