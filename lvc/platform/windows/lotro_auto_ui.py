"""User-armed LOTRO quest narration with in-session detector controls.

Automatic speech requires one selected native LOTRO window, an explicitly
calibrated quest crop, two negative control captures and a selected speaker.
There is no unattended startup, global capture, network speech or saved text.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from uuid import uuid4

from PIL import Image, ImageTk

from lvc.core import RequestToken
from lvc.platform.windows.auto_profile_store import load_saved, save_saved
from lvc.platform.windows.auto_windows_ocr import recognize_auto_crop
from lvc.platform.windows.lotro_observation_ui import (
    ROOT,
    ObservationWindow,
    StreamCaptureRunner,
    anchor_difference,
    capture_preflight,
)
from lvc.platform.windows.lotro_probe_ui import OcrCancelled, OcrProcessRunner
from lvc.platform.windows.lotro_user_probe import EXPECTED_STREAM_SHA256, STREAM_PROBE
from lvc.platform.windows.manual_preferences import PreferencesStore
from lvc.platform.windows.manual_read import (
    AUDIO_PYTHON,
    TTS_PYTHON,
    VOICE_OPTIONS,
    OutputDevice,
    list_output_devices,
)
from lvc.platform.windows.resident_auto_read import ResidentAutoReader
from lvc.platform.windows.windows_ocr import windows_ocr_preflight
from lvc.vision.auto_calibration import (
    Calibration,
    anchor_quality_issue,
    region,
    scene_fingerprint,
    selection_issue,
)
from lvc.vision.auto_core_adapter import AutoCoreAdapter
from lvc.vision.auto_observation import Decision, Observation
from lvc.vision.binding import PixelRect
from lvc.vision.panel_locator import PanelLocator, TemplatePanelLocator

MIN_NEGATIVE_DIFFERENCE = 0.16
SETTINGS = Path(os.environ.get("MITHRIL_AUTO_SETTINGS",
                               str(ROOT / ".audition" / "auto-preferences.json")))


class AutoNarrationWindow(ObservationWindow):
    def __init__(self, *, hidden: bool = False, silent: bool = False) -> None:
        super().__init__(hidden=hidden)
        self.runner = StreamCaptureRunner()
        self.root.title("Mithril Voices - automatic LOTRO quest narration")
        self.mode.set("anchor")
        self.capture_button.configure(text="1. Capture open quest window")
        self.anchor_button.configure(text="2. Yellow: small border detail")
        self.body_button.configure(text="3. Blue: all dialogue words")
        self.save_button.configure(text="4. Save yellow + blue boxes")
        self.start_button.configure(text="Start automatic reading")
        self.instructions_label.configure(text=(
            "Select LOTRO, then capture an open quest window. Draw YELLOW around a small "
            "unchanging corner or border detail, outside the words. Switch to BLUE and draw "
            "around every dialogue line inside the pane. Both boxes remain visible; dragging "
            "again replaces only the selected color. Save, then take the two safety samples "
            "described below. Prepare voice and select a speaker before Start."))
        self.candidate_text.configure(height=3)
        self.setup_step = tk.StringVar()
        tk.Label(self.root, textvariable=self.setup_step, wraplength=1050,
                 justify="left", anchor="w", fg="#164b76").pack(
                     fill="x", padx=8, pady=3, before=self.candidate_text)
        self.candidate_label.configure(text="Recognized dialogue preview (this session only)")
        self.silent = silent
        self.controls: dict[str, float] = {}
        self.panel_locator: PanelLocator | None = None
        self.preview_anchor: PixelRect | None = None
        self.bridge: AutoCoreAdapter | None = None
        self.reader = ResidentAutoReader()
        self.active_token: RequestToken | None = None
        self.pending_speech: tuple[RequestToken, str] | None = None
        self.last_validation_reason = ""
        self.saved_load_reason = ""
        self.positive_scene: bytes | None = None
        self.control_scenes: dict[str, bytes] = {}
        self.control_crop_photo: ImageTk.PhotoImage | None = None
        self.devices: dict[str, OutputDevice] = {}
        self.device_results: queue.Queue[object] = queue.Queue()
        self.settings = PreferencesStore(SETTINGS,
                                         tuple(option.voice_id for option in VOICE_OPTIONS))
        preferences, issue = self.settings.load()
        self.preferences = preferences
        self.voice_by_label = {option.label: option.voice_id for option in VOICE_OPTIONS}
        self.voice_choice = tk.StringVar(value=next(
            (option.label for option in VOICE_OPTIONS
             if option.voice_id == preferences.voice_id), VOICE_OPTIONS[0].label))
        self.device_choice = tk.StringVar()
        self.active_voice: str | None = None
        self.active_device: OutputDevice | None = None

        controls = tk.Frame(self.root)
        controls.pack(fill="x", padx=8, pady=2, before=self.candidate_text)
        self.closed_button = tk.Button(
            controls, text="5. Capture with quest closed",
            command=lambda: self.capture_control("closed-control"))
        self.closed_button.pack(side="left")
        self.other_button = tk.Button(
            controls, text="6. Capture journal or inventory",
            command=lambda: self.capture_control("journal-control"))
        self.other_button.pack(side="left", padx=5)
        voice_controls = tk.Frame(self.root)
        voice_controls.pack(fill="x", padx=8, pady=2, before=self.candidate_text)
        tk.Label(voice_controls, text="Voice").pack(side="left", padx=(0, 2))
        self.voice_picker = ttk.Combobox(voice_controls, textvariable=self.voice_choice,
                                        values=tuple(self.voice_by_label),
                                        state="readonly", width=18)
        self.voice_picker.pack(side="left")
        tk.Button(voice_controls, text="Prepare voice", command=self.prepare_voice).pack(
            side="left", padx=(4, 0))
        tk.Button(voice_controls, text="Find speakers", command=self.refresh_devices).pack(
            side="left", padx=(12, 2))
        self.device_picker = ttk.Combobox(voice_controls, textvariable=self.device_choice,
                                         state="readonly", width=42)
        self.device_picker.pack(side="left", fill="x", expand=True)
        tk.Button(voice_controls, text="Pause", command=self.pause).pack(side="left", padx=5)
        tk.Label(self.root, text=(
            "Safety samples: first close the quest window and capture the game. Then open a "
            "journal or inventory (with no quest dialogue) and capture again. The app checks "
            "that the yellow quest detail is absent in both. No speech starts during setup. "
            "No screenshot or recognized words are saved."),
                 wraplength=1050, justify="left").pack(
                     anchor="w", padx=8, before=self.candidate_text)
        self.control_preview_title = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.control_preview_title,
                 anchor="w").pack(fill="x", padx=8, before=self.candidate_text)
        self.control_preview = tk.Label(self.root)
        self.control_preview.pack(anchor="w", padx=8, before=self.candidate_text)
        preview_controls = tk.Frame(self.root)
        preview_controls.pack(fill="x", padx=8, pady=2, before=self.candidate_text)
        tk.Button(preview_controls, text="Preview moved panel (speech off)",
                  command=self.preview_panel).pack(side="left")
        tk.Label(preview_controls, text=(
            "Preview cannot read aloud; speech still uses the saved yellow and blue boxes."),
            anchor="w").pack(side="left", padx=8)
        if issue:
            self.status.set(f"Auto preferences could not be loaded ({issue}). Choose voice and speaker.")
        self._update_setup()
        if not hidden:
            self.refresh_devices()

    def _update_setup(self) -> None:
        """Keep the next action visible without hiding either saved selection."""
        if self.running:
            step = ("Automatic reading is armed for the selected LOTRO window. "
                    "A steady yellow Windows capture outline may remain until Stop. "
                    "Pause or Stop fences the current page and audio.")
        elif self.selected is None:
            step = "Next: select the LOTRO window, then capture an open quest window."
        elif self.frame is None and self.profile is None:
            step = "Next: open a quest in LOTRO, click Capture, and return to the game."
        elif self.profile is None:
            issue = selection_issue(self.frame, self.anchor, self.body)
            if ((issue is None or issue.startswith("Switch to the blue"))
                    and self.frame is not None and self.anchor is not None
                    and self.anchor.inside(*self.frame.size)
                    and self.anchor.width >= 20 and self.anchor.height >= 20
                    and self.anchor.width * self.anchor.height <= 250_000):
                issue = anchor_quality_issue(self.frame, self.anchor) or issue
            step = (f"Next: {issue}" if issue else
                    "Both boxes are kept. Check their edges, then Save. Redraw either color "
                    "to correct just that box.")
        elif "closed-control" not in self.controls:
            step = ("Boxes saved. Next: close the quest window in LOTRO, click "
                    "'Capture with quest closed', then return to the game.")
        elif "journal-control" not in self.controls:
            step = ("Quest-closed sample passed. Next: show a journal or inventory with "
                    "no quest dialogue, click its Capture button, and return to the game.")
        else:
            step = ("Both safety samples passed. Choose the exact speaker, click Prepare "
                    "voice and wait for Voice ready, then Start automatic reading.")
        self.setup_step.set(step)
        available = "normal" if self.profile is not None and not self.running else "disabled"
        self.closed_button.configure(state=available)
        self.other_button.configure(state=available)
        self.start_button.configure(
            state="normal" if (not self.running and self.profile is not None
                               and self.positive_scene is not None
                               and set(self.controls) == {"closed-control", "journal-control"}
                               and set(self.control_scenes) ==
                               {"closed-control", "journal-control"}) else "disabled")

    def choose_window(self, event: tk.Event | None = None) -> None:
        if self.running or self.busy:
            return
        super().choose_window(event)
        self.controls.clear()
        self.panel_locator = None
        self.preview_anchor = None
        self.saved_load_reason = ""
        self.positive_scene = None
        self.control_scenes.clear()
        self._clear_control_preview()
        self._update_setup()

    def _save_calibration(self, profile: Calibration) -> None:
        if self.selected is None or self.frame is None:
            raise ValueError("CALIBRATION_BINDING_INVALID")
        save_saved(self.selected, self.frame, profile.dpi, profile)

    def _load_calibration(self, frame: Image.Image, dpi: int) -> Calibration | None:
        if self.selected is None:
            return None
        saved, self.saved_load_reason = load_saved(self.selected, frame, dpi)
        return saved

    def _calibration_status(self, loaded: bool) -> str:
        if loaded:
            source = ("Previous build's" if self.saved_load_reason == "PREVIOUS_BOXES_LOADED"
                      else "Saved")
            return (f"{source} yellow and blue boxes loaded for this window size. "
                    "Check them against the current quest and UI scale; redraw if needed, "
                    "then Save. Take both safety samples again before Start.")
        if self.saved_load_reason == "SAVED_BOXES_INVALID":
            return ("Saved boxes could not be read safely. Draw yellow and blue again, "
                    "then Save; speech stays off.")
        return ("No saved boxes match this game installation, capture size and DPI. "
                "Draw yellow and blue, then Save. Both safety samples are required.")

    def release(self, event: tk.Event) -> None:
        before = self.anchor, self.body
        super().release(event)
        if before != (self.anchor, self.body):
            self.controls.clear()
            self.panel_locator = None
            self.preview_anchor = None
            self.positive_scene = None
            self.control_scenes.clear()
            self._clear_control_preview()
        self._update_setup()

    def calibration_capture(self) -> None:
        self.mode.set("anchor")
        self.controls.clear()
        self.panel_locator = None
        self.preview_anchor = None
        self.positive_scene = None
        self.control_scenes.clear()
        self._clear_control_preview()
        self._update_setup()
        super().calibration_capture()

    def save_regions(self) -> bool:
        if self.running:
            return False
        if (self.frame is not None and self.anchor is not None
                and selection_issue(self.frame, self.anchor, self.body) is None):
            issue = anchor_quality_issue(self.frame, self.anchor)
            if issue is not None:
                self.profile = None
                self.reference = None
                self.positive_scene = None
                self.control_scenes.clear()
                self.controls.clear()
                self.status.set(issue)
                self._update_setup()
                return False
        saved = super().save_regions()
        if saved and self.profile is not None:
            assert self.frame is not None
            self.positive_scene = scene_fingerprint(self.frame)
            self.control_scenes.clear()
            self._clear_control_preview()
            self.controls.clear()
            self.panel_locator = None
            self.preview_anchor = None
            if self.frame is not None:
                try:
                    self.panel_locator = TemplatePanelLocator(self.frame, self.profile)
                except ValueError:
                    pass
            self.status.set("Yellow and blue boxes saved for this game installation and window "
                            "size. Next capture the quest-closed and "
                            "journal/inventory safety samples. Moved-window preview cannot "
                            "start speech.")
        self._update_setup()
        return saved

    def preview_panel(self) -> None:
        if self.running or self.panel_locator is None:
            self.status.set("Save a small detailed yellow border box and blue dialogue box "
                            "before previewing a moved quest window.")
            return
        self._capture("panel-preview")

    def capture_control(self, purpose: str) -> None:
        if (self.running or self.profile is None or self.reference is None
                or self.positive_scene is None):
            self.status.set("Save the separate yellow border box and blue dialogue box "
                            "before taking safety samples.")
            return
        self._capture(purpose)

    def _clear_control_preview(self) -> None:
        self.control_preview_title.set("")
        self.control_preview.configure(image="")
        self.control_crop_photo = None

    def _show_control_crop(self, frame: Image.Image, profile: Calibration,
                           purpose: str) -> None:
        crop = region(frame, profile.anchor).convert("RGB")
        scale = min(3.0, 320 / crop.width, 120 / crop.height)
        shown = crop.resize((max(1, round(crop.width * scale)),
                             max(1, round(crop.height * scale))))
        self.control_crop_photo = ImageTk.PhotoImage(shown, master=self.root)
        self.control_preview.configure(image=self.control_crop_photo)
        label = ("quest-closed" if purpose == "closed-control" else "journal/inventory")
        self.control_preview_title.set(
            f"Yellow area in the latest {label} capture (local preview only):")

    def _handle_extra_capture(self, purpose: str, frame: Image.Image, dpi: int) -> bool:
        if purpose == "panel-preview":
            locator = self.panel_locator
            profile = self.profile
            selected = self.selected
            if (locator is None or profile is None or selected is None
                    or not profile.matches(frame, selected.client_width,
                                           selected.client_height, dpi)):
                self.preview_anchor = None
                self.status.set("Panel preview suspended: window geometry or DPI changed.")
                return True
            finding = locator.locate(frame, self.preview_anchor)
            if (finding.reason != "FOUND" or finding.anchor is None
                    or finding.body is None or finding.scale is None):
                self.preview_anchor = None
                self.status.set(f"Panel preview abstained: {finding.reason.lower()} "
                                f"(visual similarity {finding.similarity:.3f}). Speech stays off.")
                return True
            self.preview_anchor = finding.anchor
            self._show_frame(frame)
            # A preview must never become the source for Save/controls.
            self.frame = None
            self.canvas.delete("regions")
            viewport = self.viewport
            if viewport is not None:
                for rect, color in ((finding.panel, "#ffcc44"), (finding.body, "#37c4ff")):
                    if rect is not None:
                        scale = viewport.scale
                        self.canvas.create_rectangle(
                            rect.x * scale, rect.y * scale,
                            (rect.x + rect.width) * scale, (rect.y + rect.height) * scale,
                            outline=color, width=3, tags="preview")
            self.status.set(f"Provisional panel extent and body box; visual similarity "
                            f"{finding.similarity:.3f}, scale {finding.scale:.2f}. "
                            "Check the boxes. This preview does not authorize speech.")
            return True
        if purpose not in {"closed-control", "journal-control"}:
            return False
        profile = self.profile
        reference = self.reference
        selected = self.selected
        if self.positive_scene is None:
            self.controls.clear()
            self.status.set("Capture an open quest pane and Save its boxes before safety samples.")
            self._update_setup()
            return True
        if (profile is None or reference is None or selected is None
                or not profile.matches(frame, selected.client_width,
                                       selected.client_height, dpi)):
            self.controls.clear()
            self.status.set("Window size or DPI changed during the safety sample. "
                            "Reselect the window and mark both boxes again.")
            self._update_setup()
            return True
        self._show_control_crop(frame, profile, purpose)
        scene = scene_fingerprint(frame)
        if scene == self.positive_scene or scene in self.control_scenes.values():
            self.controls.pop(purpose, None)
            self.control_scenes.pop(purpose, None)
            self.status.set("This safety capture looks identical to an earlier setup scene. "
                            "Check the small yellow-area preview, change to the requested "
                            "game view, then capture once more. Speech stays off.")
            self._update_setup()
            return True
        difference = anchor_difference(reference, frame, profile)
        if difference < MIN_NEGATIVE_DIFFERENCE:
            self.controls.pop(purpose, None)
            self.control_scenes.pop(purpose, None)
            self.status.set(
                f"The game scene changed, but the yellow area still looks like the quest "
                f"sample (difference {difference:.3f}; needs {MIN_NEGATIVE_DIFFERENCE:.2f}). "
                "Check the small preview above. If the quest pane is absent there, this "
                "yellow area is too generic; keep blue and redraw yellow around a visible "
                "quest-pane corner or line, then Save. Speech stays off.")
            self._update_setup()
            return True
        self.controls[purpose] = difference
        self.control_scenes[purpose] = scene
        label = ("Quest-closed sample" if purpose == "closed-control"
                 else "Journal/inventory sample")
        self.status.set(f"{label} passed. {len(self.controls)}/2 safety samples captured; "
                        "speech remains off.")
        self._update_setup()
        return True

    def refresh_devices(self) -> None:
        if self.running:
            return
        self.status.set("Checking local audio outputs; no playback started.")

        def work() -> None:
            try:
                result: object = list_output_devices()
            except Exception:  # noqa: BLE001 - never place local paths in UI status
                result = "AUDIO_DEVICE_LIST_FAILED"
            self.device_results.put(result)

        threading.Thread(target=work, daemon=True).start()

    def prepare_voice(self) -> None:
        if self.running:
            return
        voice = self.voice_by_label.get(self.voice_choice.get())
        if voice is None or not self.reader.prepare(voice):
            self.status.set("Voice could not start warming. Reopen this session if changing voice.")
            return
        self.status.set("Preparing the selected offline voice. Wait for Voice ready before Start.")

    def start(self) -> None:
        if (self.positive_scene is None
                or set(self.controls) != {"closed-control", "journal-control"}
                or set(self.control_scenes) != {"closed-control", "journal-control"}):
            self.status.set("Capture with the quest closed and then capture a journal or "
                            "inventory before Start.")
            return
        voice = self.voice_by_label.get(self.voice_choice.get())
        device = self.devices.get(self.device_choice.get())
        if voice is None or device is None:
            self.status.set("Choose an available local voice and exact speaker first.")
            return
        if not self.reader.ready or self.reader.voice != voice:
            self.status.set("Click Prepare voice and wait for Voice ready before Start.")
            return
        self.active_voice, self.active_device = voice, device
        try:
            self.settings.save(self.preferences.voice(voice).device(
                device.id, device.description))
        except (OSError, ValueError):
            self.status.set("Auto preferences could not be saved. Fix local settings before Start.")
            return
        super().start()
        if self.running:
            self.status.set("Automatic reading armed for the selected LOTRO window. "
                            "Return focus to the game within 8 seconds. Windows may show "
                            "one steady yellow capture outline until Stop.")

    def _arm_policy(self, binding: str) -> None:
        self.runner.streaming = True
        self.bridge = AutoCoreAdapter(uuid4(), binding, 1, profile_qualified=True)
        result = self.bridge.enable(0)
        if result.reason != "WATCHING":
            raise RuntimeError("AUTO_CORE_NOT_ARMED")
        self.policy = self.bridge.observation
        self.pending_speech = None
        self.active_token = None
        self.last_validation_reason = ""

    def _fence_voice(self) -> None:
        self.pending_speech = None
        self.active_token = None
        self.reader.stop()

    def _recognize(self, body: Image.Image, token: tuple[int, str]) -> None:
        """Windows OCR admission on a stable, separately identified body crop."""
        self.ocr_busy = True
        self.metrics["ocr_attempts"] += 1
        epoch = self.epoch
        runner = OcrProcessRunner()
        self.ocr_runner = runner
        self.status.set("Stable panel body: checking two local Windows OCR image variants.")

        def work() -> None:
            try:
                result: object = recognize_auto_crop(body, runner)
            except (OcrCancelled, OSError, ValueError, RuntimeError):
                result = "WINDOWS_OCR_UNAVAILABLE_OR_CANCELED"
            except Exception:  # noqa: BLE001 - never expose crop or OCR text in status
                result = "WINDOWS_OCR_FAILED"
            self.results.put(("ocr", (epoch, token, result)))

        threading.Thread(target=work, daemon=True).start()

    def _policy_observe(self, item: Observation) -> Decision:
        bridge = self.bridge
        if bridge is None:
            return Decision()
        outcome = bridge.observe(item)
        if any(effect.kind in {"fence", "cancel"} for effect in outcome.effects):
            self._fence_voice()
            if self.ocr_runner is not None:
                self.ocr_runner.cancel()
        if outcome.reason == "SUSPENDED":
            self.stop()
            self.status.set("Detector or window binding suspended. Recalibrate before Start.")
            return Decision(("SUSPENDED",))
        if outcome.reason == "CLOSED":
            return Decision(("CLOSED",))
        if outcome.validation is not None:
            return Decision(("VALIDATE",), outcome.validation.observation_token)
        if any(effect.kind == "fence" for effect in outcome.effects):
            return Decision(("FENCE",))
        return Decision()

    def _validated(self, token: tuple[int, str], text: str | None) -> Decision:
        bridge = self.bridge
        if bridge is None:
            return Decision()
        outcome = bridge.validated(token, text, time.monotonic_ns() // 1_000_000 - self.started_ms)
        self.last_validation_reason = outcome.reason
        if outcome.synthesis_text is None:
            return Decision()
        synthesis = next((effect.token for effect in outcome.effects
                          if effect.kind == "synthesize"), None)
        if synthesis is None:
            return Decision()
        self.pending_speech = synthesis, outcome.synthesis_text
        return Decision(("READ",), accepted_text=outcome.synthesis_text)

    def _on_poll(self) -> None:
        self._update_setup()
        while True:
            try:
                result = self.device_results.get_nowait()
            except queue.Empty:
                break
            if isinstance(result, str):
                self.status.set("Could not list local speakers. Check the Qt runtime.")
                continue
            assert isinstance(result, tuple)
            self.devices = {f"{item.description} [{item.id[:18]}]": item
                            for item in result}
            self.device_picker.configure(values=tuple(self.devices))
            chosen = next((label for label, item in self.devices.items()
                           if item.id == self.preferences.device_id
                           and item.description == self.preferences.device_description), "")
            self.device_choice.set(chosen)
            if not chosen:
                self.status.set("Choose the exact speaker for automatic reading.")
        while True:
            try:
                event, code = self.reader.events.get_nowait()
            except queue.Empty:
                break
            if event == "VOICE_READY":
                self.status.set("Voice ready. Complete both safety samples, then Start automatic reading.")
                continue
            if self.active_token is None or not self.running:
                if event == "ERROR":
                    self.status.set(f"Local voice unavailable: {code}.")
                continue
            if event == "ERROR":
                self.stop()
                self.status.set(f"Automatic reading stopped: {code}. Check the local voice/runtime.")
            elif event == "COMPLETED":
                self.status.set("Current page completed. Watching for a new page.")
                self.active_token = None
            elif event in {"SYNTHESIZING", "PREPARING_AUDIO", "UNIT_STARTED"}:
                self.status.set(f"Current page: {event.lower().replace('_', ' ')}.")
        pending = self.pending_speech
        bridge = self.bridge
        if (self.running and pending is not None and bridge is not None
                and not self.reader.busy and self.active_device is not None
                and self.active_voice is not None):
            token, text = pending
            self.pending_speech = None
            if bridge.state.synthesis == token:
                if self.reader.read_auto(text, token, self.active_voice,
                                         self.active_device, silent=self.silent):
                    self.active_token = token
                    self.status.set("Accepted quest page sent to warm local voice worker.")
                else:
                    self.status.set("Local voice unavailable; Stop and prepare voice again.")
                    self.stop()

    def pause(self) -> None:
        if self.running:
            self.stop()
            self.status.set("Paused and fenced. Start again to arm a new observation session.")

    def _on_stop(self) -> None:
        if hasattr(self, "reader"):
            self._fence_voice()
        self.bridge = None

    def _on_close(self) -> None:
        if hasattr(self, "reader"):
            self.reader.close()

    def _accepted_status(self) -> str:
        return "Windows OCR variants agreed; preparing the selected local voice."

    def _ocr_backend(self) -> str:
        return "windows_media_ocr_dual_variant"

    def _on_calibration_invalidated(self) -> None:
        self.positive_scene = None
        self.control_scenes.clear()
        self._clear_control_preview()
        self.controls.clear()
        self.panel_locator = None
        self.preview_anchor = None
        self._update_setup()

    def _stopped_status(self) -> str:
        return "Automatic capture and speech stopped. The selected window remains available."

    def _closed_status(self, difference: float) -> str:
        return (f"Candidate quest pane closed (anchor difference {difference:.3f}); "
                "prior speech canceled; watching for a new panel.")

    def _held_status(self) -> str:
        if self.last_validation_reason == "DUPLICATE_TEXT":
            return "Same quest words detected again; duplicate narration suppressed."
        return "OCR result is stale or held; no new narration started."


def main() -> int:
    if sys.platform != "win32":
        return 2
    if "--check" in sys.argv:
        try:
            capture_preflight(require_tesseract=False)
            if (not STREAM_PROBE.is_file() or
                    hashlib.sha256(STREAM_PROBE.read_bytes()).hexdigest()
                    != EXPECTED_STREAM_SHA256):
                raise RuntimeError("STREAM_CAPTURE_UNAVAILABLE")
            windows_ocr_preflight()
            if not TTS_PYTHON.is_file() or not AUDIO_PYTHON.is_file():
                raise RuntimeError("VOICE_RUNTIME_UNAVAILABLE")
            print(json.dumps({"status": "READY", "capture": "selected native window",
                              "ocr_backend": "windows_media_ocr_dual_variant",
                              "speech": "user-armed", "game_tested": False}))
            return 0
        except (OSError, RuntimeError):
            print('{"status":"BLOCKED","code":"PREREQUISITE_UNAVAILABLE"}')
            return 2
    if "--check-ui" in sys.argv:
        window = AutoNarrationWindow(hidden=True, silent=True)
        window.root.update_idletasks()
        window.close()
        print('{"status":"READY","ui":"constructed","capture_started":false}')
        return 0
    AutoNarrationWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
