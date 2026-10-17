"""Saved box coordinates survive builds while safety samples remain session local."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from lvc.platform.windows.auto_profile_store import load_saved, profile_path, save_saved
from lvc.platform.windows.lotro_user_probe import Candidate
from lvc.vision.auto_calibration import Calibration, save_profile
from lvc.vision.binding import PixelRect


def candidate(*, hwnd: int = 10, pid: int = 20,
              path: str = "C:/Games/lotroclient64.exe",
              width: int = 800) -> Candidate:
    return Candidate(hwnd, pid, 30, path, "Synthetic", width, 500)


def profile(width: int = 800, dpi: int = 96) -> Calibration:
    return Calibration(width, 500, width, 500, dpi,
                       PixelRect(100, 80, 50, 50), PixelRect(190, 140, 500, 100))


def test_geometry_survives_new_process_but_not_size_dpi_or_install(tmp_path: Path) -> None:
    image = Image.new("RGB", (800, 500), "black")
    saved_path = save_saved(candidate(), image, 96, profile(), root=tmp_path)
    payload = saved_path.read_text(encoding="utf-8")
    assert json.loads(payload)["anchor"] == [100, 80, 50, 50]
    assert all(word not in payload for word in ("Games", "Synthetic", "sample", "pixels"))
    loaded, reason = load_saved(candidate(hwnd=55, pid=66), image, 96, root=tmp_path)
    assert reason == "SAVED_BOXES_LOADED" and loaded == profile()
    for other, frame, dpi in (
        (candidate(width=900), Image.new("RGB", (900, 500)), 96),
        (candidate(), image, 120),
        (candidate(path="D:/Other/lotroclient64.exe"), image, 96),
    ):
        assert load_saved(other, frame, dpi, root=tmp_path) == (
            None, "NO_SAVED_BOXES_FOR_GEOMETRY")


def test_malformed_saved_profile_abstains_and_legacy_requires_exact_geometry(
        tmp_path: Path) -> None:
    image = Image.new("RGB", (800, 500))
    path = profile_path(candidate(), image, 96, root=tmp_path)
    path.write_text('{"version":1,"anchor":[1,2,3,4],"anchor":[4,3,2,1]}',
                    encoding="utf-8")
    assert load_saved(candidate(), image, 96, root=tmp_path) == (
        None, "SAVED_BOXES_INVALID")
    path.unlink()
    save_profile(tmp_path / "legacy-calibration.json", profile())
    assert load_saved(candidate(), image, 96, root=tmp_path) == (
        profile(), "PREVIOUS_BOXES_LOADED")
    assert load_saved(candidate(), image, 120, root=tmp_path) == (
        None, "NO_SAVED_BOXES_FOR_GEOMETRY")
