"""Automatic observation events must fence core audio before late work arrives."""
from __future__ import annotations

from uuid import UUID

from lvc.core import (
    AutoEnable,
    ConfirmedPage,
    PageChangePending,
    PageIdentity,
    PanelClosed,
    RendererStarted,
    RequestToken,
    State,
    Stop,
    ValidatedText,
    WorkerCompleted,
    reduce,
)
from lvc.vision.auto_observation import AutoObservation, Observation

SESSION = UUID("00000000-0000-4000-8000-000000000100")
INTERACTION_A = UUID("00000000-0000-4000-8000-000000000101")
INTERACTION_B = UUID("00000000-0000-4000-8000-000000000102")
REQ_A = UUID("00000000-0000-4000-8000-000000000103")
REQ_B = UUID("00000000-0000-4000-8000-000000000104")
A = PageIdentity(INTERACTION_A, 1, "quest_body", "page-a")
B = PageIdentity(INTERACTION_A, 2, "quest_body", "page-b")
REOPENED = PageIdentity(INTERACTION_B, 1, "quest_body", "page-a")


def playing_auto() -> tuple[State, RequestToken]:
    state, _ = reduce(State(SESSION, bound=True), AutoEnable(REQ_A), 0)
    state, _ = reduce(state, ValidatedText(REQ_A, A, "First page."), 1)
    token = state.synthesis
    assert token is not None and token.origin == "auto"
    state, _ = reduce(state, WorkerCompleted(token, "first.wav"), 2)
    state, _ = reduce(state, RendererStarted(token, "first.wav"), 3)
    assert state.playback == "PLAYING"
    return state, token


def test_change_fences_before_confirmation_and_new_page_can_read() -> None:
    state, old = playing_auto()
    state, effects = reduce(state, PageChangePending(), 4)
    assert effects[0].kind == "fence" and effects[0].generation > old.generation
    assert state.page == A and state.auto_enabled and state.prepared_token is None
    state, effects = reduce(state, ConfirmedPage(B, REQ_B), 305)
    assert any(effect.kind == "capture" for effect in effects)
    state, effects = reduce(state, ValidatedText(REQ_B, B, "Second page."), 306)
    assert state.synthesis is not None and state.synthesis.page == B
    assert any(effect.kind == "synthesize" for effect in effects)
    state, effects = reduce(state, WorkerCompleted(old, "stale.wav"), 307)
    assert effects == () and state.prepared is None


def test_unconfirmed_visual_change_cannot_replay_stopped_page() -> None:
    state, _ = playing_auto()
    state, _ = reduce(state, Stop(), 4)
    assert state.tombstone == A
    state, effects = reduce(state, PageChangePending(), 5)
    assert effects == ()
    state, effects = reduce(state, ConfirmedPage(A, REQ_B), 305)
    assert effects == () and state.pending is None


def test_confirmed_close_stops_live_page_and_reopen_is_new_interaction() -> None:
    state, _ = playing_auto()
    state, effects = reduce(state, PanelClosed(), 130)
    assert effects[0].kind == "fence"
    assert state.page is None and not state.auto_read_pages
    assert state.auto_enabled and state.playback == "STOPPED"
    state, effects = reduce(state, ConfirmedPage(REOPENED, REQ_B), 500)
    assert any(effect.kind == "capture" for effect in effects)
    state, effects = reduce(state, ValidatedText(REQ_B, REOPENED, "First page."), 501)
    assert any(effect.kind == "synthesize" for effect in effects)


def test_close_clears_unknown_stop_hold_only_after_confirmation() -> None:
    state, _ = reduce(State(SESSION, bound=True), AutoEnable(REQ_A), 0)
    state, _ = reduce(state, Stop(), 1)
    assert state.auto_held_unknown
    state, _ = reduce(state, PanelClosed(), 126)
    assert not state.auto_held_unknown
    state, effects = reduce(state, ConfirmedPage(REOPENED, REQ_B), 500)
    assert any(effect.kind == "capture" for effect in effects)


def test_synthetic_observation_to_core_change_fences_old_unit() -> None:
    policy = AutoObservation()
    policy.bind("selected", 1)
    policy.auto_on()
    state, _ = reduce(State(SESSION, bound=True), AutoEnable(REQ_A), 0)

    def observation(ms: int, digest: str) -> Observation:
        return Observation(ms, "selected", 1, True, True, digest)

    first_digest, second_digest = "a" * 64, "b" * 64
    policy.observe(observation(0, first_digest))
    first = policy.observe(observation(300, first_digest))
    assert first.validation_token is not None
    text = policy.validated(first.validation_token, "First page.")
    assert text.effects == ("READ",)
    state, _ = reduce(state, ValidatedText(REQ_A, A, text.accepted_text or ""), 301)
    old = state.synthesis
    assert old is not None
    changed = policy.observe(observation(400, second_digest))
    assert changed.effects == ("FENCE",)
    state, effects = reduce(state, PageChangePending(), 400)
    assert effects[0].kind == "fence"
    second = policy.observe(observation(700, second_digest))
    assert second.validation_token is not None
    state, _ = reduce(state, ConfirmedPage(B, REQ_B), 700)
    assert policy.validated(first.validation_token, "Late old text.").effects == ()
    text = policy.validated(second.validation_token, "Second page.")
    state, effects = reduce(state, ValidatedText(REQ_B, B, text.accepted_text or ""), 701)
    assert any(effect.kind == "synthesize" for effect in effects)
    state, effects = reduce(state, WorkerCompleted(old, "late.wav"), 702)
    assert effects == () and state.prepared is None
