"""Qualified synthetic observations flowing through the actual reducer."""
from __future__ import annotations

from uuid import uuid4

from lvc.vision.auto_core_adapter import AutoCoreAdapter, BridgeOutcome
from lvc.vision.auto_observation import Observation

A = "a" * 64
B = "b" * 64
C = "c" * 64


def frame(ms: int, digest: str | None = A, *, present: bool = True,
          geometry: int = 1, qualified: bool = True) -> Observation:
    return Observation(ms, "selected", geometry, qualified, present, digest)


def ready() -> AutoCoreAdapter:
    bridge = AutoCoreAdapter(uuid4(), "selected", 1, profile_qualified=True)
    assert bridge.enable(0).reason == "WATCHING"
    return bridge


def kind(outcome: BridgeOutcome) -> list[str]:
    return [effect.kind for effect in outcome.effects]


def stable(bridge: AutoCoreAdapter, digest: str, start: int) -> BridgeOutcome:
    assert bridge.observe(frame(start, digest)).validation is None
    assert bridge.observe(frame(start + 299, digest)).validation is None
    return bridge.observe(frame(start + 300, digest))


def test_qualification_gate_and_stable_ocr_to_synthesis() -> None:
    unqualified = AutoCoreAdapter(uuid4(), "selected", 1)
    assert unqualified.enable(0).reason == "DETECTOR_PROFILE_UNQUALIFIED"
    assert not unqualified.state.auto_enabled
    assert unqualified.observe(frame(0)).validation is None

    bridge = ready()
    pending = stable(bridge, A, 0)
    assert pending.reason == "VALIDATE"
    assert pending.validation is not None
    assert bridge.state.page == pending.validation.page
    assert bridge.state.pending is not None
    assert "capture" not in kind(pending)
    outcome = bridge.validated(pending.validation.observation_token, "Synthetic quest body.", 301)
    assert kind(outcome) == ["synthesize"]
    assert outcome.synthesis_text == "Synthetic quest body."
    assert bridge.observe(frame(500)).validation is None


def test_change_fences_before_new_ocr_and_rejects_late_result() -> None:
    bridge = ready()
    first = stable(bridge, A, 0)
    assert first.validation is not None
    changed = bridge.observe(frame(301, B))
    assert "fence" in kind(changed)
    assert "cancel" in kind(changed)
    assert bridge.validated(first.validation.observation_token, "Stale page.", 302).effects == ()
    assert bridge.observe(frame(600, B)).validation is None
    second = bridge.observe(frame(601, B))
    assert second.validation is not None
    assert second.validation.page.revision == first.validation.page.revision + 1
    assert bridge.validated(second.validation.observation_token, "New page.", 602).synthesis_text == "New page."


def test_stop_during_ocr_and_off_block_late_read() -> None:
    bridge = ready()
    first = stable(bridge, A, 0)
    assert first.validation is not None
    assert "fence" in kind(bridge.stop(301))
    assert bridge.validated(first.validation.observation_token, "Late page.", 302).effects == ()
    assert bridge.observe(frame(700)).validation is None
    bridge.disable(701)
    assert not bridge.state.auto_enabled
    assert bridge.observe(frame(1100, B)).validation is None


def test_confirmed_close_reopens_same_digest_as_new_interaction() -> None:
    bridge = ready()
    first = stable(bridge, A, 0)
    assert first.validation is not None
    assert kind(bridge.validated(first.validation.observation_token, "First.", 301)) == ["synthesize"]
    assert "fence" in kind(bridge.observe(frame(500, None, present=False)))
    assert bridge.observe(frame(624, None, present=False)).reason == "WATCHING"
    assert bridge.observe(frame(625, None, present=False)).reason == "CLOSED"
    assert bridge.state.page is None
    second = stable(bridge, A, 900)
    assert second.validation is not None
    assert second.validation.page.interaction_id != first.validation.page.interaction_id
    assert bridge.validated(second.validation.observation_token, "First.", 1201).synthesis_text == "First."


def test_unqualified_observation_suspends_and_fences_active_synthesis() -> None:
    bridge = ready()
    first = stable(bridge, A, 0)
    assert first.validation is not None
    bridge.validated(first.validation.observation_token, "Synthetic text.", 301)
    suspended = bridge.observe(frame(302, geometry=2))
    assert suspended.reason == "SUSPENDED"
    assert "fence" in kind(suspended)
    assert "cancel" in kind(suspended)
    assert bridge.observe(frame(700)).validation is None
    assert bridge.validated(first.validation.observation_token, "Late text.", 701).effects == ()


def test_same_ocr_words_with_new_pixels_are_not_read_twice() -> None:
    bridge = ready()
    first = stable(bridge, A, 0)
    assert first.validation is not None
    assert bridge.validated(first.validation.observation_token,
                            "The road is clear.", 301).synthesis_text == "The road is clear."
    second = stable(bridge, B, 500)
    assert second.validation is not None
    repeated = bridge.validated(second.validation.observation_token,
                                "  THE   road is clear.  ", 801)
    assert repeated.synthesis_text is None
    assert "synthesize" not in kind(repeated)
    third = stable(bridge, C, 1000)
    assert third.validation is not None
    assert bridge.validated(third.validation.observation_token,
                            "The gate is open.", 1301).synthesis_text == "The gate is open."
