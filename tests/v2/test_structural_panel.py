"""Structural proposals use independent geometry, not saved box positions."""
from __future__ import annotations

from PIL import Image, ImageDraw

from lvc.vision.structural_panel import (
    StructuralPanelDetector,
    StructuralSessionGuard,
    readable_body,
)
from lvc.vision.text_gate import OcrPass, OcrWord


def pane(*, x: int, y: int, width: int, height: int,
         background: str = "#10151c", border: str = "#b6abb8") -> Image.Image:
    frame = Image.new("RGB", (1400, 900), "#394437")
    draw = ImageDraw.Draw(frame)
    divider = x + round(width * 0.67)
    draw.rectangle((x, y, x + width, y + height),
                   fill=background, outline=border, width=2)
    draw.line((divider, y + 22, divider, y + height - 22), fill=border, width=2)
    draw.line((x + 12, y + 22, x + 12, y + height - 22), fill=border, width=2)
    draw.line((x + 12, y + 22, x + width - 12, y + 22), fill=border, width=2)
    draw.line((x + 12, y + height - 22, x + width - 12, y + height - 22),
              fill=border, width=2)
    for index in range(7):
        draw.text((x + 24, y + 42 + index * 18), "A quest dialogue line.", fill=border)
    draw.text((divider + 16, y + 42), "Objective", fill=border)
    return frame


def test_color_movement_and_independent_resize_keep_body_left_of_divider() -> None:
    detector = StructuralPanelDetector()
    for x, y, width, height, background, border in (
        (60, 40, 650, 520, "#10151c", "#b6abb8"),
        (660, 250, 650, 520, "#ded8b6", "#222233"),
        (210, 80, 920, 600, "#10151c", "#b6abb8"),
    ):
        image = pane(x=x, y=y, width=width, height=height,
                     background=background, border=border)
        result = detector.detect(image)
        assert result.reason == "FOUND"
        selected = result.selected
        assert selected is not None
        divider = x + round(width * 0.67)
        assert abs(selected.body.x - x) < 30
        assert selected.body.x + selected.body.width < divider + 8
        assert selected.body.y <= y + 60
        assert selected.body.y + selected.body.height >= y + height - 50


def test_blank_and_unrelated_text_abstain() -> None:
    detector = StructuralPanelDetector()
    blank = Image.new("RGB", (1400, 900), "#303030")
    assert detector.detect(blank).reason == "NOT_FOUND"
    unrelated = blank.copy()
    draw = ImageDraw.Draw(unrelated)
    for index in range(24):
        draw.text((40, 40 + index * 25), "Journal inventory and chat text", fill="white")
    assert detector.detect(unrelated).reason == "NOT_FOUND"


def test_two_quest_shaped_panels_abstain_on_ambiguous_candidates() -> None:
    image = pane(x=40, y=60, width=600, height=500)
    another = pane(x=740, y=60, width=600, height=500)
    image.paste(another.crop((740, 60, 1341, 561)), (740, 60))
    assert StructuralPanelDetector().detect(image).reason == "AMBIGUOUS"


def test_session_requires_two_absences_and_tracks_moved_geometry() -> None:
    detector = StructuralPanelDetector()
    positive = pane(x=60, y=40, width=650, height=520)
    guard = StructuralSessionGuard(detector, positive)
    moved = pane(x=660, y=250, width=650, height=520)
    assert guard.locate(moved) is None
    closed = Image.new("RGB", positive.size, "#303030")
    inventory = closed.copy()
    ImageDraw.Draw(inventory).rectangle((100, 100, 350, 250), outline="white")
    assert guard.negative("closed-control", closed)
    assert not guard.ready
    assert guard.negative("journal-control", inventory)
    assert guard.ready
    located = guard.locate(moved)
    assert located is not None and located.body.x > guard.positive.body.x
    assert guard.locate(closed) is None
    assert not guard.negative("journal-control", positive)
    assert not guard.ready


def test_readability_requires_lines_and_unclipped_confident_words() -> None:
    good = OcrPass("A real dialogue sentence.\nAnother line follows.",
                   tuple(OcrWord(f"word{index}", 90) for index in range(8)))
    assert readable_body(good)
    assert not readable_body(OcrPass("One line only", good.words))
    assert not readable_body(OcrPass(good.raw_text, good.words[:-1]
                                      + (OcrWord("edge", 90, True),)))
