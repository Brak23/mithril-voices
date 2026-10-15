"""Passive deterministic doubles for future coordinator/process/audio tests.

These doubles deliberately do not enforce cancellation or generation fencing.
The product must issue those decisions; tests inspect the recorded effects.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ManualClock:
    now_ms: int = 0

    def advance(self, delta_ms: int) -> int:
        if isinstance(delta_ms, bool) or not isinstance(delta_ms, int) or delta_ms < 0:
            raise ValueError("Clock advance must be a nonnegative integer")
        self.now_ms += delta_ms
        return self.now_ms


@dataclass
class HeldProcess:
    """Record submitted messages and release synthetic replies on explicit demand."""

    submitted: list[dict[str, Any]] = field(default_factory=list)
    held: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    alive: bool = True

    def submit(self, message: dict[str, Any]) -> None:
        if not self.alive:
            raise RuntimeError("Synthetic child is dead")
        self.submitted.append(deepcopy(message))

    def hold(self, label: str, reply: dict[str, Any]) -> None:
        self.held.append((label, deepcopy(reply)))

    def release(self, label: str) -> dict[str, Any]:
        for index, (held_label, reply) in enumerate(self.held):
            if held_label == label:
                self.held.pop(index)
                return deepcopy(reply)
        raise LookupError("No held synthetic reply with that label")

    def crash(self) -> None:
        self.alive = False


@dataclass(frozen=True)
class SinkCall:
    kind: str
    generation: int
    request_id: str | None = None
    unit_id: str | None = None


@dataclass
class RecordingSink:
    """Record every attempted write, including a stale one that must fail tests."""

    calls: list[SinkCall] = field(default_factory=list)

    def fence(self, generation: int) -> None:
        self.calls.append(SinkCall("fence", generation))

    def acknowledge_fence(self, generation: int) -> None:
        self.calls.append(SinkCall("fence_ack", generation))

    def write(self, generation: int, request_id: str, unit_id: str) -> None:
        self.calls.append(SinkCall("write", generation, request_id, unit_id))


def post_fence_writes(calls: list[SinkCall]) -> list[SinkCall]:
    """Independent observation of writes after each fence acknowledgment."""
    acknowledged = False
    writes: list[SinkCall] = []
    for call in calls:
        if call.kind == "fence_ack":
            acknowledged = True
        elif call.kind == "write" and acknowledged:
            writes.append(call)
    return writes
