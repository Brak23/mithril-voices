"""Independent synthetic outcomes for cancellation and final audio admission."""
from dataclasses import replace
from uuid import UUID

import pytest

from lvc import safeguards
from lvc.core import (
    PageIdentity,
    ReadCurrent,
    RequestToken,
    State,
    Stop,
    ValidatedText,
    WorkerCompleted,
    reduce,
)
from lvc.safeguards import MAX_LEDGER_RECORDS, AudioGate, WorkerLedger
from tests.v2.support import HeldProcess, ManualClock, RecordingSink

SESSION = UUID(int=101)
WORKER_A = UUID(int=201)
WORKER_B = UUID(int=202)
PAGE = PageIdentity(UUID(int=301), 1, "quest", "content-a")


def prepared(state: State, request_id: int) -> tuple[State, RequestToken]:
    state, _ = reduce(state, ReadCurrent(UUID(int=request_id)), 0)
    state, _ = reduce(state, ValidatedText(UUID(int=request_id), PAGE, "synthetic text"), 0)
    token = state.synthesis
    assert token is not None
    state, effects = reduce(state, WorkerCompleted(token, "original-synthetic-audio"), 0)
    assert [effect.kind for effect in effects] == ["prepare_audio"]
    return state, token


def acknowledged_gate(state: State) -> AudioGate:
    return AudioGate(SESSION).fence(state.generation).ack_fence(state.generation, 0)


def test_cancel_ack_keeps_physical_slot_occupied_until_terminal_or_tree_exit():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, token = prepared(state, 1)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, clock.now_ms)
    ledger, effects = ledger.cancel(token.request_id, clock.now_ms)
    assert [effect.kind for effect in effects] == ["send_cancel"]
    assert ledger.outcome(token.request_id) == "canceled"
    ledger = ledger.cancel_ack(token.request_id, WORKER_A, clock.advance(100))
    assert not ledger.record(token.request_id).reclaimed
    with pytest.raises(ValueError, match="busy"):
        ledger.submit(replace(token, request_id=UUID(int=2)), WORKER_A, clock.now_ms)
    ledger, effects = ledger.tick(clock.advance(900))
    assert [effect.kind for effect in effects] == ["terminate_tree"]
    ledger, effects = ledger.tick(clock.advance(1))
    assert effects == ()
    ledger = ledger.tree_exit(WORKER_A, clock.now_ms)
    assert ledger.record(token.request_id).reclaimed
    assert ledger.outcome(token.request_id) == "canceled"


def test_late_completed_and_duplicate_terminals_never_resurrect_canceled_a():
    state = State(session_id=SESSION, bound=True)
    state, token = prepared(state, 3)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, _ = ledger.cancel(token.request_id, 0)
    ledger, effective = ledger.terminal(token.request_id, WORKER_A, "completed", 100)
    assert effective is None and ledger.outcome(token.request_id) == "canceled"
    ledger, effective = ledger.terminal(token.request_id, WORKER_A, "failed", 101)
    assert effective is None and ledger.record(token.request_id).worker_terminal == "completed"
    _, fresh_token = prepared(State(session_id=SESSION, bound=True), 4)
    ledger = ledger.submit(fresh_token, WORKER_B, 101)
    ledger, effective = ledger.terminal(fresh_token.request_id, WORKER_B, "completed", 102)
    assert effective == "completed" and ledger.outcome(fresh_token.request_id) == "completed"


def test_old_cache_or_worker_audio_cannot_write_after_stop_even_before_fence_ack():
    state = State(session_id=SESSION, bound=True)
    state, token = prepared(state, 5)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, _ = ledger.terminal(token.request_id, WORKER_A, "completed", 1)
    gate = acknowledged_gate(state).start_unit(state, ledger, token, "unit-a", 0, 10, 0)
    assert gate.unit is not None
    stopped, effects = reduce(state, Stop(), 2)
    assert effects[0].kind == "fence"
    sink = RecordingSink()
    gate, wrote = gate.write(stopped, ledger, token, "unit-a", 0, 0, 2, sink)
    assert not wrote and sink.calls == []  # host snapshot changed before priority fence delivery
    gate = gate.fence(stopped.generation)
    sink.fence(stopped.generation)
    gate, wrote = gate.write(state, ledger, token, "unit-a", 0, 0, 2, sink)
    assert not wrote and all(call.kind != "write" for call in sink.calls)
    gate = gate.ack_fence(stopped.generation, 1)
    sink.acknowledge_fence(stopped.generation)
    gate, wrote = gate.write(state, ledger, token, "unit-a", 0, 0, 2, sink)
    assert not wrote and all(call.kind != "write" for call in sink.calls)


def test_only_b_writes_after_a_stop_fence_and_old_idle_cannot_advance_b():
    state = State(session_id=SESSION, bound=True)
    state, a = prepared(state, 6)
    ledger = WorkerLedger(SESSION).submit(a, WORKER_A, 0)
    ledger, _ = ledger.terminal(a.request_id, WORKER_A, "completed", 1)
    gate = acknowledged_gate(state).start_unit(state, ledger, a, "unit-a", 0, 8, 0)
    sink = RecordingSink()
    gate, wrote = gate.write(state, ledger, a, "unit-a", 0, 0, 3, sink)
    assert wrote
    stopped, _ = reduce(state, Stop(), 2)
    gate = gate.fence(stopped.generation)
    sink.fence(stopped.generation)
    gate = gate.ack_fence(stopped.generation, 1)
    sink.acknowledge_fence(stopped.generation)
    b_state, b = prepared(stopped, 7)
    ledger = ledger.submit(b, WORKER_B, 3)
    ledger, _ = ledger.terminal(b.request_id, WORKER_B, "completed", 4)
    gate = gate.fence(b_state.generation).ack_fence(b_state.generation, 2)
    gate = gate.start_unit(b_state, ledger, b, "unit-b", 0, 5, 2)
    gate, completed = gate.idle(b_state, ledger, a, "unit-a", 0, 0)
    assert not completed and gate.completed_index == -1
    gate, wrote = gate.write(b_state, ledger, b, "unit-b", 0, 2, 5, sink)
    assert wrote and [call.request_id for call in sink.calls if call.kind == "write"] == [str(a.request_id), str(b.request_id)]
    gate, completed = gate.idle(b_state, ledger, b, "unit-b", 0, 2)
    assert not completed  # submitted frames are still outstanding in the ring
    gate = gate.drain(b_state, ledger, b, "unit-b", 0, 2, 5)
    gate, completed = gate.idle(b_state, ledger, b, "unit-b", 0, 2)
    assert completed and gate.completed_index == 0


def test_mutation_removing_final_generation_check_is_caught(monkeypatch):
    state = State(session_id=SESSION, bound=True)
    state, token = prepared(state, 8)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, _ = ledger.terminal(token.request_id, WORKER_A, "completed", 1)
    gate = acknowledged_gate(state).start_unit(state, ledger, token, "unit", 0, 4, 0)
    stopped, _ = reduce(state, Stop(), 2)

    def assert_no_stale_write():
        sink = RecordingSink()
        _, wrote = gate.write(stopped, ledger, token, "unit", 0, 0, 1, sink)
        assert not wrote and sink.calls == []

    assert_no_stale_write()
    monkeypatch.setattr(safeguards, "_generation_current", lambda *_: True)
    with pytest.raises(AssertionError):
        assert_no_stale_write()


def test_missing_cancel_ack_reports_at_250_ms_and_still_terminates_at_1000_ms():
    _, token = prepared(State(session_id=SESSION, bound=True), 9)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, _ = ledger.cancel(token.request_id, 0)
    ledger, effects = ledger.tick(249)
    assert effects == ()
    ledger, effects = ledger.tick(250)
    assert [effect.kind for effect in effects] == ["cancel_ack_timeout"]
    ledger, effects = ledger.tick(999)
    assert effects == ()
    ledger, effects = ledger.tick(1000)
    assert [effect.kind for effect in effects] == ["terminate_tree"]
    assert not ledger.record(token.request_id).reclaimed


def test_new_generation_waits_for_its_fence_ack_and_rejects_wrong_sink_epoch():
    state, token = prepared(State(session_id=SESSION, bound=True), 10)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, _ = ledger.terminal(token.request_id, WORKER_A, "completed", 1)
    gate = AudioGate(SESSION).fence(state.generation)
    with pytest.raises(ValueError, match="authorized"):
        gate.start_unit(state, ledger, token, "unit", 0, 4, 0)
    gate = gate.ack_fence(state.generation, 3)
    with pytest.raises(ValueError, match="authorized"):
        gate.start_unit(state, ledger, token, "unit", 0, 4, 2)
    gate = gate.start_unit(state, ledger, token, "unit", 0, 4, 3)
    sink = RecordingSink()
    gate, wrote = gate.write(state, ledger, token, "unit", 0, 2, 4, sink)
    assert not wrote and sink.calls == []
    gate, wrote = gate.write(state, ledger, token, "unit", 0, 3, 4, sink)
    assert wrote


def test_mutation_treating_cancel_ack_as_reclamation_is_caught(monkeypatch):
    _, token = prepared(State(session_id=SESSION, bound=True), 11)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, _ = ledger.cancel(token.request_id, 0)

    def assert_ack_does_not_release():
        acknowledged = ledger.cancel_ack(token.request_id, WORKER_A, 100)
        assert not acknowledged.record(token.request_id).reclaimed

    assert_ack_does_not_release()

    def wrong_ack(self, request_id, worker_instance_id, now_ms):
        item = self.record(request_id)
        return self._update(replace(item, cancel_acknowledged=True, reclaimed=True), now_ms)

    monkeypatch.setattr(WorkerLedger, "cancel_ack", wrong_ack)
    with pytest.raises(AssertionError):
        assert_ack_does_not_release()


def test_held_a_completion_after_stop_cannot_write_but_b_can():
    clock = ManualClock()
    child = HeldProcess()
    state = State(session_id=SESSION, bound=True)
    state, _ = reduce(state, ReadCurrent(UUID(int=12)), clock.now_ms)
    state, _ = reduce(state, ValidatedText(UUID(int=12), PAGE, "A"), clock.now_ms)
    a = state.synthesis
    assert a is not None
    ledger = WorkerLedger(SESSION).submit(a, WORKER_A, clock.now_ms)
    child.hold("A", {"request_id": str(a.request_id), "terminal": "completed"})
    stopped, effects = reduce(state, Stop(), clock.now_ms)
    assert [effect.kind for effect in effects] == ["fence", "cancel"]
    ledger, _ = ledger.cancel(a.request_id, clock.now_ms)
    state, _ = reduce(stopped, ReadCurrent(UUID(int=13)), clock.now_ms)
    state, _ = reduce(state, ValidatedText(UUID(int=13), PAGE, "B"), clock.now_ms)
    b = state.synthesis
    assert b is not None
    ledger = ledger.submit(b, WORKER_B, clock.now_ms)
    child.hold("B", {"request_id": str(b.request_id), "terminal": "completed"})
    assert child.release("A")["request_id"] == str(a.request_id)
    ledger, effective = ledger.terminal(a.request_id, WORKER_A, "completed", clock.advance(1))
    assert effective is None and ledger.outcome(a.request_id) == "canceled"
    state, late_effects = reduce(state, WorkerCompleted(a, "old-audio"), clock.now_ms)
    assert late_effects == ()
    assert child.release("B")["request_id"] == str(b.request_id)
    ledger, effective = ledger.terminal(b.request_id, WORKER_B, "completed", clock.advance(1))
    assert effective == "completed"
    state, b_effects = reduce(state, WorkerCompleted(b, "new-audio"), clock.now_ms)
    assert [effect.kind for effect in b_effects] == ["prepare_audio"]
    gate = AudioGate(SESSION).fence(state.generation).ack_fence(state.generation, 2)
    gate = gate.start_unit(state, ledger, b, "unit-b", 0, 2, 2)
    sink = RecordingSink()
    gate, wrote = gate.write(state, ledger, b, "unit-b", 0, 2, 2, sink)
    assert wrote and [call.request_id for call in sink.calls] == [str(b.request_id)]


def test_worker_ledger_bounds_active_records_and_ignores_evicted_late_terminal():
    _, token = prepared(State(session_id=SESSION, bound=True), 14)
    ledger = WorkerLedger(SESSION)
    for number in range(1000, 1000 + MAX_LEDGER_RECORDS):
        ledger = ledger.submit(replace(token, request_id=UUID(int=number)), UUID(int=number), 0)
    with pytest.raises(ValueError, match="full"):
        ledger.submit(replace(token, request_id=UUID(int=2000)), UUID(int=2000), 0)
    old_request = UUID(int=1000)
    ledger, effective = ledger.terminal(old_request, old_request, "completed", 1)
    assert effective == "completed"
    ledger = ledger.submit(replace(token, request_id=UUID(int=2000)), UUID(int=2000), 1)
    assert len(ledger.records) <= MAX_LEDGER_RECORDS
    ledger, effective = ledger.terminal(old_request, old_request, "completed", 2)
    assert effective is None


def test_failed_worker_cannot_be_admitted_and_cache_requires_explicit_source():
    state, token = prepared(State(session_id=SESSION, bound=True), 15)
    ledger = WorkerLedger(SESSION).submit(token, WORKER_A, 0)
    ledger, effective = ledger.terminal(token.request_id, WORKER_A, "failed", 1)
    assert effective == "failed"
    gate = acknowledged_gate(state)
    with pytest.raises(ValueError, match="authorized"):
        gate.start_unit(state, ledger, token, "unit", 0, 4, 0)
    empty_ledger = WorkerLedger(SESSION)
    with pytest.raises(ValueError, match="authorized"):
        gate.start_unit(state, empty_ledger, token, "unit", 0, 4, 0)
    gate = gate.start_unit(state, empty_ledger, token, "cached-unit", 0, 4, 0, source="cache")
    sink = RecordingSink()
    gate, wrote = gate.write(state, empty_ledger, token, "cached-unit", 0, 0, 2, sink)
    assert wrote
    stopped, _ = reduce(state, Stop(), 2)
    gate = gate.fence(stopped.generation)
    gate, wrote = gate.write(state, empty_ledger, token, "cached-unit", 0, 0, 2, sink)
    assert not wrote and len(sink.calls) == 1
