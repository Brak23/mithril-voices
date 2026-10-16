"""Hidden Tk synthetic observation; verified LOTRO capture is never invoked."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from lvc.platform.windows import lotro_observation_ui
from lvc.platform.windows.lotro_observation_ui import ObservationWindow
from lvc.platform.windows.lotro_user_probe import Candidate
from lvc.vision.auto_calibration import Calibration, anchor_signature, body_digest
from lvc.vision.auto_observation import Observation
from lvc.vision.binding import PixelRect


def test_hidden_ui_surfaces_stable_candidate_without_starting_speech(
        monkeypatch: pytest.MonkeyPatch) -> None:
    frame = Image.new("RGB", (800, 500), "#202020")
    ImageDraw.Draw(frame).rectangle((100, 80, 149, 129), fill="#ffcc44")
    profile = Calibration(800, 500, 800, 500, 96,
                          PixelRect(100, 80, 50, 50),
                          PixelRect(190, 140, 500, 100))
    window = ObservationWindow(hidden=True)
    try:
        window.selected = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic",
                                    800, 500)
        window.profile = profile
        window.reference = anchor_signature(frame, profile)
        window.running = True
        window.metrics = {key: 0 for key in (
            "frames", "anchor_present", "anchor_absent", "body_changes",
            "confirmed_closes", "ocr_attempts", "ocr_text_gate_passes",
            "ocr_abstentions", "capture_failures")}
        window.started_ms = time.monotonic_ns() // 1_000_000 - 300
        window.policy.bind("10:20:30", 1)
        window.policy.auto_on()
        digest = body_digest(frame, profile)
        assert window.policy.observe(Observation(0, "10:20:30", 1, True,
                                                 True, digest)).effects == ()
        attempts: list[tuple[int, str]] = []
        monkeypatch.setattr(window, "_recognize", lambda _image, token: attempts.append(token))
        window._observe_frame(frame, 96)
        assert window.metrics["frames"] == 1
        assert window.metrics["anchor_present"] == 1
        assert len(attempts) == 1
        assert window.candidate_text.get("1.0", "end-1c") == ""
    finally:
        window.running = False  # Test does not write a run summary.
        window.close()


def test_summary_contains_metrics_but_no_candidate_text(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window = ObservationWindow(hidden=True)
    try:
        path = tmp_path / "summary.json"
        monkeypatch.setattr(lotro_observation_ui, "SUMMARY", path)
        window.profile = Calibration(800, 500, 800, 500, 96,
                                     PixelRect(100, 80, 50, 50),
                                     PixelRect(190, 140, 500, 100))
        window.metrics = {"frames": 3, "ocr_text_gate_passes": 1}
        window.started_ms = time.monotonic_ns() // 1_000_000
        window.set_text("PRIVATE QUEST WORDS")
        window._save_summary()
        saved = path.read_text(encoding="utf-8")
        assert "PRIVATE QUEST WORDS" not in saved
        assert '"frames": 3' in saved
    finally:
        window.close()
