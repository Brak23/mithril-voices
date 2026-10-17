"""Generated panel-box fixtures; these do not represent LOTRO accuracy."""
from __future__ import annotations

from PIL import Image, ImageDraw

from lvc.vision.auto_calibration import Calibration
from lvc.vision.binding import PixelRect
from lvc.vision.panel_locator import TemplatePanelLocator


def sample(width: int = 800, height: int = 500,
           left: int = 100, top: int = 80) -> tuple[Image.Image, Calibration]:
    image = Image.new("RGB", (width, height), "#202020")
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, top, left + 49, top + 49), fill="#c98c31")
    draw.line((left + 4, top + 4, left + 45, top + 45), fill="white", width=4)
    draw.ellipse((left + 13, top + 7, left + 35, top + 27), outline="black", width=3)
    draw.text((left + 70, top + 72), "Quest body words", fill="white")
    profile = Calibration(width, height, width, height, 96,
                          PixelRect(left, top, 50, 50),
                          PixelRect(left + 60, top + 60, 310, 100))
    return image, profile


def test_template_preview_tracks_moved_panel_and_body_on_ultrawide() -> None:
    initial, profile = sample(2560, 1080)
    locator = TemplatePanelLocator(initial, profile)
    moved, _ = sample(2560, 1080, 1620, 560)
    found = locator.locate(moved)
    assert found.reason == "FOUND"
    assert found.similarity > 0.95
    assert found.anchor == PixelRect(1620, 560, 50, 50)
    assert found.body == PixelRect(1680, 620, 310, 100)
    assert found.panel is not None and found.panel.inside(*moved.size)
    assert locator.locate(moved, found.anchor).body == found.body


def test_preview_abstains_on_missing_duplicated_and_occluded_anchor() -> None:
    initial, profile = sample()
    locator = TemplatePanelLocator(initial, profile)
    assert locator.locate(Image.new("RGB", initial.size, "#202020")).reason == "NOT_FOUND"
    for label in ("JOURNAL", "CHAT", "INVENTORY", "MAP", "VENDOR"):
        other = Image.new("RGB", initial.size, "#202020")
        draw = ImageDraw.Draw(other)
        draw.rectangle((85, 65, 500, 320), outline="#c98c31", width=5)
        draw.text((110, 90), label, fill="white")
        assert locator.locate(other).reason == "NOT_FOUND"
    ambiguous = Image.new("RGB", (800, 500), "#202020")
    anchor = initial.crop((100, 80, 150, 130))
    ambiguous.paste(anchor, (100, 80))
    ambiguous.paste(anchor, (500, 80))
    assert locator.locate(ambiguous).reason == "AMBIGUOUS"
    covered = initial.copy()
    ImageDraw.Draw(covered).rectangle((100, 80, 149, 129), fill="#202020")
    assert locator.locate(covered).reason == "NOT_FOUND"


def test_localizer_maps_body_after_generated_ui_scale_change() -> None:
    initial, profile = sample()
    locator = TemplatePanelLocator(initial, profile)
    for scale in (0.85, 1.15):
        resized = initial.resize((round(initial.width * scale),
                                  round(initial.height * scale)), Image.Resampling.BILINEAR)
        found = locator.locate(resized)
        assert found.reason == "FOUND"
        assert found.body is not None
        assert abs(found.body.x - round(profile.body.x * scale)) <= 1
        assert abs(found.body.y - round(profile.body.y * scale)) <= 1
        assert abs(found.body.width - round(profile.body.width * scale)) <= 1


def test_flat_anchor_cannot_create_detector() -> None:
    image = Image.new("RGB", (800, 500), "#202020")
    ImageDraw.Draw(image).rectangle((100, 80, 149, 129), fill="yellow")
    profile = Calibration(800, 500, 800, 500, 96,
                          PixelRect(100, 80, 50, 50), PixelRect(160, 140, 310, 100))
    try:
        TemplatePanelLocator(image, profile)
    except ValueError as exc:
        assert str(exc) == "DETECTOR_ANCHOR_NOT_DISTINCTIVE"
    else:
        raise AssertionError("flat art must not qualify a panel template")
