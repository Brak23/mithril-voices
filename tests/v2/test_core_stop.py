"""Synthetic reducer slice; renderer and real audio acceptance remain separate."""
from uuid import UUID

from lvc.core import (
    AutoDisable,
    AutoEnable,
    ConfirmedPage,
    PageIdentity,
    ReadCurrent,
    State,
    Stop,
    ValidatedText,
    WorkerCompleted,
    reduce,
)
from tests.v2.support import ManualClock

SESSION = UUID(int=1)
A = PageIdentity(UUID(int=2), 1, "quest", "digest-a")
B = PageIdentity(UUID(int=2), 2, "quest", "digest-b")


def step(state, event, clock):
    return reduce(state, event, clock.now_ms)


def kinds(effects):
    return [effect.kind for effect in effects]


def test_stop_cancels_a_and_late_worker_cannot_prepare_it_after_b():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, AutoEnable(UUID(int=10)), clock)
    state, _ = step(state, ConfirmedPage(A, UUID(int=11)), clock)
    state, effects = step(state, ValidatedText(UUID(int=11), A, "A text"), clock)
    assert kinds(effects) == ["synthesize"]
    a_token = state.synthesis
    assert a_token is not None
    state, effects = step(state, Stop(), clock)
    assert kinds(effects)[:2] == ["fence", "cancel"]
    assert state.tombstone == A and state.synthesis is None
    state, effects = step(state, ConfirmedPage(B, UUID(int=12)), clock)
    assert "capture" in kinds(effects)
    state, effects = step(state, ValidatedText(UUID(int=12), B, "B text"), clock)
    assert kinds(effects) == ["synthesize"]
    b_token = state.synthesis
    assert b_token is not None and b_token.generation > a_token.generation
    state, effects = step(state, WorkerCompleted(a_token, "audio-a"), clock)
    assert effects == ()
    assert state.stale_results == 1 and state.synthesis == b_token
    state, effects = step(state, WorkerCompleted(b_token, "audio-b"), clock)
    assert kinds(effects) == ["prepare_audio"]
    assert effects[0].request_id == b_token.request_id


def test_unknown_stop_survives_late_ocr_and_time_until_off_on_rearm():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, AutoEnable(UUID(int=20)), clock)
    state, effects = step(state, Stop(), clock)
    assert state.auto_held_unknown and kinds(effects)[0] == "fence"
    state, effects = step(state, ValidatedText(UUID(int=20), A, "late"), clock)
    assert effects == () and state.auto_held_unknown
    clock.advance(60_000)
    state, effects = step(state, ConfirmedPage(A, UUID(int=21)), clock)
    assert state.auto_held_unknown and "synthesize" not in kinds(effects)
    state, effects = step(state, ValidatedText(UUID(int=21), A, "fresh"), clock)
    assert effects == () and state.auto_held_unknown
    state, _ = step(state, AutoDisable(), clock)
    state, effects = step(state, AutoEnable(UUID(int=22)), clock)
    assert not state.auto_held_unknown and "capture" in kinds(effects)
    state, effects = step(state, ValidatedText(UUID(int=22), A, "fresh"), clock)
    assert kinds(effects) == ["synthesize"]


def test_known_page_tombstone_persists_and_manual_read_rearms():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, AutoEnable(UUID(int=30)), clock)
    state, _ = step(state, ValidatedText(UUID(int=30), A, "A text"), clock)
    state, _ = step(state, Stop(), clock)
    clock.advance(3_600_000)
    state, effects = step(state, ConfirmedPage(A, UUID(int=31)), clock)
    assert effects == () and state.tombstone == A
    state, effects = step(state, ReadCurrent(UUID(int=32)), clock)
    assert kinds(effects) == ["fence", "capture"]
    state, effects = step(state, ValidatedText(UUID(int=32), A, "A text"), clock)
    assert kinds(effects) == ["synthesize"]


def test_same_npc_different_page_fences_before_capture_and_duplicates_do_nothing():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, AutoEnable(UUID(int=40)), clock)
    state, _ = step(state, ValidatedText(UUID(int=40), A, "A text"), clock)
    state, effects = step(state, ConfirmedPage(B, UUID(int=41)), clock)
    assert kinds(effects) == ["fence", "cancel", "capture"]
    assert state.page == B and state.synthesis is None
    state, effects = step(state, ConfirmedPage(B, UUID(int=42)), clock)
    assert effects == ()
    state, effects = step(state, ValidatedText(UUID(int=41), B, "B text"), clock)
    assert kinds(effects) == ["synthesize"]


def test_auto_disable_does_not_stop_manual_read():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, AutoEnable(UUID(int=50)), clock)
    state, _ = step(state, ReadCurrent(UUID(int=51)), clock)
    generation = state.generation
    state, effects = step(state, AutoDisable(), clock)
    assert effects == () and state.generation == generation
    assert state.pending is not None and state.pending.origin == "manual"


def test_auto_disable_fences_prepared_auto_audio_and_preserves_prepared_manual_audio():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, AutoEnable(UUID(int=60)), clock)
    state, _ = step(state, ValidatedText(UUID(int=60), A, "A text"), clock)
    token = state.synthesis
    assert token is not None
    state, _ = step(state, WorkerCompleted(token, "audio-a"), clock)
    state, effects = step(state, AutoDisable(), clock)
    assert kinds(effects) == ["fence"] and state.prepared is None
    state, _ = step(state, ReadCurrent(UUID(int=61)), clock)
    state, _ = step(state, ValidatedText(UUID(int=61), A, "manual"), clock)
    token = state.synthesis
    assert token is not None
    state, _ = step(state, WorkerCompleted(token, "audio-manual"), clock)
    state, _ = step(state, AutoEnable(UUID(int=62)), clock)
    state, effects = step(state, AutoDisable(), clock)
    assert effects == () and state.prepared == "audio-manual"


def test_repeated_manual_read_replaces_pending_and_duplicate_worker_is_stale():
    clock = ManualClock()
    state = State(session_id=SESSION, bound=True)
    state, _ = step(state, ReadCurrent(UUID(int=70)), clock)
    state, effects = step(state, ReadCurrent(UUID(int=71)), clock)
    assert kinds(effects) == ["fence", "cancel", "capture"]
    state, effects = step(state, ValidatedText(UUID(int=70), A, "old"), clock)
    assert effects == ()
    state, _ = step(state, ValidatedText(UUID(int=71), A, "new"), clock)
    token = state.synthesis
    assert token is not None
    state, _ = step(state, WorkerCompleted(token, "new-audio"), clock)
    state, effects = step(state, WorkerCompleted(token, "duplicate"), clock)
    assert effects == () and state.prepared == "new-audio"
