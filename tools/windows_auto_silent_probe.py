"""Synthetic image -> real OCR -> local voice -> silent Qt admission smoke.

No native window capture, speaker output, LOTRO interaction or stored image/text.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from lvc.core import PageIdentity, RequestToken
from lvc.platform.windows import lotro_auto_ui, lotro_observation_ui
from lvc.platform.windows.lotro_auto_ui import AutoNarrationWindow
from lvc.platform.windows.lotro_user_probe import Candidate
from lvc.platform.windows.manual_read import OutputDevice
from lvc.vision.auto_calibration import Calibration, anchor_signature
from lvc.vision.binding import PixelRect

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_TEXT = "Bring 10 Ore. Do not trade 1."


def run() -> dict[str, object]:
    frame = Image.new("RGB", (800, 500), "#202020")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((100, 80, 149, 129), fill="#ffcc44")
    draw.rectangle((190, 140, 689, 239), fill="white")
    draw.text((202, 162), SYNTHETIC_TEXT,
              font=ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30), fill="black")
    absent = Image.new("RGB", frame.size, "#202020")
    profile = Calibration(800, 500, 800, 500, 96,
                          PixelRect(100, 80, 50, 50),
                          PixelRect(190, 140, 500, 100))
    candidate = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    private_temp = ROOT / ".audition" / "tmp"
    private_temp.mkdir(parents=True, exist_ok=True)
    settings_dir = tempfile.TemporaryDirectory(dir=private_temp)
    lotro_auto_ui.SETTINGS = Path(settings_dir.name) / "auto-preferences.json"
    lotro_observation_ui.candidate_for_hwnd = lambda _hwnd: candidate
    lotro_observation_ui.window_dpi = lambda _candidate: 96
    window = AutoNarrationWindow(hidden=True, silent=True)
    started = time.monotonic()
    events: dict[str, float] = {}
    event_log: list[str] = []
    cancel_on_unit = [False]
    original_put = window.reader.events.put

    def record(item: tuple[str, str], block: bool = True,
               timeout: float | None = None) -> None:
        events.setdefault(item[0], time.monotonic() - started)
        event_log.append(item[0])
        original_put(item, block, timeout)
        if cancel_on_unit[0] and item[0] == "UNIT_STARTED":
            cancel_on_unit[0] = False
            window.reader.stop()

    window.reader.events.put = record  # type: ignore[method-assign]
    try:
        window.selected = candidate
        window.frame = frame
        window.anchor, window.body = profile.anchor, profile.body
        window.profile = profile
        window.reference = anchor_signature(frame, profile)
        window.devices = {"Synthetic": OutputDevice("synthetic", "Synthetic")}
        window.device_choice.set("Synthetic")
        window._capture = lambda _purpose: None  # type: ignore[method-assign]
        window._handle_extra_capture("closed-control", absent, 96)
        window._handle_extra_capture("journal-control", absent, 96)
        window.prepare_voice()
        ready_deadline = time.monotonic() + 50
        while time.monotonic() < ready_deadline and not window.reader.ready:
            window.root.update()
            time.sleep(0.05)
        if not window.reader.ready:
            raise RuntimeError("VOICE_DID_NOT_PREPARE")
        warmup_ms = round((time.monotonic() - started) * 1000)
        started = time.monotonic()
        window.start()
        if not window.running:
            raise RuntimeError("AUTO_DID_NOT_ARM")
        window._observe_frame(frame, 96)
        time.sleep(0.32)
        window._observe_frame(frame, 96)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and "COMPLETED" not in events and "ERROR" not in events:
            window.root.update()
            time.sleep(0.04)
        if "ERROR" in events:
            raise RuntimeError("SILENT_VOICE_FAILED")
        if "COMPLETED" not in events:
            raise RuntimeError("SILENT_VOICE_TIMEOUT")
        completed_before_cancel = event_log.count("COMPLETED")
        page = PageIdentity(uuid4(), 1, "quest_body", "c" * 64)
        cancel_token = RequestToken(uuid4(), uuid4(), 3, 3, "auto", page)
        if not window.reader.read_auto(
                "The lanterns are lit. The gate is open.", cancel_token,
                "bf_emma", OutputDevice("synthetic", "Synthetic"), silent=True):
            raise RuntimeError("CANCEL_PROBE_DID_NOT_START")
        time.sleep(0.08)
        cancel_started = time.monotonic()
        window.reader.stop(wait=True)
        canceled_ms = round((time.monotonic() - cancel_started) * 1000)
        if (window.reader.busy or not window.reader.ready
                or event_log.count("COMPLETED") != completed_before_cancel):
            raise RuntimeError("CANCEL_FENCE_FAILED")
        cancel_on_unit[0] = True
        audio_cancel_token = RequestToken(uuid4(), uuid4(), 4, 4, "auto", page)
        if not window.reader.read_auto(
                "The road is clear.", audio_cancel_token, "bf_emma",
                OutputDevice("synthetic", "Synthetic"), silent=True):
            raise RuntimeError("AUDIO_CANCEL_PROBE_DID_NOT_START")
        audio_deadline = time.monotonic() + 15
        while time.monotonic() < audio_deadline and window.reader.busy:
            window.root.update()
            time.sleep(0.03)
        if (window.reader.busy or cancel_on_unit[0]
                or event_log.count("COMPLETED") != completed_before_cancel):
            raise RuntimeError("AUDIO_CANCEL_FENCE_FAILED")
        return {"status": "PASSED", "scope": "SYNTHETIC_WINDOW_REAL_OCR_VOICE_SILENT_QT",
                "ocr_backend": "windows_media_ocr_dual_variant",
                "ocr_gate_passes": window.metrics["ocr_text_gate_passes"],
                "voice_warmup_ms": warmup_ms,
                "audio_submission_ms": round(events.get("UNIT_STARTED", 0) * 1000),
                "completed_ms": round(events["COMPLETED"] * 1000),
                "cancel_completion_ms": canceled_ms,
                "warm_worker_retained_after_cancel": window.reader.ready,
                "silent_audio_cancel_fenced": True,
                "audible_onset_measured": False, "game_capture": False,
                "physical_device_opened": False}
    finally:
        window.close()
        settings_dir.cleanup()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - never print worker, path or private OCR details
        allowed = {"AUTO_DID_NOT_ARM", "VOICE_DID_NOT_PREPARE", "SILENT_VOICE_FAILED",
                   "SILENT_VOICE_TIMEOUT", "CANCEL_PROBE_DID_NOT_START",
                   "CANCEL_FENCE_FAILED", "AUDIO_CANCEL_PROBE_DID_NOT_START",
                   "AUDIO_CANCEL_FENCE_FAILED"}
        code = str(exc) if type(exc) is RuntimeError and str(exc) in allowed else (
            "SYNTHETIC_AUTO_FLOW_FAILED")
        print(json.dumps({"status": "BLOCKED", "code": code}))
        raise SystemExit(2) from None
