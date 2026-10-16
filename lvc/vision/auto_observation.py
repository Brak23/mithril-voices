"""Pure automatic page observation policy; callers supply a qualified detector.

This module never captures a window or makes OCR text eligible on its own.  A
detector must establish a supported panel and return a content fingerprint for
the same verified window binding and geometry epoch on every observation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SETTLE_MS = 300
CLOSE_CONFIRM_MS = 125

Effect = Literal["FENCE", "VALIDATE", "READ", "CLOSED", "SUSPENDED"]


@dataclass(frozen=True)
class Observation:
    at_ms: int
    binding: str
    geometry_epoch: int
    qualified: bool
    panel_present: bool
    content_digest: str | None


@dataclass(frozen=True)
class Decision:
    effects: tuple[Effect, ...] = ()
    validation_token: tuple[int, str] | None = None
    accepted_text: str | None = None


class AutoObservation:
    """One bound window, one interaction, one pending validation, no page queue."""

    def __init__(self) -> None:
        self.binding: str | None = None
        self.geometry_epoch: int | None = None
        self.armed = False
        self.suspended = True
        self.interaction = 0
        self._candidate: str | None = None
        self._since_ms: int | None = None
        self._absent_ms: int | None = None
        self._validated: str | None = None
        self._pending: tuple[int, str] | None = None
        self._serial = 0
        self._active: str | None = None
        self._tombstone: str | None = None
        self._unknown_hold = False
        self._needs_fresh_observation = True
        self._closed = False
        self._last_ms: int | None = None
        self._saw_panel = False

    def bind(self, binding: str, geometry_epoch: int) -> None:
        """Called only after explicit native selection and profile calibration."""
        if not binding or geometry_epoch < 0:
            raise ValueError("BINDING_INVALID")
        self.binding = binding
        self.geometry_epoch = geometry_epoch
        self.suspended = False
        self.armed = False
        self._needs_fresh_observation = True
        self._candidate = None
        self._since_ms = None
        self._pending = None
        self._validated = None
        self._active = None
        self._absent_ms = None
        self._tombstone = None
        self._unknown_hold = False
        self._closed = False
        self._last_ms = None
        self._saw_panel = False
        self.interaction += 1

    def auto_on(self) -> None:
        self.armed = True
        self._unknown_hold = False
        self._tombstone = None
        # A new explicit arm requests validation of the current panel.
        self._validated = None

    def auto_off(self) -> Decision:
        self.armed = False
        self._pending = None
        self._validated = None
        was_active = self._active is not None
        self._active = None
        return Decision(("FENCE",) if was_active else ())

    def stop(self) -> Decision:
        """Stop holds this page; an unknown page needs an explicit rearm/close."""
        self._tombstone = self._validated
        self._unknown_hold = self._validated is None
        self._pending = None
        self._active = None
        return Decision(("FENCE",))

    def suspend(self) -> Decision:
        self.suspended = True
        self._needs_fresh_observation = True
        self._pending = None
        self._active = None
        self._candidate = None
        self._validated = None
        self._last_ms = None
        return Decision(("FENCE", "SUSPENDED"))

    def observe(self, item: Observation) -> Decision:
        if item.at_ms < 0:
            raise ValueError("OBSERVATION_TIME_INVALID")
        if (self.suspended or self.binding is None
                or item.binding != self.binding
                or item.geometry_epoch != self.geometry_epoch
                or not item.qualified):
            return self.suspend()
        if self._last_ms is not None and item.at_ms < self._last_ms:
            raise ValueError("OBSERVATION_TIME_REVERSED")
        self._last_ms = item.at_ms
        if self._needs_fresh_observation:
            self._needs_fresh_observation = False
            self._candidate = None
            self._since_ms = None
        if not item.panel_present:
            if self._closed:
                return Decision()
            if not self._saw_panel:
                return Decision()
            if self._absent_ms is None:
                self._absent_ms = item.at_ms
                # Safety first: silence on the first credible absence.  A
                # second valid check confirms the interaction closure.
                self._pending = None
                self._active = None
                return Decision(("FENCE",))
            if item.at_ms - self._absent_ms >= CLOSE_CONFIRM_MS:
                self.interaction += 1
                self._candidate = None
                self._since_ms = None
                self._pending = None
                self._validated = None
                self._active = None
                self._tombstone = None
                self._unknown_hold = False
                self._absent_ms = None
                self._closed = True
                return Decision(("CLOSED",))
            return Decision()
        if self._closed:
            self._closed = False
            self._candidate = None
            self._since_ms = None
        self._saw_panel = True
        if self._absent_ms is not None:
            # One absent check is not a confirmed close.  Require a new settle.
            self._absent_ms = None
            self._candidate = None
        digest = item.content_digest
        if not digest or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return self.suspend()
        if digest != self._candidate:
            changed = self._candidate is not None or self._active is not None
            self._candidate = digest
            self._since_ms = item.at_ms
            self._pending = None
            self._active = None
            self._validated = None
            return Decision(("FENCE",) if changed else ())
        if not self.armed or self._unknown_hold or self._pending is not None:
            return Decision()
        if self._validated == digest or self._since_ms is None:
            return Decision()
        if item.at_ms - self._since_ms < SETTLE_MS:
            return Decision()
        self._serial += 1
        token = (self._serial, digest)
        self._pending = token
        return Decision(("VALIDATE",), validation_token=token)

    def validated(self, token: tuple[int, str], text: str | None) -> Decision:
        """Only a current, independently qualified OCR result may reach READ."""
        if not self.can_accept_validation(token):
            return Decision()
        self._pending = None
        self._validated = token[1]
        if not text or not text.strip() or self._tombstone == token[1]:
            return Decision()
        self._active = token[1]
        return Decision(("READ",), accepted_text=text)

    def can_accept_validation(self, token: tuple[int, str]) -> bool:
        return (not self.suspended and self.armed and token == self._pending
                and token[1] == self._candidate and not self._unknown_hold)
