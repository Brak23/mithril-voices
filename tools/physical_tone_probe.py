"""Guarded, local 250 ms low-level tone through one explicit QAudioSink device."""
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
TONE_SECONDS = 0.25
TONE_HZ = 440
PEAK_DBFS = -36
AMPLITUDE = 10 ** (PEAK_DBFS / 20)
FRAME_COUNT = int(SAMPLE_RATE * TONE_SECONDS)


def tone_pcm() -> bytes:
    samples = [round(32767 * AMPLITUDE * math.sin(2 * math.pi * TONE_HZ * i / SAMPLE_RATE))
               for i in range(FRAME_COUNT)]
    return struct.pack(f"<{FRAME_COUNT}h", *samples)


class PhysicalProbe(QObject):
    def __init__(self, device_id: str, expected_description: str, play: bool):
        super().__init__()
        self.app = QCoreApplication.instance()
        self.play = play
        self.expected_description = expected_description
        self.backend: QtSinkBackend | None = None
        self.reason = "INCOMPLETE"
        self.written_frames = 0
        self.stop_request_ns: int | None = None
        self.fence_ack_ns: int | None = None
        self.all_frames_submitted_ns: int | None = None
        self.ending = False
        self.rejections: list[str] = []
        self.device_losses = 0
        base = ROOT.parent / "test-tmp"
        base.mkdir(exist_ok=True)
        self.isolated = Path(tempfile.mkdtemp(prefix="mithril-tone-", dir=base))
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
        self.service.thread.finished.connect(self.app.quit)
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(lambda: self.request_stop("WATCHDOG"))
        self.watchdog.start(1200)
        self.service.fence(1)

    @Slot(int, int)
    def on_fence_ack(self, generation: int, _epoch: int) -> None:
        if generation == 1:
            if self.play:
                self.service.admit(self.submission)
                QTimer.singleShot(400, lambda: self.request_stop("TIMED_STOP"))
            else:
                self.reason = "PREFLIGHT_ONLY"
                self.service.close()
        elif generation == 2:
            self.fence_ack_ns = perf_counter_ns()
            self.service.close()

    @Slot(str, int, int)
    def on_write(self, _request_id: str, frames: int, _epoch: int) -> None:
        self.written_frames += frames
        if self.written_frames == FRAME_COUNT:
            self.all_frames_submitted_ns = perf_counter_ns()

    @Slot(str)
    def on_rejected(self, code: str) -> None:
        self.rejections.append(code)
        self.request_stop("REJECTED")

    @Slot(int)
    def on_device_lost(self, _generation: int) -> None:
        self.device_losses += 1
        self.request_stop("DEVICE_LOST")

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
        if not isolated.is_relative_to(safe_base) or not isolated.name.startswith("mithril-tone-"):
            raise RuntimeError("Refusing cleanup outside owned test directory")
        shutil.rmtree(isolated)
        backend = self.backend
        backend_report = backend.report() if backend else None
        report: dict[str, object] = {
            "scope": "ONE_USER_APPROVED_PHYSICAL_SYNTHETIC_TONE",
            "status": "FAILED",
            "reason": self.reason,
            "play_requested": self.play,
            "tone_hz": TONE_HZ,
            "tone_seconds": TONE_SECONDS,
            "peak_dbfs": PEAK_DBFS,
            "verified_pcm_bytes": len(self.submission.unit.pcm),
            "written_frames_observed": self.written_frames,
            "all_frames_submitted": self.all_frames_submitted_ns is not None,
            "rejections": self.rejections,
            "device_losses": self.device_losses,
            "stop_request_to_fence_ack_ms":
                ((self.fence_ack_ns - self.stop_request_ns) / 1e6
                 if self.fence_ack_ns and self.stop_request_ns else None),
            "stop_request_to_backend_reset_ms":
                ((backend.last_reset_ns - self.stop_request_ns) / 1e6
                 if backend and backend.last_reset_ns and self.stop_request_ns else None),
            "backend": backend_report,
            "physical_silence_measured": False,
            "user_heard_tone": "NOT_YET_CONFIRMED",
        }
        ok = (backend is not None and not self.rejections and not self.device_losses
              and backend.device_description == self.expected_description)
        if self.play and backend is not None:
            ok = (ok and self.reason == "TIMED_STOP" and self.written_frames == FRAME_COUNT
                  and backend.accepted_bytes == FRAME_COUNT * 2
                  and self.fence_ack_ns is not None and backend.reset_count >= 2)
        elif not self.play and backend is not None:
            ok = ok and self.reason == "PREFLIGHT_ONLY" and backend.accepted_bytes == 0
        report["status"] = "PASSED" if ok else "FAILED"
        return report, 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--expected-description", required=True)
    parser.add_argument("--play", action="store_true",
                        help="Opt into one physical tone; omission performs silent preflight")
    args = parser.parse_args()
    app = QCoreApplication([])
    report, code = PhysicalProbe(args.device_id, args.expected_description, args.play).report()
    print(json.dumps(report, sort_keys=True))
    _ = app
    return code


if __name__ == "__main__":
    raise SystemExit(main())
