"""Old installed box geometry migrates once without opening safety gates."""
from __future__ import annotations

from pathlib import Path

from lvc.vision.auto_calibration import Calibration, load_profile, save_profile
from lvc.vision.binding import PixelRect
from tools.build_auto_package import _carry_previous_boxes


def test_previous_geometry_is_imported_once_and_malformed_is_ignored(tmp_path: Path) -> None:
    old = tmp_path / "old" / ".audition"
    old.mkdir(parents=True)
    preferences = old / "auto-preferences.json"
    preferences.write_text("{}", encoding="utf-8")
    boxes = Calibration(800, 500, 800, 500, 96,
                        PixelRect(100, 80, 50, 50), PixelRect(190, 140, 500, 100))
    save_profile(old / "auto-calibration.json", boxes)
    destination = tmp_path / "state" / "legacy-calibration.json"
    assert _carry_previous_boxes(preferences, destination)
    assert load_profile(destination) == boxes
    assert not _carry_previous_boxes(preferences, destination)
    destination.unlink()
    (old / "auto-calibration.json").write_text('{"version":1,"anchor":[]}',
                                                encoding="utf-8")
    assert not _carry_previous_boxes(preferences, destination)
    assert not destination.exists()
