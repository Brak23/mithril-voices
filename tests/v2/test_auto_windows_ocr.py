"""Windows OCR automatic admission checks, using synthetic in-memory crops."""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from lvc.platform.windows.auto_windows_ocr import recognize_auto_crop
from lvc.platform.windows.lotro_probe_ui import OcrCancelled, OcrProcessRunner
from lvc.vision.windows_text_gate import crop_edge_clear, decide_windows_text


def test_windows_text_requires_two_nonempty_agreeing_variants() -> None:
    assert decide_windows_text("Bring 10 Ore.\nNow.", "Bring 10 Ore. Now.",
                               clear_edge=True).accepted_text == "Bring 10 Ore.\nNow."
    assert decide_windows_text("", "Words", clear_edge=True).reason == "EMPTY_OCR_OUTPUT"
    assert decide_windows_text("Bring ten ore", "Bring ten", clear_edge=True).reason == (
        "OCR_VARIANT_DISAGREEMENT")
    assert decide_windows_text("Words", "Words", clear_edge=False).reason == (
        "CROP_EDGE_UNCLEAR")
    assert decide_windows_text("Words\ufffd", "Words\ufffd", clear_edge=True).reason == (
        "OCR_TEXT_INVALID")


def test_windows_text_normalization_does_not_rewrite_spoken_text() -> None:
    original = "Caf\u00e9,  TWO\nLines."
    alternative = "Cafe\u0301, two lines."
    decision = decide_windows_text(original, alternative, clear_edge=True)
    assert decision.accepted_text == original
    assert decide_windows_text("Words\x00", "Words\x00", clear_edge=True).reason == (
        "OCR_TEXT_INVALID")
    assert decide_windows_text("...", "...", clear_edge=True).reason == (
        "OCR_TEXT_INVALID")
    assert decide_windows_text("a" * 3001, "a" * 3001, clear_edge=True).reason == (
        "OCR_TEXT_INVALID")


def test_edge_check_abstains_on_truncated_or_decorated_crop() -> None:
    clear = Image.new("RGB", (160, 75), "#202020")
    ImageDraw.Draw(clear).text((10, 22), "Quest words", fill="white")
    assert crop_edge_clear(clear)
    clipped = clear.copy()
    ImageDraw.Draw(clipped).rectangle((0, 15, 2, 35), fill="white")
    assert not crop_edge_clear(clipped)
    assert not crop_edge_clear(Image.new("RGB", (30, 30)))


def test_auto_crop_uses_padded_second_variant_and_checks_cancellation() -> None:
    image = Image.new("RGB", (160, 75), "#202020")
    ImageDraw.Draw(image).text((10, 22), "Quest words", fill="white")
    runner = OcrProcessRunner()
    sizes: list[tuple[int, int]] = []

    def native(crop: Image.Image, _runner: OcrProcessRunner) -> str:
        sizes.append(crop.size)
        return "Quest words"

    result = recognize_auto_crop(image, runner, native)
    assert result.reason == "ACCEPTED_WINDOWS_OCR"
    assert sizes == [(160, 75), (184, 99)]
    sizes.clear()

    def canceled(crop: Image.Image, owner: OcrProcessRunner) -> str:
        sizes.append(crop.size)
        owner.cancel()
        return "Quest words"

    with pytest.raises(OcrCancelled):
        recognize_auto_crop(image, OcrProcessRunner(), canceled)
    assert sizes == [(160, 75)]


def test_auto_crop_native_failure_does_not_fallback_to_other_engine() -> None:
    image = Image.new("RGB", (160, 75), "#202020")

    def unavailable(_image: Image.Image, _runner: OcrProcessRunner) -> str:
        raise RuntimeError("WINDOWS_OCR_UNAVAILABLE")

    with pytest.raises(RuntimeError, match="WINDOWS_OCR_UNAVAILABLE"):
        recognize_auto_crop(image, OcrProcessRunner(), unavailable)
