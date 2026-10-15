"""One bounded Realtek Stop probe; requires an explicit execution flag."""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from time import perf_counter_ns

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lvc.qt_audio_owner import QtAudioService
from lvc.qt_physical_backend import QtSinkBackend
from tools.qt_audio_owner_probe import SESSION, validated_submission

SAMPLE_RATE = 48_000
TONE_MS = 500
STOP_AFTER_FIRST_WRITE_MS = 120
TONE_HZ = 440
PEAK_DBFS = -36
FRAME_COUNT = SAMPLE_RATE * TONE_MS // 1000


def tone_pcm() -> bytes:
    peak = 32767 * 10 ** (PEAK_DBFS / 20)
    samples = [round(peak * math.sin(2 * math.pi * TONE_HZ * i / SAMPLE_RATE))
               for i in range(FRAME_COUNT)]
    return struct.pack(f"<{FRAME_COUNT}h", *samples)


class StopProbe(QObject):
    def __init__(self, device_id: str, expected_description: str):
        super().__init__()
        self.app = QCoreApplication.instance()
        self.expected_description = expected_description
        self.backend: QtSinkBackend | None = None
        self.reason = "INCOMPLETE"
        self.ending = False
        self.first_write_observed = False
        self.written_frames = 0
        self.old_epoch = 0
        self.stop_request_ns: int | None = None
        self.fence_ack_ns: int | None = None
        self.reset_at_fence_ns: int | None = None
        self.bytes_at_fence: int | None = None
        self.rejections: list[str] = []
        self.device_losses = 0
        self.completed_units = 0
        base = ROOT.parent / "test-tmp"
        base.mkdir(exist_ok=True)
        self.isolated = Path(tempfile.mkdtemp(prefix="mithril-stop-", dir=base))
        spool = self.isolated / str(SESSION)
        spool.mkdir()
        self.submission = validated_submission(spool, tone_pcm())

        def factory(selected: str) -> QtSinkBackend:
            backend = QtSinkBackend(selected)
            if backend.device_description != expected_description:
                raise ValueError("Selected output description changed")
            self.backend = backend
            return backend

        self.service = QtAudioService(SESSION, device_id, factory,
                                      allow_physical=True)
        self.service.owner.fence_ack.connect(self.on_fence_ack)
        self.service.owner.write_observed.connect(self.on_write)
        self.service.owner.rejected.connect(self.on_rejected)
        self.service.owner.device_lost.connect(self.on_device_lost)
        self.service.owner.unit_drained.connect(self.on_completed)
        self.service.thread.finished.connect(self.app.quit)
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(lambda: self.request_stop("WATCHDOG"))
        self.watchdog.start(1500)
        self.service.fence(1)

    @Slot(int, int)
    def on_fence_ack(self, generation: int, epoch: int) -> None:
        if generation == 1:
            self.old_epoch = epoch
            self.service.admit(self.submission)
        elif generation == 2:
            self.fence_ack_ns = perf_counter_ns()
            backend = self.backend
            self.reset_at_fence_ns = backend.last_reset_ns if backend else None
            self.bytes_at_fence = backend.accepted_bytes if backend else None
            if self.reason == "TIMED_STOP":
                self.service.idle(self.old_epoch)
                self.service.admit(self.submission)  # Old generation must be rejected.
                QTimer.singleShot(80, self.service.close)
            else:
                self.service.close()

    @Slot(str, int, int)
    def on_write(self, _request_id: str, frames: int, _epoch: int) -> None:
        self.written_frames += frames
        if not self.first_write_observed:
            self.first_write_observed = True
            QTimer.singleShot(STOP_AFTER_FIRST_WRITE_MS,
                              lambda: self.request_stop("TIMED_STOP"))

    @Slot(str)
    def on_rejected(self, code: str) -> None:
        self.rejections.append(code)
        if not self.ending:
            self.request_stop("REJECTED")

    @Slot(int)
    def on_device_lost(self, _generation: int) -> None:
        self.device_losses += 1
        self.request_stop("DEVICE_LOST")

    @Slot(str, str, int)
    def on_completed(self, _request_id: str, _unit_id: str, _epoch: int) -> None:
        self.completed_units += 1

    def request_stop(self, reason: str) -> None:
        if self.ending:
            return
        self.ending = True
        self.reason = reason
        self.stop_request_ns = perf_counter_ns()
        self.watchdog.stop()
        self.service.fence(2)

    def report(self) -> tuple[dict[str, object], int]:
        self.app.exec()
        if not self.service.thread.wait(1500):
            raise RuntimeError("Qt audio owner did not stop")
        safe_base = (ROOT.parent / "test-tmp").resolve()
        isolated = self.isolated.resolve()
        if not isolated.is_relative_to(safe_base) or not isolated.name.startswith("mithril-stop-"):
            raise RuntimeError("Refusing cleanup outside owned test directory")
        shutil.rmtree(isolated)
        backend = self.backend
        accepted = backend.accepted_bytes if backend else 0
        report: dict[str, object] = {
            "scope": "ONE_BOUNDED_REALTEK_PHYSICAL_STOP_AND_STALE_CHECK",
            "status": "FAILED",
            "reason": self.reason,
            "device_id": backend.device_id if backend else None,
            "device_description": backend.device_description if backend else None,
            "tone_ms": TONE_MS,
            "tone_hz": TONE_HZ,
            "digital_peak_dbfs_cap": PEAK_DBFS,
            "planned_stop_after_first_write_ms": STOP_AFTER_FIRST_WRITE_MS,
            "source_frames": FRAME_COUNT,
            "written_frames": self.written_frames,
            "accepted_bytes": accepted,
            "bytes_at_fence": self.bytes_at_fence,
            "stale_rejections": self.rejections,
            "renderer_completed_units": self.completed_units,
            "device_losses": self.device_losses,
            "first_backend_write_perf_ns": backend.first_write_ns if backend else None,
            "stop_request_perf_ns": self.stop_request_ns,
            "backend_reset_perf_ns": self.reset_at_fence_ns,
            "fence_ack_perf_ns": self.fence_ack_ns,
            "software_stop_to_reset_ms":
                ((self.reset_at_fence_ns - self.stop_request_ns) / 1e6
                 if self.reset_at_fence_ns and self.stop_request_ns else None),
            "backend": backend.report() if backend else None,
            "physical_acoustic_silence_measured": False,
        }
        ok = (backend is not None and self.reason == "TIMED_STOP"
              and 0 < accepted < FRAME_COUNT * 2
              and self.written_frames * 2 == accepted
              and self.bytes_at_fence == accepted
              and self.rejections == ["UNIT_NOT_ADMISSIBLE"]
              and self.completed_units == 0 and self.device_losses == 0
              and self.reset_at_fence_ns is not None
              and backend.reset_count >= 2)
        report["status"] = "PASSED" if ok else "FAILED"
        return report, 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--expected-description", required=True)
    parser.add_argument("--execute-stop-check", action="store_true", required=True)
    args = parser.parse_args()
    app = QCoreApplication([])
    report, code = StopProbe(args.device_id, args.expected_description).report()
    print(json.dumps(report, sort_keys=True))
    _ = app
    return code


if __name__ == "__main__":
    raise SystemExit(main())
