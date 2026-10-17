"""Pure bridge from qualified page observations to the existing core reducer.

There is deliberately no LOTRO activation site yet. A caller must supply a
reviewed detector qualification and perform effects through supervised workers
and the generation-fenced renderer. The calibration UI never uses this bridge.
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from uuid import UUID, uuid4, uuid5

from lvc.core import (
    AutoDisable,
    AutoEnable,
    ConfirmedPage,
    Effect,
    PageChangePending,
    PageIdentity,
    PanelClosed,
    State,
    Stop,
    ValidatedText,
    reduce,
)
from lvc.vision.auto_observation import AutoObservation, Observation


@dataclass(frozen=True)
class ValidationRequest:
    observation_token: tuple[int, str]
    request_id: UUID
    page: PageIdentity


@dataclass(frozen=True)
class BridgeOutcome:
    effects: tuple[Effect, ...] = ()
    validation: ValidationRequest | None = None
    synthesis_text: str | None = None
    reason: str = ""


class AutoCoreAdapter:
    """One binding with at most one live OCR request and one active reading."""

    def __init__(self, session_id: UUID, binding: str, geometry_epoch: int,
                 *, profile_qualified: bool = False) -> None:
        if session_id.int == 0 or not binding or geometry_epoch < 0:
            raise ValueError("AUTO_BINDING_INVALID")
        self.state = State(session_id, bound=True)
        self.observation = AutoObservation()
        self.observation.bind(binding, geometry_epoch)
        self.profile_qualified = profile_qualified
        self._last_digest: str | None = None
        self._last_interaction = self.observation.interaction
        self._revision = 0
        self._pending: ValidationRequest | None = None
        self._last_spoken_hash: str | None = None

    def enable(self, now_ms: int) -> BridgeOutcome:
        if not self.profile_qualified:
            return BridgeOutcome(reason="DETECTOR_PROFILE_UNQUALIFIED")
        if self.state.auto_enabled:
            return BridgeOutcome(reason="ALREADY_ENABLED")
        self.observation.auto_on()
        self.state, effects = reduce(self.state, AutoEnable(uuid4()), now_ms)
        # The reducer's capture reservation is fulfilled only by a later fresh,
        # stable selected-window observation. It is not a trigger to capture now.
        return BridgeOutcome(tuple(effect for effect in effects
                                   if effect.kind != "capture"), reason="WATCHING")

    def disable(self, now_ms: int) -> BridgeOutcome:
        self.observation.auto_off()
        self._pending = None
        self.state, effects = reduce(self.state, AutoDisable(), now_ms)
        return BridgeOutcome(effects, reason="AUTO_OFF")

    def stop(self, now_ms: int) -> BridgeOutcome:
        self.observation.stop()
        self._pending = None
        self.state, effects = reduce(self.state, Stop(), now_ms)
        return BridgeOutcome(effects, reason="STOPPED")

    def observe(self, item: Observation) -> BridgeOutcome:
        decision = self.observation.observe(item)
        effects: tuple[Effect, ...] = ()
        if "FENCE" in decision.effects or "SUSPENDED" in decision.effects:
            self._pending = None
            self.state, effects = reduce(self.state, PageChangePending(), item.at_ms)
        if "CLOSED" in decision.effects:
            self._pending = None
            self.state, close_effects = reduce(self.state, PanelClosed(), item.at_ms)
            effects += close_effects
            self._last_digest = None
            self._last_interaction = self.observation.interaction
            self._revision = 0
            self._last_spoken_hash = None
            return BridgeOutcome(effects, reason="CLOSED")
        if "SUSPENDED" in decision.effects:
            return BridgeOutcome(effects, reason="SUSPENDED")
        token = decision.validation_token
        if token is None or not self.state.auto_enabled:
            return BridgeOutcome(effects, reason="WATCHING")
        digest = token[1]
        if self._last_interaction != self.observation.interaction:
            self._last_interaction = self.observation.interaction
            self._last_digest = None
            self._last_spoken_hash = None
            self._revision = 0
        if digest != self._last_digest:
            self._revision += 1
            self._last_digest = digest
        elif self._revision == 0:
            self._revision = 1
        page = PageIdentity(uuid5(self.state.session_id, str(self._last_interaction)),
                            self._revision, "quest_body", digest)
        if self.state.page != page:
            request_id = uuid4()
            self.state, page_effects = reduce(self.state,
                                              ConfirmedPage(page, request_id), item.at_ms)
            effects += tuple(effect for effect in page_effects if effect.kind != "capture")
        else:
            pending = self.state.pending
            if pending is None:
                return BridgeOutcome(effects, reason="NO_CORE_CAPTURE_RESERVATION")
            request_id = pending.request_id
        request = ValidationRequest(token, request_id, page)
        self._pending = request
        return BridgeOutcome(effects, request, reason="VALIDATE")

    def validated(self, token: tuple[int, str], accepted_text: str | None,
                  now_ms: int) -> BridgeOutcome:
        request = self._pending
        if (request is None or request.observation_token != token
                or not self.observation.can_accept_validation(token)):
            return BridgeOutcome(reason="STALE_OCR")
        self._pending = None
        normalized = unicodedata.normalize(
            "NFC", " ".join((accepted_text or "").split())).casefold()
        text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None
        duplicate = text_hash is not None and text_hash == self._last_spoken_hash
        decision = self.observation.validated(token, None if duplicate else accepted_text)
        text = decision.accepted_text or ""
        self.state, effects = reduce(self.state, ValidatedText(
            request.request_id, request.page, text), now_ms)
        if not text:
            return BridgeOutcome(effects, reason=(
                "DUPLICATE_TEXT" if duplicate else "OCR_ABSTAINED_OR_HELD"))
        if not any(effect.kind == "synthesize" for effect in effects):
            return BridgeOutcome(effects, reason="CORE_REJECTED_TEXT")
        self._last_spoken_hash = text_hash
        return BridgeOutcome(effects, synthesis_text=text, reason="SYNTHESIS_ELIGIBLE")
