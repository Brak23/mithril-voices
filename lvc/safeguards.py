"""Deterministic host cancellation and final audio admission primitives.

These have no Qt, process, or audio device side effects. A future supervised
worker/audio-thread adapter must deliver the emitted actions and recheck
admission immediately before each physical sink write.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import UUID

from lvc.core import RequestToken, State

Terminal = Literal["completed", "failed", "canceled"]
AudioSource = Literal["worker", "cache"]
MAX_LEDGER_RECORDS = 256


@dataclass(frozen=True)
class ControlEffect:
    kind: Literal["send_cancel", "cancel_ack_timeout", "terminate_tree"]
    request_id: UUID
    worker_instance_id: UUID


@dataclass(frozen=True)
class WorkerRecord:
    token: RequestToken
    worker_instance_id: UUID
    effective_outcome: Terminal | None = None
    worker_terminal: Terminal | None = None
    cancel_started_ms: int | None = None
    cancel_acknowledged: bool = False
    ack_timeout_reported: bool = False
    termination_requested: bool = False
    reclaimed: bool = False


@dataclass(frozen=True)
class WorkerLedger:
    session_id: UUID
    records: tuple[WorkerRecord, ...] = ()
    now_ms: int = 0

    def _time(self, now_ms: int) -> None:
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < self.now_ms:
            raise ValueError("Worker ledger requires monotonic milliseconds")

    def record(self, request_id: UUID) -> WorkerRecord:
        for record in self.records:
            if record.token.request_id == request_id:
                return record
        raise LookupError("Unknown worker request")

    def _update(self, changed: WorkerRecord, now_ms: int) -> WorkerLedger:
        return replace(self, now_ms=now_ms, records=tuple(
            changed if item.token.request_id == changed.token.request_id else item
            for item in self.records
        ))

    def submit(self, token: RequestToken, worker_instance_id: UUID, now_ms: int) -> WorkerLedger:
        self._time(now_ms)
        if token.session_id != self.session_id:
            raise ValueError("Request session differs from worker ledger")
        if any(item.token.request_id == token.request_id for item in self.records):
            raise ValueError("Duplicate request ID")
        if any(item.worker_instance_id == worker_instance_id and not item.reclaimed for item in self.records):
            raise ValueError("Worker instance is busy")
        retained = self.records
        if len(retained) >= MAX_LEDGER_RECORDS:
            retained = tuple(item for item in retained if not item.reclaimed)
        if len(retained) >= MAX_LEDGER_RECORDS:
            raise ValueError("Worker ledger is full")
        return replace(self, now_ms=now_ms, records=retained + (WorkerRecord(token, worker_instance_id),))

    def cancel(self, request_id: UUID, now_ms: int) -> tuple[WorkerLedger, tuple[ControlEffect, ...]]:
        self._time(now_ms)
        item = self.record(request_id)
        if item.effective_outcome is not None:
            return replace(self, now_ms=now_ms), ()
        changed = replace(item, effective_outcome="canceled", cancel_started_ms=now_ms)
        return self._update(changed, now_ms), (
            ControlEffect("send_cancel", request_id, item.worker_instance_id),
        )

    def cancel_ack(self, request_id: UUID, worker_instance_id: UUID, now_ms: int) -> WorkerLedger:
        self._time(now_ms)
        try:
            item = self.record(request_id)
        except LookupError:
            return replace(self, now_ms=now_ms)  # A duplicate after bounded history pruning.
        if item.worker_instance_id != worker_instance_id or item.cancel_started_ms is None or item.reclaimed:
            return replace(self, now_ms=now_ms)
        return self._update(replace(item, cancel_acknowledged=True), now_ms)

    def terminal(self, request_id: UUID, worker_instance_id: UUID, outcome: Terminal,
                 now_ms: int) -> tuple[WorkerLedger, Terminal | None]:
        self._time(now_ms)
        try:
            item = self.record(request_id)
        except LookupError:
            return replace(self, now_ms=now_ms), None
        if item.worker_instance_id != worker_instance_id or item.worker_terminal is not None or item.reclaimed:
            return replace(self, now_ms=now_ms), None
        accepted = item.effective_outcome is None
        # A terminal IPC message settles the logical result; only observing the
        # process tree exit releases physical capacity and stops cancel escalation.
        changed = replace(item, worker_terminal=outcome,
                          effective_outcome=outcome if accepted else item.effective_outcome)
        return self._update(changed, now_ms), outcome if accepted else None

    def tree_exit(self, worker_instance_id: UUID, now_ms: int) -> WorkerLedger:
        self._time(now_ms)
        records = tuple(
            replace(item, reclaimed=True, effective_outcome=item.effective_outcome or "failed")
            if item.worker_instance_id == worker_instance_id and not item.reclaimed else item
            for item in self.records
        )
        return replace(self, now_ms=now_ms, records=records)

    def tick(self, now_ms: int) -> tuple[WorkerLedger, tuple[ControlEffect, ...]]:
        self._time(now_ms)
        effects: list[ControlEffect] = []
        records: list[WorkerRecord] = []
        for item in self.records:
            start = item.cancel_started_ms
            if start is not None and not item.reclaimed:
                if now_ms - start >= 250 and not item.cancel_acknowledged and not item.ack_timeout_reported:
                    effects.append(ControlEffect("cancel_ack_timeout", item.token.request_id,
                                                 item.worker_instance_id))
                    item = replace(item, ack_timeout_reported=True)
                if now_ms - start >= 1000 and not item.termination_requested:
                    effects.append(ControlEffect("terminate_tree", item.token.request_id,
                                                 item.worker_instance_id))
                    item = replace(item, termination_requested=True)
            records.append(item)
        return replace(self, now_ms=now_ms, records=tuple(records)), tuple(effects)

    def outcome(self, request_id: UUID) -> Terminal | None:
        return self.record(request_id).effective_outcome

    def audio_eligible(self, request_id: UUID, source: AudioSource) -> bool:
        try:
            item = self.record(request_id)
        except LookupError:
            return source == "cache"
        return source == "worker" and item.effective_outcome == "completed"


@dataclass(frozen=True)
class AudioUnit:
    token: RequestToken
    unit_id: str
    index: int
    total_frames: int
    source: AudioSource = "worker"
    written_frames: int = 0
    outstanding_frames: int = 0


class SinkWriter(Protocol):
    def write(self, generation: int, request_id: str, unit_id: str) -> None: ...


def _generation_current(host: State, token: RequestToken) -> bool:
    """Check live host authorization at the last possible write boundary."""
    return (host.session_id == token.session_id and host.generation == token.generation
            and host.intent == token.intent and host.page == token.page
            and host.prepared_token == token)


@dataclass(frozen=True)
class AudioGate:
    session_id: UUID
    minimum_generation: int = 0
    acknowledged_generation: int = 0
    sink_epoch: int = 0
    completed_index: int = -1
    unit: AudioUnit | None = None

    def fence(self, generation: int) -> AudioGate:
        if generation < self.minimum_generation:
            raise ValueError("Audio fence cannot move backward")
        return replace(self, minimum_generation=generation, unit=None, completed_index=-1)

    def ack_fence(self, generation: int, sink_epoch: int) -> AudioGate:
        if generation != self.minimum_generation or sink_epoch < self.sink_epoch:
            raise ValueError("Fence acknowledgment must match current generation and sink")
        return replace(self, acknowledged_generation=generation, sink_epoch=sink_epoch)

    def _authorized(self, host: State, ledger: WorkerLedger, token: RequestToken,
                    sink_epoch: int, source: AudioSource) -> bool:
        return (_generation_current(host, token) and token.session_id == self.session_id
                and token.generation == self.minimum_generation == self.acknowledged_generation
                and sink_epoch == self.sink_epoch and ledger.audio_eligible(token.request_id, source))

    def start_unit(self, host: State, ledger: WorkerLedger, token: RequestToken,
                   unit_id: str, index: int, total_frames: int, sink_epoch: int,
                   source: AudioSource = "worker") -> AudioGate:
        if not self._authorized(host, ledger, token, sink_epoch, source):
            raise ValueError("Audio unit is not authorized")
        if self.unit is not None or index != self.completed_index + 1 or total_frames <= 0 or not unit_id:
            raise ValueError("Audio unit order or frame count is invalid")
        return replace(self, unit=AudioUnit(token, unit_id, index, total_frames, source))

    def _current_unit(self, host: State, ledger: WorkerLedger, token: RequestToken,
                      unit_id: str, index: int, sink_epoch: int) -> AudioUnit | None:
        unit = self.unit
        if (unit is None or unit.token != token or unit.unit_id != unit_id or unit.index != index
                or not self._authorized(host, ledger, token, sink_epoch, unit.source)):
            return None
        return unit

    def write(self, host: State, ledger: WorkerLedger, token: RequestToken, unit_id: str,
              index: int, sink_epoch: int, frames: int, sink: SinkWriter) -> tuple[AudioGate, bool]:
        """Recheck authorization immediately before each bounded sink write."""
        unit = self._current_unit(host, ledger, token, unit_id, index, sink_epoch)
        if unit is None or frames <= 0 or unit.written_frames + frames > unit.total_frames:
            return self, False
        sink.write(token.generation, str(token.request_id), unit_id)
        return replace(self, unit=replace(unit, written_frames=unit.written_frames + frames,
                                          outstanding_frames=unit.outstanding_frames + frames)), True

    def drain(self, host: State, ledger: WorkerLedger, token: RequestToken, unit_id: str,
              index: int, sink_epoch: int, frames: int) -> AudioGate:
        unit = self._current_unit(host, ledger, token, unit_id, index, sink_epoch)
        if unit is None or frames < 0 or frames > unit.outstanding_frames:
            return self
        return replace(self, unit=replace(unit, outstanding_frames=unit.outstanding_frames - frames))

    def idle(self, host: State, ledger: WorkerLedger, token: RequestToken, unit_id: str,
             index: int, sink_epoch: int) -> tuple[AudioGate, bool]:
        unit = self._current_unit(host, ledger, token, unit_id, index, sink_epoch)
        if unit is None or unit.written_frames != unit.total_frames or unit.outstanding_frames != 0:
            return self, False
        return replace(self, completed_index=index, unit=None), True
