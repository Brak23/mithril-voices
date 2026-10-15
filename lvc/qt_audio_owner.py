"""One Qt event-loop audio owner with an injected synthetic backend only.

No QAudioSink or device is constructed here. The backend is deliberately
restricted to synthetic implementations until endpoint qualification is done.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from lvc.core import RequestToken, State
from lvc.safeguards import AudioGate, WorkerLedger
from lvc.synthetic_flow import AcceptedUnit

PUMP_INTERVAL_MS = 10
PUMP_FRAMES = 480  # Ten milliseconds at 48 kHz.
MAX_PREPARED_FRAMES = 24_000  # 500 ms of accepted, not-yet-drained PCM.


class SyntheticBackend(Protocol):
    synthetic: bool
    device_id: str

    def write(self, pcm: bytes) -> int:
        """Return accepted bytes, possibly less than requested."""
        ...

    def reset(self) -> None: ...


@dataclass(frozen=True)
class AudioSubmission:
    state: State
    ledger: WorkerLedger
    token: RequestToken
    unit: AcceptedUnit


class FenceFloor:
    """Synchronous Stop fence checked immediately before every backend write."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._minimum = 0

    def raise_to(self, generation: int) -> None:
        with self._lock:
            self._minimum = max(self._minimum, generation)

    def permits(self, generation: int) -> bool:
        with self._lock:
            return generation >= self._minimum


class _AudioOwner(QObject):
    fence_ack = Signal(int, int)
    unit_drained = Signal(str, str, int)
    write_observed = Signal(str, int, int)
    underrun = Signal(str, int)
    rejected = Signal(str)
    device_lost = Signal(int)
    stopped = Signal()

    def __init__(self, session, selected_device_id: str, floor: FenceFloor,
                 backend_factory: Callable[[str], SyntheticBackend],
                 allow_physical: bool):
        super().__init__()
        self.session = session
        self.selected_device_id = selected_device_id
        self.floor = floor
        self.backend_factory = backend_factory
        self.allow_physical = allow_physical
        self.backend: SyntheticBackend | None = None
        self.gate = AudioGate(session)
        self.current: AudioSubmission | None = None
        self.timer: QTimer | None = None
        self.available = True

    @Slot()
    def start(self) -> None:
        try:
            backend = self.backend_factory(self.selected_device_id)
        except (OSError, RuntimeError, ValueError):
            self.rejected.emit("BACKEND_CREATION_FAILED")
            self.stopped.emit()
            return
        if (backend.device_id != self.selected_device_id
                or (not backend.synthetic and not self.allow_physical)):
            self.rejected.emit("BACKEND_NOT_SYNTHETIC_OR_ENDPOINT_MISMATCH")
            self.stopped.emit()
            return
        self.backend = backend
        timer = QTimer(self)
        timer.setInterval(PUMP_INTERVAL_MS)
        timer.timeout.connect(self.pump)
        timer.start()
        self.timer = timer

    @Slot(int)
    def fence(self, generation: int) -> None:
        if self.backend is None or generation < self.gate.minimum_generation:
            return
        self.gate = self.gate.fence(generation)
        self.current = None
        self.backend.reset()
        epoch = self.gate.sink_epoch + 1
        self.gate = self.gate.ack_fence(generation, epoch)
        self.fence_ack.emit(generation, epoch)

    @Slot(object)
    def admit(self, submission: AudioSubmission) -> None:
        unit = submission.unit
        if (self.backend is None or not self.available or self.current is not None
                or submission.token.session_id != self.session
                or not self.floor.permits(submission.token.generation)
                or not unit.pcm or len(unit.pcm) != unit.frames * 2):
            self.rejected.emit("UNIT_NOT_ADMISSIBLE")
            return
        try:
            self.gate = self.gate.start_unit(submission.state, submission.ledger,
                                             submission.token, unit.unit_id, 0,
                                             unit.frames, self.gate.sink_epoch)
        except ValueError:
            self.rejected.emit("UNIT_NOT_CURRENT")
            return
        self.current = submission

    def write(self, generation: int, request_id: str, unit_id: str, frames: int) -> int:
        """Called only by AudioGate after its final identity checks."""
        submission, gate_unit, backend = self.current, self.gate.unit, self.backend
        if (submission is None or gate_unit is None or backend is None
                or not self.available or not self.floor.permits(generation)
                or str(submission.token.request_id) != request_id
                or submission.unit.unit_id != unit_id):
            return 0
        offset = gate_unit.written_frames * 2
        chunk = submission.unit.pcm[offset:offset + frames * 2]
        accepted_bytes = backend.write(chunk)
        if type(accepted_bytes) is not int or not 0 <= accepted_bytes <= len(chunk) or accepted_bytes % 2:
            raise ValueError("Synthetic backend returned invalid byte count")
        return accepted_bytes // 2

    @Slot()
    def pump(self) -> None:
        submission, gate_unit = self.current, self.gate.unit
        if submission is None or gate_unit is None or not self.available:
            return
        if not self.floor.permits(submission.token.generation):
            return
        remaining = submission.unit.frames - gate_unit.written_frames
        capacity = MAX_PREPARED_FRAMES - gate_unit.outstanding_frames
        frames = min(PUMP_FRAMES, remaining, capacity)
        if frames <= 0:
            return
        try:
            self.gate, wrote = self.gate.write(
                submission.state, submission.ledger, submission.token,
                submission.unit.unit_id, 0, self.gate.sink_epoch, frames, self,
            )
        except (OSError, RuntimeError, ValueError):
            self.lose_device()
            return
        if wrote and self.gate.unit is not None:
            accepted = self.gate.unit.written_frames - gate_unit.written_frames
            self.write_observed.emit(str(submission.token.request_id), accepted,
                                     self.gate.sink_epoch)

    @Slot(int, int)
    def drained(self, epoch: int, frames: int) -> None:
        submission = self.current
        if (submission is None or epoch != self.gate.sink_epoch
                or frames < 0 or not self.available):
            return
        self.gate = self.gate.drain(submission.state, submission.ledger,
                                    submission.token, submission.unit.unit_id,
                                    0, epoch, frames)

    @Slot(int)
    def idle(self, epoch: int) -> None:
        submission = self.current
        if submission is None or epoch != self.gate.sink_epoch or not self.available:
            return
        self.gate, completed = self.gate.idle(submission.state, submission.ledger,
                                               submission.token, submission.unit.unit_id,
                                               0, epoch)
        if completed:
            self.unit_drained.emit(str(submission.token.request_id),
                                   submission.unit.unit_id, epoch)
            self.current = None
        else:
            self.underrun.emit(str(submission.token.request_id), epoch)

    @Slot()
    def lose_device(self) -> None:
        if not self.available or self.backend is None:
            return
        self.available = False
        next_generation = self.gate.minimum_generation + 1
        self.floor.raise_to(next_generation)
        self.gate = self.gate.fence(next_generation)
        self.current = None
        self.backend.reset()
        self.device_lost.emit(next_generation)

    @Slot()
    def close(self) -> None:
        if self.timer is not None:
            self.timer.stop()
        if self.backend is not None:
            self.backend.reset()
        self.current = None
        self.stopped.emit()


class QtAudioService(QObject):
    """Thread-safe command facade with an explicit physical-output opt-in."""

    _fence = Signal(int)
    _admit = Signal(object)
    _drained = Signal(int, int)
    _idle = Signal(int)
    _device_loss = Signal()
    _close = Signal()

    def __init__(self, session, selected_device_id: str,
                 backend_factory: Callable[[str], SyntheticBackend],
                 *, allow_physical: bool = False):
        super().__init__()
        if not selected_device_id:
            raise ValueError("Explicit synthetic endpoint identity required")
        self.physical_enabled = allow_physical
        self.floor = FenceFloor()
        self.thread = QThread()
        self.owner = _AudioOwner(session, selected_device_id, self.floor,
                                 backend_factory, allow_physical)
        self.owner.moveToThread(self.thread)
        self.thread.started.connect(self.owner.start)
        self._fence.connect(self.owner.fence, Qt.QueuedConnection)
        self._admit.connect(self.owner.admit, Qt.QueuedConnection)
        self._drained.connect(self.owner.drained, Qt.QueuedConnection)
        self._idle.connect(self.owner.idle, Qt.QueuedConnection)
        self._device_loss.connect(self.owner.lose_device, Qt.QueuedConnection)
        self._close.connect(self.owner.close, Qt.QueuedConnection)
        self.owner.stopped.connect(self.thread.quit)
        self.thread.finished.connect(self.owner.deleteLater)
        self.thread.start()

    def fence(self, generation: int) -> None:
        self.floor.raise_to(generation)
        self._fence.emit(generation)

    def admit(self, submission: AudioSubmission) -> None:
        self._admit.emit(submission)

    def drained(self, epoch: int, frames: int) -> None:
        self._drained.emit(epoch, frames)

    def idle(self, epoch: int) -> None:
        self._idle.emit(epoch)

    def device_loss(self) -> None:
        self._device_loss.emit()

    def close(self) -> None:
        self._close.emit()
