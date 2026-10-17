"""User-armed LOTRO quest narration with in-session detector controls.

Automatic speech requires one selected native LOTRO window, an explicitly
calibrated quest crop, two negative control captures and a selected speaker.
There is no unattended startup, global capture, network speech or saved text.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

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

from PIL import Image

from lvc.core import RequestToken
from lvc.platform.windows.lotro_observation_ui import (
    ROOT,
    ObservationWindow,
    anchor_difference,
    capture_preflight,
)
from lvc.platform.windows.manual_preferences import PreferencesStore
from lvc.platform.windows.manual_read import (
    AUDIO_PYTHON,
    TTS_PYTHON,
    VOICE_OPTIONS,
    OutputDevice,
    list_output_devices,
)
from lvc.platform.windows.resident_auto_read import ResidentAutoReader
from lvc.vision.auto_core_adapter import AutoCoreAdapter
from lvc.vision.auto_observation import Decision, Observation

MIN_NEGATIVE_DIFFERENCE = 0.16
SETTINGS = Path(os.environ.get("MITHRIL_AUTO_SETTINGS",
                               str(ROOT / ".audition" / "auto-preferences.json")))


class AutoNarrationWindow(ObservationWindow):
    def __init__(self, *, hidden: bool = False, silent: bool = False) -> None:
        super().__init__(hidden=hidden)
        self.root.title("Mithril Voices - automatic LOTRO quest narration")
        self.start_button.configure(text="Start automatic reading")
        self.instructions_label.configure(text=(
            "Capture and mark a stock quest pane, then capture closed and non-quest controls "
            "from the same selected window. Prepare voice, choose a speaker, and click Start. "
            "Accepted new quest pages can play through that speaker. Stop/Pause fences speech."))
        self.candidate_label.configure(text="Current local OCR candidate and reason (memory only)")
        self.silent = silent
        self.controls: dict[str, float] = {}
        self.bridge: AutoCoreAdapter | None = None
        self.reader = ResidentAutoReader()
        self.active_token: RequestToken | None = None
        self.pending_speech: tuple[RequestToken, str] | None = None
        self.last_validation_reason = ""
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
        controls.pack(fill="x", padx=8, pady=4, before=self.candidate_text)
        tk.Button(controls, text="Capture closed-pane control",
                  command=lambda: self.capture_control("closed-control")).pack(side="left")
        tk.Button(controls, text="Capture journal/non-quest control",
                  command=lambda: self.capture_control("journal-control")).pack(side="left", padx=5)
        tk.Label(controls, text="Voice").pack(side="left", padx=(12, 2))
        self.voice_picker = ttk.Combobox(controls, textvariable=self.voice_choice,
                                        values=tuple(self.voice_by_label),
                                        state="readonly", width=18)
        self.voice_picker.pack(side="left")
        tk.Button(controls, text="Prepare voice", command=self.prepare_voice).pack(
            side="left", padx=(4, 0))
        tk.Button(controls, text="Find speakers", command=self.refresh_devices).pack(
            side="left", padx=(12, 2))
        self.device_picker = ttk.Combobox(controls, textvariable=self.device_choice,
                                         state="readonly", width=42)
        self.device_picker.pack(side="left", fill="x", expand=True)
        tk.Button(controls, text="Pause", command=self.pause).pack(side="left", padx=5)
        tk.Label(self.root, text=(
            "Automatic speech is an in-session trial. After saving regions, capture both "
            "closed and non-quest controls from the same selected window. Start only after "
            "the controls pass; Stop fences speech and capture. No screenshot/text is saved."),
                 wraplength=1050, justify="left").pack(
                     anchor="w", padx=8, before=self.candidate_text)
        if issue:
            self.status.set(f"Auto preferences could not be loaded ({issue}). Choose voice and speaker.")
        if not hidden:
            self.refresh_devices()

    def choose_window(self, event: tk.Event | None = None) -> None:
        if self.running or self.busy:
            return
        super().choose_window(event)
        self.controls.clear()

    def save_regions(self) -> None:
        if self.running:
            return
        super().save_regions()
        if self.profile is not None:
            self.controls.clear()
            self.status.set("Regions saved. Capture closed-pane and non-quest controls next.")

    def capture_control(self, purpose: str) -> None:
        if self.running or self.profile is None or self.reference is None:
            self.status.set("Save quest regions before taking negative controls.")
            return
        self._capture(purpose)

    def _handle_extra_capture(self, purpose: str, frame: Image.Image, dpi: int) -> bool:
        if purpose not in {"closed-control", "journal-control"}:
            return False
        profile = self.profile
        reference = self.reference
        selected = self.selected
        if (profile is None or reference is None or selected is None
                or not profile.matches(frame, selected.client_width,
                                       selected.client_height, dpi)):
            self.controls.clear()
            self.status.set("Control geometry changed. Reselect and recalibrate.")
            return True
        difference = anchor_difference(reference, frame, profile)
        if difference < MIN_NEGATIVE_DIFFERENCE:
            self.controls.pop(purpose, None)
            self.status.set(f"Control differs by only {difference:.3f}; choose a more distinctive "
                            "quest-pane anchor and recapture the control.")
            return True
        self.controls[purpose] = difference
        self.status.set(f"{purpose} passed ({difference:.3f} difference). "
                        f"{len(self.controls)}/2 controls captured; speech remains off.")
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
        if set(self.controls) != {"closed-control", "journal-control"}:
            self.status.set("Capture both closed-pane and non-quest controls before Start.")
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
                            "Return focus to the game within 8 seconds.")

    def _arm_policy(self, binding: str) -> None:
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

    def _policy_observe(self, item: Observation) -> Decision:
        bridge = self.bridge
        if bridge is None:
            return Decision()
        outcome = bridge.observe(item)
        if any(effect.kind in {"fence", "cancel"} for effect in outcome.effects):
            self._fence_voice()
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
                self.status.set("Voice ready. Complete both controls, then Start automatic reading.")
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
        return "Two-pass OCR accepted the page; preparing the selected local voice."

    def _on_calibration_invalidated(self) -> None:
        self.controls.clear()

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
            capture_preflight()
            if not TTS_PYTHON.is_file() or not AUDIO_PYTHON.is_file():
                raise RuntimeError("VOICE_RUNTIME_UNAVAILABLE")
            print(json.dumps({"status": "READY", "capture": "selected native window",
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
