"""Pure, bounded v2 control slice for Stop and page replacement.

Effects are instructions to a future host, not proof that a renderer fenced or
played audio. In particular, prepare_audio is never permission to write bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, TypeAlias
from uuid import UUID

Origin: TypeAlias = Literal["auto", "manual"]
Observation: TypeAlias = Literal["WATCHING", "STABILIZING", "READY"]
Playback: TypeAlias = Literal["IDLE", "PREPARING", "PLAYING", "COMPLETED", "STOPPED", "FAILED"]


@dataclass(frozen=True)
class PageIdentity:
    interaction_id: UUID
    revision: int
    surface: str
    content_digest: str

    def __post_init__(self) -> None:
        if self.revision < 1 or not self.surface or not self.content_digest:
            raise ValueError("Page identity requires qualified interaction and content")


@dataclass(frozen=True)
class RequestToken:
    request_id: UUID
    session_id: UUID
    generation: int
    intent: int
    origin: Origin
    page: PageIdentity | None


@dataclass(frozen=True)
class Effect:
    kind: Literal["fence", "cancel", "capture", "synthesize", "prepare_audio", "capture_unavailable"]
    generation: int
    request_id: UUID | None = None
    token: RequestToken | None = None
    artifact: str | None = None


@dataclass(frozen=True)
class State:
    session_id: UUID
    bound: bool = False
    intent: int = 0
    generation: int = 0
    auto_enabled: bool = False
    auto_held_unknown: bool = False
    page: PageIdentity | None = None
    tombstone: PageIdentity | None = None
    pending: RequestToken | None = None
    synthesis: RequestToken | None = None
    prepared: str | None = None
    prepared_token: RequestToken | None = None
    auto_read_pages: frozenset[PageIdentity] = frozenset()
    observation: Observation = "WATCHING"
    playback: Playback = "IDLE"
    failure_code: str | None = None
    stale_results: int = 0


@dataclass(frozen=True)
class AutoEnable:
    request_id: UUID


@dataclass(frozen=True)
class AutoDisable:
    pass


@dataclass(frozen=True)
class Stop:
    pass


@dataclass(frozen=True)
class ReadCurrent:
    request_id: UUID


@dataclass(frozen=True)
class ConfirmedPage:
    page: PageIdentity
    request_id: UUID


@dataclass(frozen=True)
class PageChangePending:
    """Credible content change: fence now, retain old identity until confirmation."""


@dataclass(frozen=True)
class PanelClosed:
    """Two valid absent-panel checks confirmed an interaction closure."""


@dataclass(frozen=True)
class ValidatedText:
    request_id: UUID
    page: PageIdentity
    accepted_text: str


@dataclass(frozen=True)
class WorkerCompleted:
    token: RequestToken
    artifact: str


@dataclass(frozen=True)
class WorkerFailed:
    token: RequestToken
    code: str


@dataclass(frozen=True)
class RendererStarted:
    token: RequestToken
    artifact: str


@dataclass(frozen=True)
class RendererDrained:
    token: RequestToken
    artifact: str


Event: TypeAlias = (AutoEnable | AutoDisable | Stop | ReadCurrent | ConfirmedPage |
                    PageChangePending | PanelClosed | ValidatedText | WorkerCompleted |
                    WorkerFailed | RendererStarted | RendererDrained)


def _cancel_effects(state: State) -> tuple[Effect, ...]:
    return tuple(
        Effect("cancel", state.generation, token.request_id, token)
        for token in (state.pending, state.synthesis) if token is not None
    )


def _fence(state: State, *, page: PageIdentity | None = None) -> tuple[State, tuple[Effect, ...]]:
    next_generation = state.generation + 1
    effects = (Effect("fence", next_generation), *_cancel_effects(state))
    return replace(state, generation=next_generation, intent=state.intent + 1,
                   pending=None, synthesis=None, prepared=None, prepared_token=None, page=page,
                   playback="STOPPED", failure_code=None), effects


def _capture(state: State, request_id: UUID, origin: Origin) -> tuple[State, tuple[Effect, ...]]:
    token = RequestToken(request_id, state.session_id, state.generation, state.intent, origin, state.page)
    return replace(state, pending=token, observation="STABILIZING", playback="PREPARING"), (
        Effect("capture", state.generation, request_id, token),
    )


def reduce(state: State, event: Event, now_ms: int) -> tuple[State, tuple[Effect, ...]]:
    """Return new state and ordered effects without I/O, timers, Qt, or worker calls.

    This deliberately handles only the event subset typed above. Other v2
    behavior-matrix events require later packets and must not be routed here.
    """
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
        raise ValueError("Expected nonnegative monotonic milliseconds")

    if isinstance(event, Stop):
        next_state, effects = _fence(state, page=state.page)
        return replace(next_state, tombstone=state.page,
                       auto_held_unknown=state.page is None,
                       observation="WATCHING"), effects

    if isinstance(event, PageChangePending):
        if (state.pending is None and state.synthesis is None
                and state.prepared_token is None and state.playback == "STOPPED"):
            return state, ()
        next_state, effects = _fence(state, page=state.page)
        return replace(next_state, observation="STABILIZING"), effects

    if isinstance(event, PanelClosed):
        if (state.page is None and state.pending is None and state.synthesis is None
                and state.prepared_token is None and not state.auto_held_unknown):
            return state, ()
        next_state, effects = _fence(state)
        return replace(next_state, auto_held_unknown=False, tombstone=None,
                       auto_read_pages=frozenset(), observation="WATCHING"), effects

    if isinstance(event, ReadCurrent):
        if not state.bound:
            return state, (Effect("capture_unavailable", state.generation),)
        next_state, effects = _fence(state, page=state.page)
        next_state = replace(next_state, auto_held_unknown=False)
        next_state, capture = _capture(next_state, event.request_id, "manual")
        return next_state, effects + capture

    if isinstance(event, AutoDisable):
        if not state.auto_enabled:
            return state, ()
        active = state.pending or state.synthesis or state.prepared_token
        if active is not None and active.origin == "auto":
            next_state, effects = _fence(state, page=state.page)
            return replace(next_state, auto_enabled=False, observation="WATCHING"), effects
        return replace(state, auto_enabled=False), ()

    if isinstance(event, AutoEnable):
        if state.auto_enabled:
            return state, ()
        next_state = replace(state, auto_enabled=True, auto_held_unknown=False)
        active = state.pending or state.synthesis or state.prepared_token
        if not state.bound or (active is not None and active.origin == "manual"):
            return next_state, ()
        return _capture(next_state, event.request_id, "auto")

    if isinstance(event, ConfirmedPage):
        if event.page == state.page:
            return state, ()
        next_state, effects = _fence(state, page=event.page)
        next_state = replace(next_state, tombstone=None, observation="STABILIZING")
        if not next_state.auto_enabled or next_state.auto_held_unknown:
            return next_state, effects
        next_state, capture = _capture(next_state, event.request_id, "auto")
        return next_state, effects + capture

    if isinstance(event, ValidatedText):
        token = state.pending
        if (token is None or token.request_id != event.request_id
                or token.session_id != state.session_id
                or token.generation != state.generation or token.intent != state.intent
                or (token.page is not None and token.page != event.page)
                or (state.page is not None and state.page != event.page)):
            return replace(state, stale_results=state.stale_results + 1), ()
        next_state = replace(state, pending=None, page=event.page, observation="READY")
        authorized = (token.origin == "manual" or (
            next_state.auto_enabled and not next_state.auto_held_unknown
            and next_state.tombstone != event.page
            and event.page not in next_state.auto_read_pages
        ))
        if not authorized or not event.accepted_text.strip():
            return replace(next_state, playback="STOPPED"), ()
        synth_token = replace(token, page=event.page)
        pages = next_state.auto_read_pages
        if token.origin == "auto":
            pages = pages | {event.page}
        return replace(next_state, synthesis=synth_token, auto_read_pages=pages,
                       playback="PREPARING"), (
            Effect("synthesize", state.generation, token.request_id, synth_token),
        )

    if isinstance(event, WorkerCompleted):
        token = event.token
        if (state.synthesis != token or token.session_id != state.session_id
                or token.generation != state.generation or token.intent != state.intent
                or token.page != state.page):
            return replace(state, stale_results=state.stale_results + 1), ()
        return replace(state, synthesis=None, prepared=event.artifact, prepared_token=token), (
            Effect("prepare_audio", state.generation, token.request_id, token, event.artifact),
        )

    if isinstance(event, WorkerFailed):
        token = event.token
        if state.synthesis != token or not event.code:
            return replace(state, stale_results=state.stale_results + 1), ()
        next_state, effects = _fence(state, page=state.page)
        return replace(next_state, playback="FAILED", failure_code=event.code), effects

    if isinstance(event, RendererStarted):
        if (state.prepared_token != event.token or state.prepared != event.artifact
                or state.playback != "PREPARING"):
            return replace(state, stale_results=state.stale_results + 1), ()
        return replace(state, playback="PLAYING"), ()

    if isinstance(event, RendererDrained):
        if (state.prepared_token != event.token or state.prepared != event.artifact
                or state.playback != "PLAYING"):
            return replace(state, stale_results=state.stale_results + 1), ()
        return replace(state, playback="COMPLETED", prepared=None, prepared_token=None), ()

    raise TypeError(f"Unsupported v2 core event: {type(event).__name__}")
