"""One hidden synthetic UI session; no LOTRO window or audio device is used."""
from __future__ import annotations

import hashlib
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from lvc.platform.windows import lotro_auto_ui, lotro_observation_ui
from lvc.platform.windows.lotro_auto_ui import AutoNarrationWindow
from lvc.platform.windows.lotro_observation_ui import CaptureRunner
from lvc.platform.windows.lotro_probe_ui import OcrCancelled, OcrProcessRunner
from lvc.platform.windows.lotro_user_probe import Candidate
from lvc.platform.windows.manual_read import OutputDevice
from lvc.vision.auto_calibration import Calibration, anchor_signature, scene_fingerprint
from lvc.vision.binding import PixelRect
from lvc.vision.panel_locator import TemplatePanelLocator
from lvc.vision.text_gate import TextDecision


def test_auto_ui_requires_controls_and_fences_stale_pages(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("MITHRIL_AUTO_UI_TEST_CHILD") != "1":
        # Tk occasionally corrupts its second root in a long Windows pytest
        # process. Keep this one real-root integration test process-local.
        child = subprocess.run(
            [sys.executable, "-m", "pytest",
             f"{__file__}::test_auto_ui_requires_controls_and_fences_stale_pages",
             "-q", "--tb=short", "--color=no", "-o", "addopts=",
             "--basetemp", str(tmp_path / "child")],
            env={**os.environ, "MITHRIL_AUTO_UI_TEST_CHILD": "1"},
            capture_output=True, text=True, timeout=20, check=False,
        )
        assert child.returncode == 0, child.stdout[-1200:] + child.stderr[-1200:]
        return
    monkeypatch.setattr(lotro_auto_ui, "SETTINGS", tmp_path / "auto-settings.json")
    clock = [1_000_000_000]
    monkeypatch.setattr(lotro_observation_ui.time, "monotonic_ns", lambda: clock[0])
    positive = Image.new("RGB", (800, 500), "black")
    drawer = ImageDraw.Draw(positive)
    drawer.rectangle((100, 80, 149, 129), fill="#ffcc44")
    drawer.line((100, 80, 149, 129), fill="#303030", width=5)
    drawer.text((200, 150), "The gate is open.", fill="white")
    negative = Image.new("RGB", (800, 500), "black")
    journal = negative.copy()
    ImageDraw.Draw(journal).rectangle((600, 300, 750, 450), fill="#405e57")
    next_page = positive.copy()
    ImageDraw.Draw(next_page).text((200, 180), "Another page.", fill="white")
    profile = Calibration(800, 500, 800, 500, 96,
                          PixelRect(100, 80, 50, 50),
                          PixelRect(190, 140, 500, 100))
    candidate = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    window = AutoNarrationWindow(hidden=True, silent=True)
    try:
        assert "small unchanging corner" in window.instructions_label.cget("text")
        assert "never speech" not in window.candidate_label.cget("text")
        window.selected = candidate
        window.frame = positive
        window.anchor, window.body = profile.anchor, profile.body
        window.profile = profile
        window.reference = anchor_signature(positive, profile)
        window.positive_scene = scene_fingerprint(positive)
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

        template = positive.copy()
        ImageDraw.Draw(template).line((103, 83, 145, 125), fill="black", width=4)
        window.panel_locator = TemplatePanelLocator(template, profile)
        moved = Image.new("RGB", (800, 500), "black")
        moved.paste(template.crop((100, 80, 150, 130)), (200, 200))
        assert window._handle_extra_capture("panel-preview", moved, 96)
        assert window.preview_anchor == PixelRect(200, 200, 50, 50)
        assert "does not authorize speech" in window.status.get()
        assert window.frame is None  # Preview cannot replace the open-pane Save source.
        assert not window.save_regions()
        assert "Capture an open quest window" in window.status.get()
        window.frame = positive

        window.start()
        assert not window.running
        assert window._handle_extra_capture("closed-control", negative, 96)
        assert window._handle_extra_capture("journal-control", journal, 96)
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
        old_runner = OcrProcessRunner()
        window.ocr_runner = old_runner
        window._observe_frame(next_page, 96)
        assert stops  # Change fences currently playing speech before OCR.
        assert old_runner.cancelled.is_set()
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
        window.positive_scene = scene_fingerprint(positive)
        window.controls = {"closed-control": 0.8, "journal-control": 0.8}
        window.control_scenes = {"closed-control": scene_fingerprint(negative),
                                 "journal-control": scene_fingerprint(journal)}
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
        window.stop()
        assert window.status.get().startswith("Automatic capture and speech stopped")
        window.start()
        assert window.running
        window._observe_frame(positive, 120)
        assert not window.running and not window.controls
    finally:
        window.close()


def test_auto_ocr_worker_cancellation_never_returns_accepted_text(
        monkeypatch: pytest.MonkeyPatch) -> None:
    window = object.__new__(AutoNarrationWindow)
    window.metrics = {"ocr_attempts": 0}
    window.results = queue.Queue()
    window.epoch = 7
    started = threading.Event()

    class Status:
        def set(self, _value: str) -> None:
            pass

    window.status = Status()  # type: ignore[assignment]

    def delayed(_body: Image.Image, runner: OcrProcessRunner) -> object:
        started.set()
        assert runner.cancelled.wait(2)
        raise OcrCancelled()

    monkeypatch.setattr(lotro_auto_ui, "recognize_auto_crop", delayed)
    window._recognize(Image.new("RGB", (100, 60)), (3, "a" * 64))
    assert started.wait(2)
    assert window.ocr_runner is not None
    window.ocr_runner.cancel()
    purpose, payload = window.results.get(timeout=3)
    assert purpose == "ocr"
    assert payload == (7, (3, "a" * 64), "WINDOWS_OCR_UNAVAILABLE_OR_CANCELED")


def test_capture_rejects_missing_or_resized_window_before_child(
        monkeypatch: pytest.MonkeyPatch) -> None:
    selected = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    monkeypatch.setattr(lotro_observation_ui, "capture_preflight", lambda **_kw: None)
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


def test_auto_capture_preflight_requires_native_helper_without_tesseract(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    native = tmp_path / "native.exe"
    native.write_bytes(b"synthetic native helper hash")
    monkeypatch.setattr(lotro_observation_ui, "NATIVE_PROBE", native)
    monkeypatch.setattr(lotro_observation_ui, "EXPECTED_NATIVE_SHA256",
                        hashlib.sha256(native.read_bytes()).hexdigest())
    monkeypatch.setattr(lotro_observation_ui, "TESSERACT", tmp_path / "missing.exe")
    lotro_observation_ui.capture_preflight(require_tesseract=False)
    with pytest.raises(RuntimeError, match="CAPTURE_OR_TESSERACT_UNAVAILABLE"):
        lotro_observation_ui.capture_preflight()
