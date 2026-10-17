"""Opt-in, observation-only LOTRO panel calibration; no automatic speech."""
# pyright: reportMissingImports=false
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk
from typing import cast

from PIL import Image, ImageTk

from lvc.platform.windows.lotro_probe_ui import (
    OcrProcessRunner,
    Viewport,
    perform_two_pass,
)
from lvc.platform.windows.lotro_user_probe import (
    EXPECTED_NATIVE_SHA256,
    MAX_FRAME_BYTES,
    NATIVE_PROBE,
    TESSERACT,
    Candidate,
    candidate_for_hwnd,
    decode_frame,
    eligible_windows,
    native_command,
    recognize,
    same_window_and_size,
)
from lvc.vision.auto_calibration import (
    Calibration,
    anchor_difference,
    anchor_signature,
    body_digest,
    load_profile,
    region,
    save_profile,
)
from lvc.vision.auto_observation import AutoObservation, Decision, Observation
from lvc.vision.binding import PixelRect
from lvc.vision.text_gate import TextDecision

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / ".audition" / "auto-calibration.json"
SUMMARY = ROOT / ".audition" / "auto-observation-summary.json"
ANCHOR_CANDIDATE_MAX_DIFFERENCE = 0.08  # Diagnostic only; no speech authority.
CAPTURE_INTERVAL_MS = 500

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint


def window_dpi(candidate: Candidate) -> int:
    value = int(user32.GetDpiForWindow(candidate.hwnd))
    if not 48 <= value <= 960:
        raise ValueError("WINDOW_DPI_UNAVAILABLE")
    return value


def capture_preflight() -> None:
    if not NATIVE_PROBE.is_file() or not TESSERACT.is_file():
        raise RuntimeError("CAPTURE_OR_TESSERACT_UNAVAILABLE")
    if hashlib.sha256(NATIVE_PROBE.read_bytes()).hexdigest() != EXPECTED_NATIVE_SHA256:
        raise RuntimeError("CAPTURE_HELPER_CHANGED")


class CaptureRunner:
    """One owned native child; Stop kills only that child, never the game."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._cancelled = threading.Event()

    def reset(self) -> None:
        self._cancelled.clear()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                process.kill()

    def capture(self, candidate: Candidate) -> tuple[Image.Image, int]:
        if self._cancelled.is_set():
            raise RuntimeError("CAPTURE_CANCELED")
        capture_preflight()
        if not same_window_and_size(candidate, candidate_for_hwnd(candidate.hwnd)):
            raise RuntimeError("WINDOW_IDENTITY_OR_SIZE_CHANGED")
        dpi = window_dpi(candidate)
        process = subprocess.Popen(native_command(candidate), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        with self._lock:
            self._process = process
            if self._cancelled.is_set() and process.poll() is None:
                process.kill()
        try:
            try:
                output, error = process.communicate(timeout=12)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise RuntimeError("CAPTURE_TIMEOUT") from exc
            if process.returncode != 0:
                reason = error.decode("ascii", "replace").strip()
                if "SELECTED_WINDOW_NOT_FOREGROUND" in reason:
                    raise RuntimeError("SELECTED_WINDOW_NOT_FOREGROUND")
                if "WINDOW_CHANGED" in reason or "IDENTITY_CHANGED" in reason:
                    raise RuntimeError("WINDOW_IDENTITY_CHANGED")
                raise RuntimeError("CAPTURE_UNAVAILABLE")
            if len(output) > MAX_FRAME_BYTES:
                raise RuntimeError("FRAME_TOO_LARGE")
            if (not same_window_and_size(candidate, candidate_for_hwnd(candidate.hwnd))
                    or window_dpi(candidate) != dpi):
                raise RuntimeError("WINDOW_GEOMETRY_CHANGED")
            return decode_frame(output), dpi
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None


class ObservationWindow:
    def __init__(self, *, hidden: bool = False) -> None:
        self.root = tk.Tk()
        if hidden:
            self.root.withdraw()
        self.root.title("Mithril Voices - LOTRO observation setup (speech off)")
        self.root.geometry("1100x850")
        self.root.minsize(750, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="Select a verified LOTRO window. No capture has started.")
        self.mode = tk.StringVar(value="body")
        self.window_choice = tk.StringVar()
        self.windows: dict[str, Candidate] = {}
        self.selected: Candidate | None = None
        self.frame: Image.Image | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.viewport: Viewport | None = None
        self.native_view = False
        self.anchor: PixelRect | None = None
        self.body: PixelRect | None = None
        self.profile: Calibration | None = None
        self.reference: Image.Image | None = None
        self.policy = AutoObservation()
        self.runner = CaptureRunner()
        self.ocr_runner: OcrProcessRunner | None = None
        self.results: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.busy = False
        self.closed = False
        self.capture_serial = 0
        self.started_ms = 0
        self.last_digest: str | None = None
        self.drag_start: tuple[float, float] | None = None
        self.ocr_busy = False
        self.deferred_ocr: tuple[Image.Image, tuple[int, str]] | None = None
        self.epoch = 0
        self.metrics: dict[str, int] = {}

        top = tk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)
        tk.Button(top, text="Find LOTRO windows", command=self.refresh).pack(side="left")
        self.picker = ttk.Combobox(top, textvariable=self.window_choice, state="readonly", width=72)
        self.picker.pack(side="left", padx=6, fill="x", expand=True)
        self.picker.bind("<<ComboboxSelected>>", self.choose_window)
        tk.Button(top, text="Capture open quest panel", command=self.calibration_capture).pack(side="left")

        controls = tk.Frame(self.root)
        controls.pack(fill="x", padx=8)
        tk.Radiobutton(controls, text="Mark static pane anchor", variable=self.mode,
                       value="anchor").pack(side="left")
        tk.Radiobutton(controls, text="Mark complete body text", variable=self.mode,
                       value="body").pack(side="left")
        tk.Button(controls, text="Save regions", command=self.save_regions).pack(side="left", padx=8)
        tk.Button(controls, text="Native-size refine", command=self.zoom_native).pack(side="left")
        tk.Button(controls, text="Whole window", command=self.overview).pack(side="left", padx=5)
        self.start_button = tk.Button(controls, text="Start observation (no speech)",
                                      command=self.start)
        self.start_button.pack(side="left")
        tk.Button(controls, text="Stop", command=self.stop).pack(side="left", padx=5)
        tk.Label(self.root, textvariable=self.status, anchor="w", wraplength=1000,
                 justify="left").pack(fill="x", padx=8, pady=5)
        self.instructions_label = tk.Label(self.root, text=(
            "Open a stock quest pane, capture once, then draw a static border/logo patch "
            "and a complete text crop. Switch back to LOTRO within 8 seconds of Capture/Start. "
            "No speech or gameplay control occurs."), wraplength=1050,
            justify="left")
        self.instructions_label.pack(anchor="w", padx=8)

        holder = tk.Frame(self.root)
        holder.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas = tk.Canvas(holder, background="#202020", cursor="crosshair")
        horizontal = tk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        vertical = tk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.candidate_label = tk.Label(
            self.root, text="Current OCR candidate and reason (memory only; never speech)")
        self.candidate_label.pack(anchor="w", padx=8)
        self.candidate_text = scrolledtext.ScrolledText(self.root, height=7, wrap="word")
        self.candidate_text.pack(fill="x", padx=8, pady=4)
        self.candidate_text.configure(state="disabled")
        self.root.after(100, self.poll)
        self.refresh()

    def set_text(self, value: str) -> None:
        self.candidate_text.configure(state="normal")
        self.candidate_text.delete("1.0", "end")
        self.candidate_text.insert("1.0", value)
        self.candidate_text.configure(state="disabled")

    def refresh(self) -> None:
        if self.running or self.busy:
            return
        try:
            candidates = eligible_windows()
        except OSError:
            self.status.set("LOTRO window inventory unavailable. Retry.")
            return
        self.windows = {}
        for index, candidate in enumerate(candidates, 1):
            label = (f"{index}. PID {candidate.pid} | "
                     f"{candidate.client_width}x{candidate.client_height} | "
                     f"{candidate.title[:80]}")
            self.windows[label] = candidate
        self.picker.configure(values=tuple(self.windows))
        self.window_choice.set("")
        self.selected = None
        self.status.set(f"{len(candidates)} verified retail LOTRO window(s). Select one; no capture yet.")

    def choose_window(self, _event: tk.Event | None = None) -> None:
        if self.running or self.busy:
            return
        self.selected = self.windows.get(self.window_choice.get())
        self.frame = None
        self.anchor = self.body = None
        self.profile = None
        self.reference = None
        self.set_text("")
        self.status.set("Window selected by verified native identity. Open a quest pane, then Capture.")

    def _capture(self, purpose: str) -> None:
        if self.selected is None or self.busy or self.closed:
            self.status.set("Select one verified LOTRO window first.")
            return
        candidate = self.selected
        self.busy = True
        self.runner.reset()
        self.capture_serial += 1
        serial = self.capture_serial
        self.status.set("Switch to the selected LOTRO window within 8 seconds; capturing one in-memory frame...")

        def work() -> None:
            try:
                result: object = self.runner.capture(candidate)
            except (OSError, ValueError, RuntimeError) as exc:
                result = str(exc) if str(exc) in {
                    "WINDOW_IDENTITY_OR_SIZE_CHANGED", "WINDOW_DPI_UNAVAILABLE",
                    "SELECTED_WINDOW_NOT_FOREGROUND", "WINDOW_IDENTITY_CHANGED",
                    "WINDOW_GEOMETRY_CHANGED", "CAPTURE_UNAVAILABLE", "CAPTURE_TIMEOUT",
                    "CAPTURE_HELPER_CHANGED", "CAPTURE_OR_TESSERACT_UNAVAILABLE",
                    "FRAME_TOO_LARGE"} else "CAPTURE_FAILED"
            self.results.put((purpose, (serial, result)))

        threading.Thread(target=work, daemon=True).start()

    def calibration_capture(self) -> None:
        if self.running:
            self.stop()
        self._capture("calibration")

    def _show_frame(self, frame: Image.Image, *, native: bool = False) -> None:
        self.native_view = native
        scale = 1.0 if native else min(1.0, 1050 / frame.width, 590 / frame.height)
        self.viewport = Viewport(frame.width, frame.height, scale)
        shown = frame if native else frame.resize((round(frame.width * scale),
                                                    round(frame.height * scale)))
        self.photo = ImageTk.PhotoImage(shown, master=self.root)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, shown.width, shown.height))
        self._draw_rectangles()
        if native:
            center = self.body or self.anchor
            if center is not None:
                self.root.update_idletasks()
                left = center.x + center.width / 2 - self.canvas.winfo_width() / 2
                top = center.y + center.height / 2 - self.canvas.winfo_height() / 2
                self.canvas.xview_moveto(max(0.0, left / shown.width))
                self.canvas.yview_moveto(max(0.0, top / shown.height))

    def zoom_native(self) -> None:
        if self.frame is None or self.running:
            self.status.set("Capture an open panel before refining its crop.")
            return
        self._show_frame(self.frame, native=True)
        self.status.set("Native pixels: use scrollbars to pan; redraw exact body boundaries.")

    def overview(self) -> None:
        if self.frame is None or self.running:
            return
        self._show_frame(self.frame)
        self.status.set("Whole selected window. Draw a rough region or use Native-size refine.")

    def _draw_rectangles(self) -> None:
        self.canvas.delete("regions")
        if self.viewport is None:
            return
        for rect, color in ((self.anchor, "#ffca28"), (self.body, "#37c4ff")):
            if rect is not None:
                scale = self.viewport.scale
                self.canvas.create_rectangle(rect.x * scale, rect.y * scale,
                                             (rect.x + rect.width) * scale,
                                             (rect.y + rect.height) * scale,
                                             outline=color, width=3, tags="regions")

    def press(self, event: tk.Event) -> None:
        if self.frame is None or self.running:
            return
        self.drag_start = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def drag(self, event: tk.Event) -> None:
        if self.drag_start is None or self.frame is None or self.running:
            return
        self.canvas.delete("drawing")
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.create_rectangle(*self.drag_start, x, y, outline="white",
                                     width=2, tags="drawing")

    def release(self, event: tk.Event) -> None:
        if self.drag_start is None or self.viewport is None or self.running:
            return
        end = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        rect = self.viewport.crop(*self.drag_start, *end)
        self.drag_start = None
        self.canvas.delete("drawing")
        if rect is None:
            self.status.set("Draw a region of at least 20 x 20 frame pixels.")
            return
        if self.mode.get() == "anchor":
            self.anchor = rect
        else:
            self.body = rect
        self.profile = None
        self.reference = None
        self._draw_rectangles()
        self.status.set("Region marked. Mark the other region, then Save regions.")

    def save_regions(self) -> None:
        if (self.frame is None or self.selected is None or self.anchor is None
                or self.body is None or self.running):
            self.status.set("Capture an open panel and mark separate anchor and body regions first.")
            return
        try:
            dpi = window_dpi(self.selected)
            profile = Calibration(self.frame.width, self.frame.height,
                                  self.selected.client_width, self.selected.client_height,
                                  dpi, self.anchor, self.body)
            save_profile(PROFILE, profile)
            self.profile = profile
            self.reference = anchor_signature(self.frame, profile)
        except (OSError, ValueError) as exc:
            self.status.set(f"Cannot save regions: {exc}. Check overlap and crop size.")
            return
        self.status.set("Geometry-only regions saved. Anchor pixels stay in memory for this session. "
                        "Start observation, then return focus to LOTRO.")

    def start(self) -> None:
        if (self.running or self.busy or self.selected is None or self.profile is None
                or self.reference is None):
            self.status.set("Select a window, capture an open quest pane, and save regions first.")
            return
        current = candidate_for_hwnd(self.selected.hwnd)
        if not same_window_and_size(self.selected, current):
            self.status.set("Selected LOTRO window identity or size changed. Select and recalibrate.")
            return
        try:
            if window_dpi(self.selected) != self.profile.dpi:
                raise ValueError("DPI changed")
        except ValueError:
            self.status.set("Window DPI changed. Recalibrate before observation.")
            return
        self.running = True
        self.epoch += 1
        self.ocr_busy = False
        self.deferred_ocr = None
        self.metrics = {key: 0 for key in (
            "frames", "anchor_present", "anchor_absent", "body_changes",
            "confirmed_closes", "ocr_attempts", "ocr_text_gate_passes",
            "ocr_abstentions", "capture_failures")}
        self.started_ms = time.monotonic_ns() // 1_000_000
        binding = f"{self.selected.hwnd}:{self.selected.pid}:{self.selected.process_started_ticks}"
        self._arm_policy(binding)
        self.last_digest = None
        self.set_text("")
        # The calibration screenshot is no longer needed once the bounded
        # anchor signature and rectangle coordinates have been prepared.
        self.canvas.delete("all")
        self.photo = None
        self.frame = None
        self.viewport = None
        self._capture("observe")

    def stop(self) -> None:
        was_running = self.running
        self.running = False
        self.epoch += 1
        self.capture_serial += 1
        self.runner.cancel()
        self.busy = False
        if self.ocr_runner is not None:
            self.ocr_runner.cancel()
        self.ocr_busy = False
        self.ocr_runner = None
        self.deferred_ocr = None
        self.policy.stop()
        self.policy.auto_off()
        self._on_stop()
        if was_running:
            self._save_summary()
        self.status.set(self._stopped_status())

    def _save_summary(self) -> None:
        profile = self.profile
        if profile is None:
            return
        value = {"version": 1,
                 "elapsed_ms": max(0, time.monotonic_ns() // 1_000_000 - self.started_ms),
                 "frame": [profile.frame_width, profile.frame_height],
                 "dpi": profile.dpi, "metrics": self.metrics,
                 "contains_pixels_or_text": False}
        temporary = SUMMARY.with_name(f".{SUMMARY.name}.tmp")
        try:
            SUMMARY.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, SUMMARY)
        except OSError:
            self.status.set("Observation summary could not be saved; pixels/text were not written.")
        finally:
            temporary.unlink(missing_ok=True)

    def _observe_frame(self, frame: Image.Image, dpi: int) -> None:
        assert self.profile is not None and self.selected is not None
        if not self.profile.matches(frame, self.selected.client_width,
                                    self.selected.client_height, dpi):
            self.stop()
            self.profile = None
            self.reference = None
            self._on_calibration_invalidated()
            self.status.set("Frame size, client size, or DPI changed. Capture and recalibrate.")
            return
        reference = self.reference
        if reference is None:
            self.stop()
            return
        difference = anchor_difference(reference, frame, self.profile)
        present = difference <= ANCHOR_CANDIDATE_MAX_DIFFERENCE
        self.metrics["frames"] += 1
        self.metrics["anchor_present" if present else "anchor_absent"] += 1
        digest = body_digest(frame, self.profile) if present else None
        binding = f"{self.selected.hwnd}:{self.selected.pid}:{self.selected.process_started_ticks}"
        item = Observation(time.monotonic_ns() // 1_000_000 - self.started_ms,
                           binding, 1, True, present, digest)
        decision = self._policy_observe(item)
        if not self.running:
            return
        if "CLOSED" in decision.effects:
            self.metrics["confirmed_closes"] += 1
            self.deferred_ocr = None
            self.status.set(self._closed_status(difference))
            self.set_text("")
        elif not present:
            self.status.set(f"Anchor differs by {difference:.3f}; possible close or UI change. "
                            "No text is admitted.")
        elif "FENCE" in decision.effects:
            self.metrics["body_changes"] += 1
            self.deferred_ocr = None
            self.status.set("Candidate body changed; previous OCR invalidated. Settling 300 ms...")
            self.set_text("")
        elif decision.validation_token is not None:
            crop = region(frame, self.profile.body)
            if self.ocr_busy:
                self.deferred_ocr = crop, decision.validation_token
            else:
                self._recognize(crop, decision.validation_token)
        elif digest != self.last_digest:
            self.status.set("Candidate panel present; waiting for stable body pixels...")
        self.last_digest = digest

    def _recognize(self, body: Image.Image, token: tuple[int, str]) -> None:
        self.ocr_busy = True
        self.metrics["ocr_attempts"] += 1
        epoch = self.epoch
        runner = OcrProcessRunner()
        self.ocr_runner = runner
        self.status.set("Candidate stable. Running two local OCR passes before any text admission.")

        def work() -> None:
            try:
                decision, _, _ = perform_two_pass(body, recognize, runner, lambda: None)
                result: object = decision
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                result = "OCR_UNAVAILABLE"
            except Exception:  # noqa: BLE001 - never log captured text from a child error
                result = "OCR_FAILED"
            self.results.put(("ocr", (epoch, token, result)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self) -> None:
        if self.closed:
            return
        try:
            while True:
                purpose, payload = self.results.get_nowait()
                if purpose == "ocr":
                    epoch, token, result = cast(tuple[int, tuple[int, str], object], payload)
                    if epoch != self.epoch:
                        continue
                    self.ocr_busy = False
                    self.ocr_runner = None
                    if not self.running:
                        continue
                    if isinstance(result, TextDecision):
                        current = self.policy.can_accept_validation(token)
                        outcome = self._validated(token, result.accepted_text)
                        if not current:
                            self.status.set("OCR result became stale after a panel change; discarded.")
                            self.set_text("")
                        elif result.accepted_text is None:
                            self.metrics["ocr_abstentions"] += 1
                            self.status.set(f"OCR abstained: {result.reason}. Review/refine the crop.")
                            self.set_text(result.raw_text[:3000])
                        elif outcome.accepted_text is None:
                            self.status.set("OCR result became stale or held after Stop; no admission.")
                            self.set_text("")
                        else:
                            self.metrics["ocr_text_gate_passes"] += 1
                            self.status.set(self._accepted_status())
                            self.set_text(result.raw_text[:3000])
                    else:
                        self.metrics["ocr_abstentions"] += 1
                        self.status.set("Local OCR could not complete; no text admitted.")
                    if self.deferred_ocr is not None and self.running:
                        image, next_token = self.deferred_ocr
                        self.deferred_ocr = None
                        if self.policy.can_accept_validation(next_token):
                            self._recognize(image, next_token)
                    continue
                serial, result = cast(tuple[int, object], payload)
                if serial != self.capture_serial:
                    continue
                self.busy = False
                if isinstance(result, str):
                    if purpose == "observe":
                        self.metrics["capture_failures"] += 1
                        self.stop()
                    self.status.set(f"Capture stopped: {result}. Keep the exact selected window "
                                    "foreground and retry; reselect if it changed.")
                    continue
                frame, dpi = cast(tuple[Image.Image, int], result)
                if self._handle_extra_capture(purpose, frame, dpi):
                    pass
                elif purpose == "calibration":
                    self.frame = frame
                    self.anchor = self.body = None
                    self.profile = None
                    self.reference = None
                    try:
                        saved = load_profile(PROFILE)
                        if (self.selected is not None
                                and saved.matches(frame, self.selected.client_width,
                                                  self.selected.client_height, dpi)):
                            self.anchor, self.body = saved.anchor, saved.body
                    except (FileNotFoundError, OSError, ValueError):
                        pass
                    self._show_frame(frame)
                    self.status.set("Fresh selected-window frame. Yellow: anchor; blue: body. "
                                    "Check saved rectangles or draw both, then Save regions.")
                elif purpose == "observe" and self.running:
                    self._observe_frame(frame, dpi)
                    if self.running:
                        self.root.after(CAPTURE_INTERVAL_MS, lambda: self._capture("observe"))
        except queue.Empty:
            pass
        self._on_poll()
        self.root.after(100, self.poll)

    def close(self) -> None:
        if self.closed:
            return
        self.stop()
        self.closed = True
        self.frame = None
        self.reference = None
        self.set_text("")
        self._on_close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

    def _arm_policy(self, binding: str) -> None:
        self.policy = AutoObservation()
        self.policy.bind(binding, 1)
        self.policy.auto_on()

    def _policy_observe(self, item: Observation) -> Decision:
        return self.policy.observe(item)

    def _validated(self, token: tuple[int, str], text: str | None) -> Decision:
        return self.policy.validated(token, text)

    def _handle_extra_capture(self, _purpose: str, _frame: Image.Image,
                              _dpi: int) -> bool:
        return False

    def _on_stop(self) -> None:
        pass

    def _on_poll(self) -> None:
        pass

    def _on_close(self) -> None:
        pass

    def _accepted_status(self) -> str:
        return ("Two-pass OCR candidate passed its text gate. "
                "Detector is unqualified; automatic speech remains off.")

    def _on_calibration_invalidated(self) -> None:
        pass

    def _stopped_status(self) -> str:
        return "Observation stopped. No audio was generated or played."

    def _closed_status(self, difference: float) -> str:
        return (f"Candidate panel closed (anchor difference {difference:.3f}); "
                "watching for a new panel. Speech remains off.")


def main() -> int:
    if sys.platform != "win32":
        print("Windows-only observation tool.", file=sys.stderr)
        return 2
    if "--check" in sys.argv:
        try:
            capture_preflight()
            print(json.dumps({"status": "READY", "capture": "verified helper",
                              "ocr": "local Tesseract", "speech": "DISABLED"}))
            return 0
        except (OSError, RuntimeError):
            print('{"status":"BLOCKED","code":"PREREQUISITE_UNAVAILABLE"}')
            return 2
    if "--check-ui" in sys.argv:
        window = ObservationWindow(hidden=True)
        window.root.update_idletasks()
        window.close()
        print('{"status":"READY","ui":"constructed","capture_started":false}')
        return 0
    ObservationWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
