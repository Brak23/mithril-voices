"""Walk the actual Tk setup controls with generated frames and no game capture."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from lvc.platform.windows import auto_profile_store, lotro_auto_ui, lotro_observation_ui
from lvc.platform.windows.lotro_auto_ui import AutoNarrationWindow
from lvc.platform.windows.lotro_user_probe import Candidate
from lvc.vision.auto_calibration import selection_issue
from lvc.vision.binding import PixelRect


def test_selection_errors_identify_the_box_to_redraw() -> None:
    frame = Image.new("RGB", (800, 500))
    assert "Capture" in (selection_issue(None, None, None) or "")
    assert "yellow" in (selection_issue(frame, None, None) or "")
    huge = PixelRect(50, 20, 700, 400)
    assert "whole quest window" in (selection_issue(frame, huge, None) or "")
    yellow = PixelRect(100, 80, 50, 50)
    assert "blue" in (selection_issue(frame, yellow, None) or "")
    overlap = PixelRect(120, 90, 230, 160)
    assert "overlap" in (selection_issue(frame, yellow, overlap) or "")
    assert selection_issue(frame, yellow, PixelRect(190, 140, 500, 100)) is None


def test_guided_setup_saves_two_boxes_then_requires_both_samples(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("MITHRIL_GUIDED_UI_CHILD") != "1":
        child = subprocess.run(
            [sys.executable, "-m", "pytest",
             f"{__file__}::test_guided_setup_saves_two_boxes_then_requires_both_samples",
             "-q", "--tb=short", "--color=no", "-o", "addopts=",
             "--basetemp", str(tmp_path / "child")],
            env={**os.environ, "MITHRIL_GUIDED_UI_CHILD": "1"},
            capture_output=True, text=True, timeout=20, check=False)
        assert child.returncode == 0, child.stdout[-1600:] + child.stderr[-1600:]
        return

    monkeypatch.setattr(lotro_auto_ui, "SETTINGS", tmp_path / "preferences.json")
    monkeypatch.setattr(lotro_observation_ui, "PROFILE", tmp_path / "calibration.json")
    monkeypatch.setattr(lotro_auto_ui, "save_saved",
                        lambda candidate, frame, dpi, profile:
                        auto_profile_store.save_saved(candidate, frame, dpi, profile,
                                                      root=tmp_path))
    monkeypatch.setattr(lotro_auto_ui, "load_saved",
                        lambda candidate, frame, dpi:
                        auto_profile_store.load_saved(candidate, frame, dpi,
                                                      root=tmp_path))
    monkeypatch.setattr(lotro_observation_ui, "window_dpi", lambda _candidate: 96)
    candidate = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    frame = Image.new("RGB", (800, 500), "#202020")
    ImageDraw.Draw(frame).rectangle((100, 80, 149, 129), fill="#fccc31")
    window = AutoNarrationWindow(hidden=True, silent=True)
    try:
        window.selected = candidate
        window.frame = frame
        window._show_frame(frame)
        window._update_setup()
        assert window.mode.get() == "anchor"
        assert window.closed_button.cget("state") == "disabled"
        assert window.other_button.cget("state") == "disabled"
        assert window.start_button.cget("state") == "disabled"

        def draw(x1: int, y1: int, x2: int, y2: int) -> None:
            window.press(SimpleNamespace(x=x1, y=y1))  # type: ignore[arg-type]
            window.release(SimpleNamespace(x=x2, y=y2))  # type: ignore[arg-type]

        draw(100, 80, 105, 85)
        assert "too small" in window.status.get()
        assert window.anchor is None
        draw(50, 20, 750, 420)  # Bryce's whole-window yellow selection.
        assert "whole quest window" in window.status.get()
        window.save_regions()
        assert "whole quest window" in window.status.get()
        assert window.profile is None

        draw(100, 80, 150, 130)
        assert window.anchor == PixelRect(100, 80, 50, 50)
        window.mode.set("body")
        draw(190, 140, 195, 145)
        assert "too small" in window.status.get()
        assert window.body is None
        draw(120, 90, 350, 250)
        assert "overlap" in window.status.get()
        window.save_regions()
        assert "overlap" in window.status.get()
        assert window.profile is None
        assert window.anchor == PixelRect(100, 80, 50, 50)

        draw(190, 140, 690, 240)
        assert window.anchor == PixelRect(100, 80, 50, 50)
        assert window.body == PixelRect(190, 140, 500, 100)
        assert len(window.canvas.find_withtag("regions")) == 2
        real_save = lotro_auto_ui.save_saved
        monkeypatch.setattr(lotro_auto_ui, "save_saved",
                            lambda *_args: (_ for _ in ()).throw(OSError("private path")))
        window.save_regions()
        assert "Could not save" in window.status.get()
        assert window.profile is None
        assert window.body is not None
        monkeypatch.setattr(lotro_auto_ui, "save_saved", real_save)
        window.save_regions()
        assert window.profile is not None
        assert len(list(tmp_path.glob("calibration-*.json"))) == 1
        assert window.closed_button.cget("state") == "normal"
        assert window.other_button.cget("state") == "normal"
        assert window.start_button.cget("state") == "disabled"
        assert "close the quest" in window.setup_step.get()

        negative = Image.new("RGB", frame.size, "#202020")
        assert window._handle_extra_capture("closed-control", negative, 96)
        assert "Quest-closed sample passed" in window.status.get()
        assert window.start_button.cget("state") == "disabled"
        assert window._handle_extra_capture("journal-control", negative, 96)
        assert "Journal/inventory sample passed" in window.status.get()
        assert window.start_button.cget("state") == "normal"

        draw(200, 150, 680, 235)  # Editing one box invalidates both samples.
        assert window.profile is None and not window.controls
        assert window.anchor == PixelRect(100, 80, 50, 50)
        assert window.start_button.cget("state") == "disabled"
        assert window.closed_button.cget("state") == "disabled"
        monkeypatch.setattr(window, "_capture", lambda _purpose: None)
        window.calibration_capture()
        assert window.mode.get() == "anchor"
        assert not window.controls
        window.windows = {"Synthetic": candidate}
        window.window_choice.set("Synthetic")
        window.choose_window()
        assert window.selected == candidate
        assert window.anchor is None and window.body is None
        assert window.closed_button.cget("state") == "disabled"
        window.selected = Candidate(55, 66, 70, candidate.executable_path,
                                    "New game process", 800, 500)
        window.capture_serial += 1
        window.results.put(("calibration", (window.capture_serial, (frame, 96))))
        window.poll()
        assert window.anchor == PixelRect(100, 80, 50, 50)
        assert window.body == PixelRect(190, 140, 500, 100)
        assert window.profile is None and not window.controls
        assert window.start_button.cget("state") == "disabled"
        assert "Saved yellow and blue boxes loaded" in window.status.get()
    finally:
        window.close()
