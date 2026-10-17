"""Synthetic calibration invariants; no real game frame or audio."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from lvc.vision.auto_calibration import (
    Calibration,
    anchor_difference,
    anchor_quality_issue,
    anchor_signature,
    body_digest,
    load_profile,
    save_profile,
    scene_fingerprint,
)
from lvc.vision.binding import PixelRect


def fixture() -> tuple[Image.Image, Calibration]:
    frame = Image.new("RGB", (800, 500), "#202020")
    painter = ImageDraw.Draw(frame)
    painter.rectangle((100, 80, 149, 129), fill="#ffcc44")
    painter.text((200, 150), "Bring 10 Ore. Do not trade 1.", fill="white")
    profile = Calibration(800, 500, 800, 500, 96,
                          PixelRect(100, 80, 50, 50),
                          PixelRect(190, 140, 500, 100))
    return frame, profile


def test_only_geometry_is_saved_and_loaded(tmp_path: Path) -> None:
    frame, profile = fixture()
    path = tmp_path / "calibration.json"
    save_profile(path, profile)
    raw = path.read_text(encoding="utf-8")
    assert "Bring" not in raw and "screenshot" not in raw
    assert load_profile(path) == profile
    assert profile.matches(frame, 800, 500, 96)
    assert not profile.matches(frame, 800, 500, 120)
    assert not profile.matches(Image.new("RGB", (801, 500)), 800, 500, 96)


def test_anchor_and_body_change_are_observable_without_retention() -> None:
    frame, profile = fixture()
    reference = anchor_signature(frame, profile)
    assert anchor_difference(reference, frame, profile) == 0
    old_body = body_digest(frame, profile)
    changed = frame.copy()
    ImageDraw.Draw(changed).rectangle((100, 80, 149, 129), fill="#202020")
    assert anchor_difference(reference, changed, profile) > 0.1
    changed = frame.copy()
    ImageDraw.Draw(changed).text((200, 190), "A new page.", fill="white")
    assert body_digest(changed, profile) != old_body


def test_plain_anchor_is_rejected_and_thin_detail_survives_same_color_background() -> None:
    frame, profile = fixture()
    assert "plain color" in (anchor_quality_issue(frame, profile.anchor) or "")
    positive = frame.copy()
    ImageDraw.Draw(positive).line((100, 80, 149, 129), fill="#303030", width=5)
    assert anchor_quality_issue(positive, profile.anchor) is None
    reference = anchor_signature(positive, profile)
    assert anchor_difference(reference, positive, profile) == 0
    # The quest-specific line is gone, but the same gold is behind it.
    assert anchor_difference(reference, frame, profile) > 0.16
    moved = frame.copy()
    ImageDraw.Draw(moved).line((200, 200, 249, 249), fill="#303030", width=5)
    assert anchor_difference(reference, moved, profile) > 0.16
    assert scene_fingerprint(positive) != scene_fingerprint(moved)
    red = frame.copy()
    green = frame.copy()
    ImageDraw.Draw(red).rectangle((100, 80, 149, 129), fill=(255, 0, 0))
    ImageDraw.Draw(green).rectangle((100, 80, 149, 129), fill=(0, 130, 0))
    # Similar grayscale brightness still must not erase a real color change.
    assert anchor_difference(anchor_signature(red, profile), green, profile) > 0.16


def test_overlap_and_unvalidated_shapes_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OVERLAP"):
        Calibration(800, 500, 800, 500, 96, PixelRect(200, 150, 40, 40),
                    PixelRect(190, 140, 500, 100))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 1, "frame": [800, 500],
                                "client": [800, 500], "dpi": True,
                                "anchor": [100, 80, 50, 50],
                                "body": [190, 140, 500, 100]}), encoding="utf-8")
    with pytest.raises(ValueError, match="CALIBRATION_INVALID"):
        load_profile(path)
