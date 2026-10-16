"""Desired automatic behavior on synthetic qualified observations only."""
from __future__ import annotations

import hashlib

from PIL import Image, ImageDraw, ImageFont

from lvc.platform.windows.lotro_user_probe import recognize
from lvc.vision.auto_observation import AutoObservation, Observation
from lvc.vision.text_gate import decide_text

A = "a" * 64
B = "b" * 64


def frame(ms: int, digest: str | None = A, *, present: bool = True,
          binding: str = "selected", geometry: int = 1,
          qualified: bool = True) -> Observation:
    return Observation(ms, binding, geometry, qualified, present, digest)


def ready() -> AutoObservation:
    policy = AutoObservation()
    policy.bind("selected", 1)
    policy.auto_on()
    return policy


def validate_page(policy: AutoObservation, digest: str = A, start: int = 0) -> str:
    policy.observe(frame(start, digest))
    assert policy.observe(frame(start + 299, digest)).effects == ()
    decision = policy.observe(frame(start + 300, digest))
    assert decision.effects == ("VALIDATE",)
    assert decision.validation_token is not None
    assert policy.validated(decision.validation_token, "Bring 10 Ore. Do not trade 1.").effects == ("READ",)
    return decision.validation_token[1]


def test_settle_duplicate_and_same_npc_change() -> None:
    policy = ready()
    validate_page(policy)
    assert policy.observe(frame(500)).effects == ()
    assert policy.observe(frame(625)).effects == ()
    assert policy.observe(frame(700, B)).effects == ("FENCE",)
    pending = policy.observe(frame(1000, B))
    assert pending.effects == ("VALIDATE",)
    assert pending.validation_token is not None
    assert policy.validated(pending.validation_token, "A different page.").effects == ("READ",)


def test_stale_ocr_after_change_and_stop_before_ocr() -> None:
    policy = ready()
    policy.observe(frame(0))
    pending = policy.observe(frame(300))
    assert pending.validation_token is not None
    policy.stop()
    assert policy.validated(pending.validation_token, "Late text.").effects == ()
    assert policy.observe(frame(600)).effects == ()  # Unknown-page hold persists.
    policy.auto_off()
    policy.auto_on()
    second = policy.observe(frame(700))
    assert second.effects == ("VALIDATE",)
    assert policy.validated(pending.validation_token, "Old text.").effects == ()
    assert second.validation_token is not None
    assert policy.validated(second.validation_token, "Current text.").effects == ("READ",)


def test_stop_tombstone_and_new_page() -> None:
    policy = ready()
    validate_page(policy)
    assert policy.stop().effects == ("FENCE",)
    assert policy.observe(frame(700)).effects == ()
    assert policy.observe(frame(800, B)).effects == ("FENCE",)
    pending = policy.observe(frame(1100, B))
    assert pending.validation_token is not None
    assert policy.validated(pending.validation_token, "New page.").effects == ("READ",)


def test_close_needs_two_valid_checks_and_reopen_is_new_interaction() -> None:
    policy = ready()
    validate_page(policy)
    before = policy.interaction
    assert policy.observe(frame(500, None, present=False)).effects == ("FENCE",)
    assert policy.observe(frame(624, None, present=False)).effects == ()
    assert policy.observe(frame(625, None, present=False)).effects == ("CLOSED",)
    assert policy.observe(frame(800, None, present=False)).effects == ()
    assert policy.interaction == before + 1
    policy.observe(frame(900))
    next_page = policy.observe(frame(1200))
    assert next_page.validation_token is not None
    assert policy.validated(next_page.validation_token, "Same words, new interaction.").effects == ("READ",)


def test_idle_empty_screen_is_not_a_sequence_of_new_interactions() -> None:
    policy = ready()
    before = policy.interaction
    for at_ms in (0, 125, 500, 1000):
        assert policy.observe(frame(at_ms, None, present=False)).effects == ()
    assert policy.interaction == before


def test_geometry_and_unqualified_detector_suspend_without_read() -> None:
    policy = ready()
    policy.observe(frame(0))
    pending = policy.observe(frame(300))
    assert pending.validation_token is not None
    assert policy.observe(frame(301, geometry=2)).effects == ("FENCE", "SUSPENDED")
    assert policy.validated(pending.validation_token, "Stale geometry.").effects == ()
    policy.bind("selected", 2)
    assert not policy.armed
    policy.auto_on()
    assert policy.observe(frame(400, geometry=2, qualified=False)).effects == (
        "FENCE", "SUSPENDED")


def test_auto_off_fences_and_does_not_rearm_on_bind() -> None:
    policy = ready()
    validate_page(policy)
    assert policy.auto_off().effects == ("FENCE",)
    assert policy.observe(frame(500)).effects == ()
    policy.bind("selected", 2)
    assert policy.observe(frame(800, geometry=2)).effects == ()
    assert policy.observe(frame(1100, geometry=2)).effects == ()


def test_synthetic_quest_ocr_requires_qualified_crop_and_current_token() -> None:
    """Real local Tesseract; the image is generated here, never a LOTRO frame."""
    image = Image.new("RGB", (900, 100), "white")
    painter = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30)
    expected = "Bring 10 Ore. Do not trade 1."
    painter.text((25, 22), expected, font=font, fill="black")
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    policy = ready()
    policy.observe(frame(0, digest))
    pending = policy.observe(frame(300, digest))
    assert pending.validation_token is not None
    first = recognize(image, alternative=False)
    second = recognize(image, alternative=True)
    assert decide_text(first, second, qualified_region=False).accepted_text is None
    decision = decide_text(first, second, qualified_region=True)
    assert decision.accepted_text == expected
    assert policy.validated(pending.validation_token, decision.accepted_text).effects == (
        "READ",)
    assert policy.observe(frame(450, digest)).effects == ()
