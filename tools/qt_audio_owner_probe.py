"""Controlled Qt audio-thread outcomes using verified generated PCM and a fake backend."""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import wave
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Slot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lvc.core import PageIdentity, RequestToken
from lvc.qt_audio_owner import AudioSubmission, QtAudioService
from lvc.spool import SpoolValidator
from lvc.synthetic_flow import SyntheticFlow
from tests.v2.support import RecordingSink
from tools.validate_contracts import validate_ipc

SESSION = UUID("00000000-0000-4000-8000-000000000001")
WORKER = UUID("00000000-0000-4000-8000-000000000002")
REQUEST = UUID("00000000-0000-4000-8000-000000000003")
UNIT = UUID("00000000-0000-4000-8000-000000000004")
BINDING = UUID("00000000-0000-4000-8000-000000000010")
PAGE = PageIdentity(UUID("00000000-0000-4000-8000-000000000011"), 1,
                    "quest_body", "synthetic")
EXAMPLE = json.loads((ROOT / "docs/design-v2/contracts/ipc.examples.json").read_text(encoding="utf-8"))["examples"][4]


class NoopWorker:
    def submit(self, token: RequestToken, text: str) -> None:
        _ = token, text

    def cancel(self, token: RequestToken) -> None:
        _ = token


class FakeBackend:
    synthetic = True

    def __init__(self, device_id: str, max_bytes: int, fail_write: bool = False):
        self.device_id = device_id
        self.max_bytes = max_bytes
        self.fail_write = fail_write
        self.creator_thread = QThread.currentThread()
        self.off_main_thread = self.creator_thread != QCoreApplication.instance().thread()
        self.write_bytes: list[int] = []
        self.reset_count = 0

    def write(self, pcm: bytes) -> int:
        if QThread.currentThread() != self.creator_thread:
            raise RuntimeError("Backend accessed outside its owner thread")
        if self.fail_write:
            return -2
        accepted = min(len(pcm), self.max_bytes)
        self.write_bytes.append(accepted)
        return accepted

    def reset(self) -> None:
        if QThread.currentThread() != self.creator_thread:
            raise RuntimeError("Backend reset outside its owner thread")
        self.reset_count += 1


def validated_submission(spool_root: Path, pcm: bytes | None = None) -> AudioSubmission:
    if pcm is None:
        pcm = struct.pack("<960h", *((1000 if i % 2 else -1000) for i in range(960)))
    if not pcm or len(pcm) % 2:
        raise ValueError("Synthetic PCM must contain complete Int16 frames")
    path = spool_root / f"{REQUEST}.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(pcm)
    raw = path.read_bytes()
    flow = SyntheticFlow(SESSION, WORKER, BINDING, 1, NoopWorker(),
                         RecordingSink(), SpoolValidator(spool_root, SESSION, UNIT,
                                                         spool_root.parent), validate_ipc)
    flow.read_current(REQUEST, 0)
    flow.text_accepted(REQUEST, PAGE, "Original synthetic tone.", 1)
    flow.acknowledge_fence(1, 1)
    token = flow.state.synthesis
    assert token is not None
    message = deepcopy(EXAMPLE)
    message["seq"] = 3
    message["payload"]["context"] = flow._context(token)
    message["payload"]["result"].update({
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "frame_count": len(pcm) // 2,
    })
    assert flow.receive_terminal(message, 2)
    assert flow.unit is not None and flow.unit.pcm == pcm
    return AudioSubmission(flow.state, flow.ledger, token, flow.unit)


class Probe(QObject):
    def __init__(self, case: str):
        super().__init__()
        self.case = case
        self.app = QCoreApplication.instance()
        safe_base = ROOT.parent / "test-tmp"
        safe_base.mkdir(exist_ok=True)
        self.isolated = Path(tempfile.mkdtemp(prefix="mithril-audio-", dir=safe_base))
        self.spool_root = self.isolated / str(SESSION)
        self.spool_root.mkdir()
        self.submission = validated_submission(self.spool_root)
        self.backend: FakeBackend | None = None
        self.factory_calls = 0
        max_bytes = 240 if case == "partial" else 960

        def factory(device_id: str) -> FakeBackend:
            self.factory_calls += 1
            self.backend = FakeBackend(device_id, max_bytes, case == "negative_write")
            if case == "physical_without_opt_in":
                self.backend.synthetic = False
            return self.backend

        self.service = QtAudioService(SESSION, "synthetic-selected-endpoint", factory)
        self.epoch = 0
        self.written = 0
        self.writes_at_fence: int | None = None
        self.backend_writes_at_fence: int | None = None
        self.underruns = 0
        self.rejections = 0
        self.drained = False
        self.lost = False
        self.ending = False
        self.reason = "INCOMPLETE"
        self.service.owner.fence_ack.connect(self.on_fence_ack)
        self.service.owner.write_observed.connect(self.on_write)
        self.service.owner.unit_drained.connect(self.on_drained)
        self.service.owner.underrun.connect(self.on_underrun)
        self.service.owner.rejected.connect(self.on_rejected)
        self.service.owner.device_lost.connect(self.on_device_lost)
        self.service.thread.finished.connect(self.app.quit)
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(lambda: self.finish("WATCHDOG"))
        self.watchdog.start(4000)
        if case == "no_ack":
            self.service.admit(self.submission)
        else:
            self.service.fence(1)

    @Slot(int, int)
    def on_fence_ack(self, generation: int, epoch: int) -> None:
        if generation == 1:
            self.epoch = epoch
            self.service.admit(self.submission)
        elif generation == 2 and self.case == "stop":
            self.service.idle(self.epoch)  # Old callback cannot complete.
            self.service.admit(self.submission)  # Old generation must be rejected.
            QTimer.singleShot(70, lambda: self.finish("STOP_FENCED"))

    @Slot(str, int, int)
    def on_write(self, request_id: str, frames: int, epoch: int) -> None:
        if request_id != str(REQUEST) or epoch != self.epoch:
            self.finish("WRONG_WRITE_IDENTITY")
            return
        self.written += frames
        if self.case == "stop" and self.writes_at_fence is None:
            self.writes_at_fence = self.written
            self.backend_writes_at_fence = len(self.backend.write_bytes) if self.backend else None
            self.service.fence(2)
        elif self.case == "device_loss" and not self.lost:
            self.service.device_loss()
        elif self.case == "early_idle" and self.underruns == 0 and self.written == frames:
            self.service.idle(epoch)
        elif (self.written == self.submission.unit.frames
              and (self.case in {"normal", "partial"}
                   or (self.case == "early_idle" and self.underruns))):
            self.service.drained(epoch, self.written)
            self.service.idle(epoch)

    @Slot(str, int)
    def on_underrun(self, request_id: str, epoch: int) -> None:
        if request_id == str(REQUEST) and epoch == self.epoch:
            self.underruns += 1
            if self.case == "early_idle" and self.written == self.submission.unit.frames:
                self.service.drained(epoch, self.written)
                self.service.idle(epoch)

    @Slot(str, str, int)
    def on_drained(self, request_id: str, unit_id: str, epoch: int) -> None:
        if request_id == str(REQUEST) and unit_id == str(UNIT) and epoch == self.epoch:
            self.drained = True
            self.finish("DRAINED")

    @Slot(str)
    def on_rejected(self, _code: str) -> None:
        self.rejections += 1
        if self.case == "no_ack":
            self.finish("NO_ACK_REJECTED")
        elif self.case == "physical_without_opt_in":
            self.reason = "PHYSICAL_BACKEND_REJECTED"

    @Slot(int)
    def on_device_lost(self, _generation: int) -> None:
        self.lost = True
        self.service.idle(self.epoch)
        self.service.admit(self.submission)
        QTimer.singleShot(70, lambda: self.finish("DEVICE_LOST"))

    def finish(self, reason: str) -> None:
        if self.ending:
            return
        self.ending = True
        self.reason = reason
        self.watchdog.stop()
        self.service.close()

    def report(self) -> tuple[dict, int]:
        self.app.exec()
        self.service.thread.wait(1000)  # Probe only, after event-loop shutdown.
        safe_base = (ROOT.parent / "test-tmp").resolve()
        isolated = self.isolated.resolve()
        if not isolated.is_relative_to(safe_base) or not isolated.name.startswith("mithril-audio-"):
            raise RuntimeError("Refusing cleanup outside owned test directory")
        shutil.rmtree(isolated)
        backend = self.backend
        report = {"case": self.case, "status": "FAILED", "reason": self.reason,
                  "physical_enabled": self.service.physical_enabled,
                  "backend_off_main_thread": backend.off_main_thread if backend else False,
                  "selected_endpoint": "synthetic-selected-endpoint",
                  "written_frames": self.written, "writes_at_fence": self.writes_at_fence,
                  "backend_writes_at_fence": self.backend_writes_at_fence,
                  "backend_factory_calls": self.factory_calls,
                  "backend_writes": len(backend.write_bytes) if backend else 0,
                  "largest_backend_write_bytes": max(backend.write_bytes, default=0) if backend else 0,
                  "backend_resets": backend.reset_count if backend else 0,
                  "underruns": self.underruns, "rejections": self.rejections,
                  "drained": self.drained, "device_lost": self.lost,
                  "verified_pcm_bytes": len(self.submission.unit.pcm)}
        ok = (not report["physical_enabled"] and report["backend_off_main_thread"]
              and self.factory_calls == 1)
        if self.case in {"normal", "partial", "early_idle"}:
            ok = ok and self.reason == "DRAINED" and self.drained and self.written == 960
        if self.case == "partial":
            ok = ok and report["largest_backend_write_bytes"] <= 240 and report["backend_writes"] >= 8
        if self.case == "early_idle":
            ok = ok and self.underruns >= 1
        if self.case == "stop":
            ok = ok and self.reason == "STOP_FENCED" and self.writes_at_fence is not None
            ok = ok and self.written == self.writes_at_fence and not self.drained
            ok = ok and report["backend_writes"] == self.backend_writes_at_fence
            ok = ok and self.rejections >= 1 and report["backend_resets"] >= 2
        if self.case in {"device_loss", "negative_write"}:
            ok = ok and self.reason == "DEVICE_LOST" and self.lost and not self.drained
            ok = ok and report["backend_resets"] >= 2
        if self.case == "device_loss":
            ok = ok and self.rejections >= 1
        if self.case == "negative_write":
            ok = ok and self.written == 0
        if self.case == "no_ack":
            ok = ok and self.reason == "NO_ACK_REJECTED" and self.written == 0
        if self.case == "physical_without_opt_in":
            ok = ok and self.reason == "PHYSICAL_BACKEND_REJECTED"
            ok = ok and self.written == 0 and self.rejections == 1
        report["status"] = "PASSED" if ok else "FAILED"
        return report, 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["normal", "partial", "early_idle",
                                           "stop", "device_loss", "no_ack",
                                           "negative_write", "physical_without_opt_in"], required=True)
    args = parser.parse_args()
    app = QCoreApplication([])
    result, code = Probe(args.case).report()
    print(json.dumps(result, sort_keys=True))
    _ = app
    return code


if __name__ == "__main__":
    raise SystemExit(main())
