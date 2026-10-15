"""Single-unit synthetic coordinator seam; audio acceptance and sink are injected.

This joins already-tested control, cancellation and admission primitives. It is
not an artifact verifier, production worker launcher, or physical audio owner.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol
from uuid import UUID

from lvc.core import (
    PageIdentity,
    ReadCurrent,
    RendererDrained,
    RendererStarted,
    RequestToken,
    State,
    Stop,
    ValidatedText,
    WorkerCompleted,
    WorkerFailed,
    reduce,
)
from lvc.safeguards import AudioGate, SinkWriter, WorkerLedger


@dataclass(frozen=True)
class AcceptedUnit:
    artifact: str
    unit_id: str
    frames: int


class WorkerPort(Protocol):
    def submit(self, token: RequestToken, text: str) -> None: ...
    def cancel(self, token: RequestToken) -> None: ...


class SinkPort(SinkWriter, Protocol):
    def fence(self, generation: int) -> None: ...
    def acknowledge_fence(self, generation: int) -> None: ...


class SyntheticFlow:
    """Bounded one-unit adapter with no implicit sink fence acknowledgment."""

    def __init__(self, session: UUID, worker_id: UUID, binding_id: UUID,
                 geometry_epoch: int, worker: WorkerPort, sink: SinkPort,
                 accept_audio: Callable[[dict[str, Any]], AcceptedUnit],
                 validate_message: Callable[[dict[str, Any]], None]):
        if geometry_epoch < 1:
            raise ValueError("Geometry epoch must be positive")
        self.state = State(session_id=session, bound=True)
        self.ledger = WorkerLedger(session)
        self.gate = AudioGate(session)
        self.worker_id = worker_id
        self.binding_id = binding_id
        self.geometry_epoch = geometry_epoch
        self.worker = worker
        self.sink = sink
        self.accept_audio = accept_audio
        self.validate_message = validate_message
        self.unit: AcceptedUnit | None = None

    def _effects(self, effects: tuple, now_ms: int) -> None:
        for effect in effects:
            if effect.kind == "fence":
                self.gate = self.gate.fence(effect.generation)
                self.sink.fence(effect.generation)
                self.unit = None
            elif effect.kind == "cancel" and effect.token is not None:
                try:
                    self.ledger, controls = self.ledger.cancel(effect.token.request_id, now_ms)
                except LookupError:
                    continue  # Capture was pending; no worker was submitted.
                if controls:
                    self.worker.cancel(effect.token)

    def read_current(self, request_id: UUID, now_ms: int) -> None:
        self.state, effects = reduce(self.state, ReadCurrent(request_id), now_ms)
        self._effects(effects, now_ms)

    def acknowledge_fence(self, generation: int, sink_epoch: int) -> None:
        self.gate = self.gate.ack_fence(generation, sink_epoch)
        self.sink.acknowledge_fence(generation)
        self._start_unit_if_ready()

    def text_accepted(self, request_id: UUID, page: PageIdentity, text: str, now_ms: int) -> None:
        self.state, effects = reduce(self.state, ValidatedText(request_id, page, text), now_ms)
        for effect in effects:
            if effect.kind == "synthesize" and effect.token is not None:
                self.ledger = self.ledger.submit(effect.token, self.worker_id, now_ms)
                self.worker.submit(effect.token, text)

    def stop(self, now_ms: int) -> None:
        self.state, effects = reduce(self.state, Stop(), now_ms)
        self._effects(effects, now_ms)

    def worker_tree_exited(self, replacement_id: UUID, now_ms: int) -> None:
        """Retire the physically exited channel before assigning new work."""
        if replacement_id == self.worker_id or any(
            item.worker_instance_id == replacement_id for item in self.ledger.records
        ):
            raise ValueError("Replacement worker instance ID must be new")
        self.ledger = self.ledger.tree_exit(self.worker_id, now_ms)
        self.worker_id = replacement_id

    def _context(self, token: RequestToken) -> dict[str, Any]:
        page = token.page
        if page is None:
            raise ValueError("Submitted synthesis has no page")
        return {"intent_epoch": token.intent, "generation": token.generation,
                "binding_id": str(self.binding_id), "interaction_id": str(page.interaction_id),
                "surface_id": page.surface, "page_revision": page.revision,
                "geometry_epoch": self.geometry_epoch, "origin": token.origin}

    def _fail(self, token: RequestToken, code: str, now_ms: int) -> None:
        self.ledger, _ = self.ledger.terminal(token.request_id, self.worker_id, "failed", now_ms)
        self.state, effects = reduce(self.state, WorkerFailed(token, code), now_ms)
        self._effects(effects, now_ms)

    def _start_unit_if_ready(self) -> None:
        token, unit = self.state.prepared_token, self.unit
        if token is None or unit is None or self.gate.unit is not None:
            return
        try:
            self.gate = self.gate.start_unit(self.state, self.ledger, token,
                                             unit.unit_id, 0, unit.frames, self.gate.sink_epoch)
        except ValueError:
            pass  # Remains staged until the matching fence acknowledgment arrives.

    def receive_terminal(self, message: dict[str, Any], now_ms: int) -> bool:
        """Receive a terminal from a separately supervised, ordered IPC channel."""
        try:
            self.validate_message(message)
            if (message["session_id"] != str(self.state.session_id)
                    or message["type"] not in {"completed", "failed"}):
                raise ValueError("Terminal sender or type invalid")
            payload = message["payload"]
            request_id = UUID(payload["request_id"])
            record = self.ledger.record(request_id)
            token = record.token
            if message["worker_instance_id"] != str(self.worker_id):
                if (message["worker_instance_id"] == str(record.worker_instance_id)
                        and record.reclaimed):
                    self.state = replace(self.state, stale_results=self.state.stale_results + 1)
                    return False  # Retired-channel event cannot fail a healthy replacement.
                raise ValueError("Terminal sender invalid")
            if message["type"] == "completed" and payload["context"] != self._context(token):
                raise ValueError("Completed context differs from submission")
        except (KeyError, ValueError, LookupError, TypeError):
            active = self.state.synthesis
            if active is not None:
                self._fail(active, "PROTOCOL_INVALID", now_ms)
            return False
        if record.effective_outcome is not None or record.worker_terminal is not None:
            self.ledger, _ = self.ledger.terminal(request_id, self.worker_id, "completed", now_ms)
            # Canceled or duplicate terminal; do not read or accept any artifact.
            self.state, _ = reduce(self.state, WorkerCompleted(token, "stale"), now_ms)
            return False
        if message["type"] == "failed":
            self._fail(token, payload["code"], now_ms)
            return False
        if self.state.synthesis != token:
            self.state, _ = reduce(self.state, WorkerCompleted(token, "stale"), now_ms)
            return False
        try:
            descriptor = payload["result"]
            if descriptor["kind"] != "audio":
                raise ValueError("Expected audio result")
            unit = self.accept_audio(descriptor)
            if unit.unit_id != descriptor["unit_id"] or unit.frames < 1 or not unit.artifact:
                raise ValueError("Audio verifier returned mismatched unit")
        except (ValueError, KeyError, TypeError, OSError):
            self._fail(token, "AUDIO_INVALID", now_ms)
            return False
        self.ledger, effective = self.ledger.terminal(request_id, self.worker_id,
                                                       "completed", now_ms)
        if effective is None:
            return False
        self.state, effects = reduce(self.state, WorkerCompleted(token, unit.artifact), now_ms)
        if len(effects) != 1 or effects[0].kind != "prepare_audio":
            return False
        self.unit = unit
        # A missing fence acknowledgment keeps the unit staged without writing.
        self._start_unit_if_ready()
        return True

    def pump(self, frames: int) -> bool:
        token, unit = self.state.prepared_token, self.unit
        if token is None or unit is None or self.gate.unit is None:
            return False
        self.gate, wrote = self.gate.write(self.state, self.ledger, token, unit.unit_id,
                                           0, self.gate.sink_epoch, frames, self.sink)
        if wrote and self.state.playback == "PREPARING":
            self.state, _ = reduce(self.state, RendererStarted(token, unit.artifact), 0)
        return wrote

    def drain(self, frames: int) -> None:
        token, unit = self.state.prepared_token, self.unit
        if token is not None and unit is not None:
            self.gate = self.gate.drain(self.state, self.ledger, token, unit.unit_id,
                                        0, self.gate.sink_epoch, frames)

    def sink_idle(self) -> bool:
        token, unit = self.state.prepared_token, self.unit
        if token is None or unit is None:
            return False
        self.gate, complete = self.gate.idle(self.state, self.ledger, token,
                                             unit.unit_id, 0, self.gate.sink_epoch)
        if complete:
            self.state, _ = reduce(self.state, RendererDrained(token, unit.artifact), 0)
            self.unit = None
        return complete
