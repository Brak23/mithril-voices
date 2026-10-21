"""Local replay reports detection and crop quality without retaining text."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from lvc.vision.binding import PixelRect
from lvc.vision.structural_panel import PanelDetection, PanelProposal
from tools.replay_panel_detector import replay


class FixedDetector:
    def detect(self, frame: Image.Image) -> PanelDetection:
        if frame.getpixel((0, 0)) == (255, 0, 0):
            return PanelDetection("NOT_FOUND", ())
        return PanelDetection("FOUND", (PanelProposal(
            PixelRect(30, 20, 200, 160), PixelRect(40, 40, 120, 90),
            0.9, ("test",)),))


def test_replay_measures_missing_and_extra_crop_area_and_negative(tmp_path: Path) -> None:
    Image.new("RGB", (300, 200), "black").save(tmp_path / "positive.png")
    Image.new("RGB", (300, 200), "red").save(tmp_path / "negative.png")
    rows = [
        {"image": "positive.png", "group": "source-a", "split": "development",
         "label": "quest", "source": "generated", "rights": "test",
         "panel": [30, 20, 200, 160], "body": [45, 45, 100, 80]},
        {"image": "negative.png", "group": "source-b", "split": "holdout",
         "label": "absent", "source": "generated", "rights": "test"},
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(rows), encoding="utf-8")
    output = replay(manifest, FixedDetector())
    assert output["counts"] == {"development_quest_found": 1,
                                "holdout_absent_not_found": 1}
    assert output["results"][0]["body_coverage"] == 1.0
    assert output["results"][0]["body_purity"] < 1.0
    assert output["contains_pixels_or_text"] is False


def test_replay_rejects_source_group_leaking_across_splits(tmp_path: Path) -> None:
    Image.new("RGB", (300, 200), "red").save(tmp_path / "negative.png")
    rows = [{"image": "negative.png", "group": "same-source", "split": split,
             "label": "absent", "source": "generated", "rights": "test"}
            for split in ("development", "holdout")]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="REPLAY_GROUP_SPLIT_LEAK"):
        replay(manifest, FixedDetector())
