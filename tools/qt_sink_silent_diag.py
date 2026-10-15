"""Silent QAudioSink start diagnostic: opens a device but never writes PCM."""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lvc.qt_physical_backend import QtSinkBackend


class Diagnostic(QObject):
    finished = Signal()

    def __init__(self, device_id: str, mode: str):
        super().__init__()
        self.device_id = device_id
        self.mode = mode

    @Slot()
    def arm(self) -> None:
        QTimer.singleShot(0, self.run)

    @Slot()
    def run(self) -> None:
        if self.mode == "backend_owner":
            backend = QtSinkBackend(self.device_id)
            sink = backend.sink
            before = {"state": str(sink.state()), "error": str(sink.error()),
                      "is_null": sink.isNull(), "buffer_bytes": sink.bufferSize()}
            backend.reset()
            after_reset = {"state": str(sink.state()), "error": str(sink.error()),
                           "is_null": sink.isNull()}
            io = sink.start()
            after = {"state": str(sink.state()), "error": str(sink.error()),
                     "error_is_no_error": sink.error() == QtAudio.Error.NoError,
                     "is_null": sink.isNull(), "buffer_bytes": sink.bufferSize(),
                     "bytes_free": sink.bytesFree(), "io_is_none": io is None,
                     "io_type": type(io).__name__}
            backend.reset()
            print(json.dumps({"mode": self.mode, "pyside": pyside_version,
                              "device": backend.device_description,
                              "default": backend.was_default_at_selection,
                              "format_supported": True, "before": before,
                              "after_reset": after_reset, "after_start": after,
                              "pcm_bytes_written": 0}, sort_keys=True), flush=True)
            self.finished.emit()
            return
        matches = [d for d in QMediaDevices.audioOutputs()
                   if bytes(d.id()).decode("utf-8", "replace") == self.device_id]
        if len(matches) != 1:
            raise ValueError("Exact device ID did not resolve once")
        device = matches[0]
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48_000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        sink = QAudioSink(device, audio_format)
        sink.setBufferSize(4800)
        before = {"state": str(sink.state()), "error": str(sink.error()),
                  "is_null": sink.isNull(), "buffer_bytes": sink.bufferSize()}
        if self.mode == "owner_reset":
            sink.reset()
        after_reset = {"state": str(sink.state()), "error": str(sink.error()),
                       "is_null": sink.isNull()}
        io = sink.start()
        after = {"state": str(sink.state()), "error": str(sink.error()),
                 "error_is_no_error": sink.error() == QtAudio.Error.NoError,
                 "is_null": sink.isNull(), "buffer_bytes": sink.bufferSize(),
                 "bytes_free": sink.bytesFree(), "io_is_none": io is None,
                 "io_type": type(io).__name__}
        sink.reset()
        print(json.dumps({"mode": self.mode, "pyside": pyside_version,
                          "device": device.description(), "default": device.isDefault(),
                          "format_supported": device.isFormatSupported(audio_format),
                          "before": before, "after_reset": after_reset,
                          "after_start": after, "pcm_bytes_written": 0}, sort_keys=True),
              flush=True)
        self.finished.emit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--mode", choices=["main", "owner", "owner_reset",
                                           "backend_owner"], required=True)
    args = parser.parse_args()
    app = QCoreApplication([])
    diagnostic = Diagnostic(args.device_id, args.mode)
    thread: QThread | None = None
    if args.mode == "main":
        diagnostic.finished.connect(app.quit)
        QTimer.singleShot(0, diagnostic.run)
    else:
        owner_thread = QThread()
        diagnostic.moveToThread(owner_thread)
        owner_thread.started.connect(diagnostic.arm)
        diagnostic.finished.connect(owner_thread.quit)
        owner_thread.finished.connect(app.quit)
        owner_thread.start()
        thread = owner_thread
    code = app.exec()
    if thread is not None:
        thread.wait(1000)
    return code


if __name__ == "__main__":
    sys.exit(main())
