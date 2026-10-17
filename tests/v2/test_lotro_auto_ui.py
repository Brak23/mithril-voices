"""One hidden synthetic UI session; no LOTRO window or audio device is used."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from lvc.platform.windows import lotro_auto_ui, lotro_observation_ui
from lvc.platform.windows.lotro_auto_ui import AutoNarrationWindow
from lvc.platform.windows.lotro_observation_ui import CaptureRunner
from lvc.platform.windows.lotro_user_probe import Candidate
from lvc.platform.windows.manual_read import OutputDevice
from lvc.vision.auto_calibration import Calibration, anchor_signature
from lvc.vision.binding import PixelRect
from lvc.vision.text_gate import TextDecision


def test_auto_ui_requires_controls_and_fences_stale_pages(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lotro_auto_ui, "SETTINGS", tmp_path / "auto-settings.json")
    clock = [1_000_000_000]
    monkeypatch.setattr(lotro_observation_ui.time, "monotonic_ns", lambda: clock[0])
    positive = Image.new("RGB", (800, 500), "black")
    drawer = ImageDraw.Draw(positive)
    drawer.rectangle((100, 80, 149, 129), fill="#ffcc44")
    drawer.text((200, 150), "The gate is open.", fill="white")
    negative = Image.new("RGB", (800, 500), "black")
    next_page = positive.copy()
    ImageDraw.Draw(next_page).text((200, 180), "Another page.", fill="white")
    profile = Calibration(800, 500, 800, 500, 96,
                          PixelRect(100, 80, 50, 50),
                          PixelRect(190, 140, 500, 100))
    candidate = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    window = AutoNarrationWindow(hidden=True, silent=True)
    try:
        window.selected = candidate
        window.frame = positive
        window.anchor, window.body = profile.anchor, profile.body
        window.profile = profile
        window.reference = anchor_signature(positive, profile)
        window.devices = {"Synthetic": OutputDevice("synthetic", "Synthetic")}
        window.device_choice.set("Synthetic")
        window.reader.ready = True
        window.reader._voice = "bf_emma"
        current: list[Candidate | None] = [candidate]
        monkeypatch.setattr(lotro_observation_ui, "candidate_for_hwnd", lambda _hwnd: current[0])
        monkeypatch.setattr(lotro_observation_ui, "window_dpi", lambda _candidate: 96)
        monkeypatch.setattr(window, "_capture", lambda _purpose: None)
        recognized: list[tuple[int, str]] = []
        monkeypatch.setattr(window, "_recognize", lambda _body, token: recognized.append(token))
        sent: list[str] = []
        monkeypatch.setattr(window.reader, "read_auto",
                            lambda text, _token, _voice, _device, **_kw:
                            (sent.append(text) or True))
        stops: list[int] = []
        monkeypatch.setattr(window.reader, "stop", lambda **_kw: stops.append(1))

        window.start()
        assert not window.running
        assert window._handle_extra_capture("closed-control", negative, 96)
        assert window._handle_extra_capture("journal-control", negative, 96)
        current[0] = None  # A minimized, closed or replaced game cannot arm Auto.
        window.start()
        assert not window.running
        current[0] = candidate
        window.start()
        assert window.running and window.bridge is not None
        assert window.frame is None and window.photo is None
        window._observe_frame(positive, 96)
        clock[0] += 300_000_000
        window._observe_frame(positive, 96)
        assert len(recognized) == 1
        first = recognized[-1]
        window.results.put(("ocr", (window.epoch, first,
                                    TextDecision("The gate is open.",
                                                 "The gate is open.", "ACCEPTED"))))
        window.poll()
        assert sent == ["The gate is open."]
        assert window.bridge.state.auto_read_pages

        clock[0] += 100_000_000
        window._observe_frame(positive, 96)
        assert len(recognized) == 1  # Same stable page is never replayed.
        clock[0] += 100_000_000
        window._observe_frame(next_page, 96)
        assert stops  # Change fences currently playing speech before OCR.
        assert window.bridge.validated(first, "Late old text.", 501).effects == ()
        clock[0] += 300_000_000
        window._observe_frame(next_page, 96)
        assert len(recognized) == 2
        second = recognized[-1]
        window.results.put(("ocr", (window.epoch, second,
                                    TextDecision("New page.", "New page.", "ACCEPTED"))))
        window.poll()
        assert sent == ["The gate is open.", "New page."]

        clock[0] += 100_000_000
        window._observe_frame(negative, 96)
        clock[0] += 125_000_000
        window._observe_frame(negative, 96)
        assert window.bridge.state.page is None
        window._observe_frame(positive.resize((900, 500)), 96)
        assert not window.running
        assert window.pending_speech is None
        window.start()
        assert not window.running
        window.profile = profile
        window.reference = anchor_signature(positive, profile)
        window.controls = {"closed-control": 0.8, "journal-control": 0.8}
        window.start()
        assert window.running
        window._observe_frame(positive, 96)
        clock[0] += 300_000_000
        window._observe_frame(positive, 96)
        assert len(recognized) == 3
        window.results.put(("ocr", (window.epoch, recognized[-1], "OCR_UNAVAILABLE")))
        window.poll()
        assert sent == ["The gate is open.", "New page."]
        assert window.metrics["ocr_abstentions"] == 1
        window.pause()
        assert not window.running
        assert window.pending_speech is None
        window.start()
        assert window.running
        window._observe_frame(positive, 120)
        assert not window.running and not window.controls
    finally:
        window.close()


def test_capture_rejects_missing_or_resized_window_before_child(
        monkeypatch: pytest.MonkeyPatch) -> None:
    selected = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    monkeypatch.setattr(lotro_observation_ui, "capture_preflight", lambda: None)
    monkeypatch.setattr(lotro_observation_ui.subprocess, "Popen",
                        lambda *_a, **_kw: pytest.fail("native capture must not start"))
    for current in (None, Candidate(10, 20, 30, "C:/lotroclient64.exe",
                                    "Synthetic", 900, 500),
                    Candidate(10, 21, 30, "C:/lotroclient64.exe", "Synthetic",
                              800, 500)):
        monkeypatch.setattr(lotro_observation_ui, "candidate_for_hwnd",
                            lambda _hwnd, value=current: value)
        with pytest.raises(RuntimeError, match="WINDOW_IDENTITY_OR_SIZE_CHANGED"):
            CaptureRunner().capture(selected)
