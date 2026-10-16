"""Local, single-frame LOTRO OCR preview. Pixels and OCR stay in memory."""
from __future__ import annotations

import queue
import statistics
import subprocess
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import scrolledtext, ttk
from typing import cast

from PIL import Image, ImageTk

from lvc.platform.windows.manual_read import (
    MAX_TEXT_CHARS,
    ManualReadController,
    ManualReadError,
    OutputDevice,
    list_output_devices,
)
from lvc.platform.windows.windows_ocr import recognize_windows
from lvc.vision.binding import PixelRect
from lvc.vision.comparison import ReviewState, disagreement_spans
from lvc.vision.text_gate import OcrPass, TextDecision, decide_text

MAX_OCR_PIXELS = 2_000_000


class OcrCancelled(Exception):
    """A user canceled the current local OCR attempt."""


class OcrProcessRunner:
    """Run one Tesseract child at a time, with bounded time and prompt cancellation."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._active: subprocess.Popen[bytes] | None = None

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            if self._active is not None and self._active.poll() is None:
                try:
                    self._active.kill()
                except OSError:
                    pass  # The child may have exited between poll and kill.

    def __call__(self, command: list[str], *, input: bytes,
                 capture_output: bool, timeout: float,
                 check: bool) -> subprocess.CompletedProcess[bytes]:
        if not capture_output or check or timeout <= 0:
            raise ValueError("OCR runner requires bounded captured output")
        if self.cancelled.is_set():
            raise OcrCancelled()
        child = subprocess.Popen(command, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with self._lock:
                self._active = child
                if self.cancelled.is_set() and child.poll() is None:
                    child.kill()
            try:
                stdout, stderr = child.communicate(input=input,
                                                   timeout=min(self.timeout, timeout))
            except subprocess.TimeoutExpired as exc:
                child.kill()
                child.communicate()
                raise RuntimeError("OCR_TIMEOUT") from exc
            if self.cancelled.is_set():
                raise OcrCancelled()
            return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
        finally:
            if child.poll() is None:
                try:
                    child.kill()
                except OSError:
                    pass
                child.communicate()
            with self._lock:
                if self._active is child:
                    self._active = None


@dataclass(frozen=True)
class Viewport:
    frame_width: int
    frame_height: int
    scale: float

    def crop(self, x1: float, y1: float, x2: float, y2: float) -> PixelRect | None:
        if self.scale <= 0:
            return None
        left = max(0, min(self.frame_width, round(min(x1, x2) / self.scale)))
        top = max(0, min(self.frame_height, round(min(y1, y2) / self.scale)))
        right = max(0, min(self.frame_width, round(max(x1, x2) / self.scale)))
        bottom = max(0, min(self.frame_height, round(max(y1, y2) / self.scale)))
        rect = PixelRect(left, top, right - left, bottom - top)
        return rect if rect.width >= 20 and rect.height >= 20 and rect.inside(
            self.frame_width, self.frame_height) else None


def gate_explanation(decision: TextDecision, first: OcrPass, second: OcrPass) -> str:
    """Explain the existing fail-closed gate without changing its decision."""
    if decision.reason == "ACCEPTED":
        return "Two OCR passes agree and meet the word-confidence gate."
    if decision.reason == "INCOMPLETE_OR_INVALID_WORD":
        if any(word.clipped for result in (first, second) for word in result.words):
            return "A detected word touches the crop edge. Widen the crop and retry."
        return "At least one OCR pass contains an incomplete or invalid word. Refine the crop."
    if decision.reason == "LOW_OCR_CONFIDENCE":
        def scores(result: OcrPass) -> str:
            values = [word.confidence for word in result.words
                      if any(character.isalnum() for character in word.text)]
            if not values:
                return "no alphanumeric words"
            return f"min {min(values):.1f}, median {statistics.median(values):.1f}"

        def weakest(result: OcrPass) -> str:
            ranked = sorted(((index, word) for index, word in enumerate(result.words, 1)
                             if any(character.isalnum() for character in word.text)),
                            key=lambda item: item[1].confidence)
            below_floor = [item for item in ranked if item[1].confidence < 40]
            selected = below_floor[:5] if below_floor else ranked[:2]
            if not selected:
                return "no alphanumeric word guesses"
            details = "; ".join(
                f"#{index} recognized as {word.text[:48]!r} ({word.confidence:.1f})"
                for index, word in selected)
            if len(below_floor) > len(selected):
                details += f"; {len(below_floor) - len(selected)} more below 40"
            return details

        return (f"Pass 1: {scores(first)}; pass 2: {scores(second)}. "
                "Each word needs at least 40 and each pass median at least 85.\n"
                f"Pass 1 weakest OCR guesses: {weakest(first)}.\n"
                f"Pass 2 weakest OCR guesses: {weakest(second)}. "
                "These are recognized guesses, not confirmed game text.")
    if decision.reason == "OCR_PASS_DISAGREEMENT":
        return "The two OCR passes disagree on at least one word."
    if decision.reason == "EMPTY_OCR_OUTPUT":
        return "One or both OCR passes found no complete words."
    return "The crop or OCR result could not be accepted."


def crop_is_bounded(crop: PixelRect) -> bool:
    return 20 <= crop.width and 20 <= crop.height and crop.width * crop.height <= MAX_OCR_PIXELS


def perform_two_pass(body: Image.Image, recognize: Callable[..., OcrPass],
                     runner: OcrProcessRunner,
                     on_second: Callable[[], None]) -> tuple[TextDecision, OcrPass, OcrPass]:
    first = recognize(body, alternative=False, runner=runner)
    if runner.cancelled.is_set():
        raise OcrCancelled()
    on_second()
    second = recognize(body, alternative=True, runner=runner)
    if runner.cancelled.is_set():
        raise OcrCancelled()
    return decide_text(first, second, qualified_region=True), first, second


@dataclass(frozen=True)
class EngineComparison:
    tesseract: TextDecision | None
    first: OcrPass | None
    second: OcrPass | None
    windows_text: str | None
    tesseract_error: str | None = None
    windows_error: str | None = None

    @property
    def tesseract_text(self) -> str | None:
        return self.first.raw_text if self.first is not None else None


def perform_comparison(body: Image.Image, recognize: Callable[..., OcrPass],
                       native: Callable[[Image.Image, OcrProcessRunner], str],
                       runner: OcrProcessRunner, on_second: Callable[[], None],
                       on_windows: Callable[[], None], *,
                       compare_tesseract: bool = True) -> EngineComparison:
    """Independent OCR sources; neither result authorizes speech or auto admission."""
    decision: TextDecision | None = None
    first: OcrPass | None = None
    second: OcrPass | None = None
    tesseract_error: str | None = "NOT_RUN" if not compare_tesseract else None
    windows_error: str | None = None
    windows_text: str | None = None
    on_windows()
    try:
        windows_text = native(body, runner)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        windows_error = str(exc)[:100] or "WINDOWS_OCR_FAILED"
    if runner.cancelled.is_set():
        raise OcrCancelled()
    if compare_tesseract:
        try:
            decision, first, second = perform_two_pass(body, recognize, runner, on_second)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            tesseract_error = str(exc)[:100] or "TESSERACT_FAILED"
    if runner.cancelled.is_set():
        raise OcrCancelled()
    return EngineComparison(decision, first, second, windows_text,
                            tesseract_error, windows_error)


class PreviewWindow:
    """Keep one captured frame visible for overview, native-size refinement and retry."""

    def __init__(self, frame: Image.Image,
                 recognize: Callable[..., OcrPass],
                 native: Callable[[Image.Image, OcrProcessRunner], str] = recognize_windows) -> None:
        self.frame = frame
        self.recognize = recognize
        self.native = native
        self.root = tk.Tk()
        self.root.title("Mithril Voices - one-frame quest OCR preview")
        self.root.geometry("1250x950")
        self.root.minsize(900, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.attributes("-topmost", True)
        self.root.after_idle(self.root.lift)
        # Reserve the manual controls before the scrollable image and OCR panes.
        # Otherwise the image can consume the viewport and hide Read below it.
        self.actions = tk.Frame(self.root)
        self.actions.pack(side="bottom", fill="x")
        self.stage = "overview"
        self.viewport = Viewport(frame.width, frame.height, 1.0)
        self.photo: ImageTk.PhotoImage | None = None
        self.drag_start: tuple[float, float] | None = None
        self.selection: PixelRect | None = None
        self.job: OcrProcessRunner | None = None
        self.attempt = 0
        self.closed = False
        self.review = ReviewState.empty()
        self._loading_draft = False
        self.results: queue.Queue[tuple[int, object]] = queue.Queue()
        self.reader = ManualReadController()
        self.devices: dict[str, OutputDevice] = {}
        self.device_results: queue.Queue[object] = queue.Queue()

        self.instructions = tk.StringVar()
        tk.Label(self.root, textvariable=self.instructions).pack(anchor="w")
        holder = tk.Frame(self.root)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, width=min(1200, frame.width),
                                height=min(300, frame.height), cursor="crosshair")
        xscroll = tk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        yscroll = tk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        controls = tk.Frame(self.root)
        controls.pack(fill="x")
        self.refine_button = tk.Button(controls, text="Zoom to selection (native size)",
                                       command=self.refine)
        self.refine_button.pack(side="left")
        self.ocr_button = tk.Button(controls, text="Preview OCR of selected body",
                                    command=self.preview_ocr)
        self.ocr_button.pack(side="left")
        self.retry_button = tk.Button(controls, text="Retry crop from this frame",
                                      command=self.retry)
        self.retry_button.pack(side="left")
        self.compare_tesseract = tk.BooleanVar(value=False)
        tk.Checkbutton(controls, text="Compare Tesseract (optional diagnostic)",
                       variable=self.compare_tesseract).pack(side="left")
        self.cancel_button = tk.Button(controls, text="Cancel OCR", command=self.cancel_ocr)
        self.cancel_button.pack(side="left")
        tk.Button(controls, text="Close", command=self.close).pack(side="right")
        self.status = tk.StringVar(value="Select an approximate quest-body area.")
        tk.Label(self.root, textvariable=self.status, anchor="w").pack(fill="x")
        self.output = scrolledtext.ScrolledText(self.root, width=110, height=5,
                                                wrap="word")
        self.output.pack(fill="x")
        self.output.configure(state="disabled")
        sources = tk.Frame(self.root)
        sources.pack(fill="x")
        for column, title in enumerate(("Tesseract source guess",
                                        "Windows OCR source guess")):
            pane = tk.Frame(sources)
            pane.grid(row=0, column=column, sticky="nsew")
            tk.Label(pane, text=title).pack(anchor="w")
            widget = scrolledtext.ScrolledText(pane, height=4, wrap="word")
            widget.pack(fill="both", expand=True)
            widget.configure(state="disabled")
            widget.tag_configure("difference", background="#ffe19c")
            if column == 0:
                self.tesseract_text = widget
            else:
                self.windows_text = widget
            sources.grid_columnconfigure(column, weight=1)
        tk.Label(self.root, text="Editable review text (changes require confirmation again)").pack(anchor="w")
        self.draft = scrolledtext.ScrolledText(self.root, width=110, height=4, wrap="word")
        self.draft.pack(fill="x")
        self.draft.bind("<<Modified>>", self._draft_modified)
        self.confirm_button = tk.Button(self.actions, text="Confirm corrected text for this preview",
                                        command=self.confirm_review, state="disabled")
        self.confirm_button.pack(anchor="w")
        speech = tk.Frame(self.actions)
        speech.pack(fill="x")
        tk.Label(speech, text="Voice:").pack(side="left")
        self.voice_choice = ttk.Combobox(speech, width=20, state="readonly",
                                         values=("Emma (British)", "Fable (British)"))
        self.voice_choice.pack(side="left")
        self.voice_choice.bind("<<ComboboxSelected>>", self._speech_choice_changed)
        tk.Label(speech, text="Speakers:").pack(side="left")
        self.device_choice = ttk.Combobox(speech, width=44, state="readonly")
        self.device_choice.pack(side="left")
        self.device_choice.bind("<<ComboboxSelected>>", self._speech_choice_changed)
        tk.Button(speech, text="Refresh speakers", command=self._refresh_devices).pack(side="left")
        self.keep_cache = tk.BooleanVar(value=False)
        tk.Checkbutton(speech, text="Keep private local audio cache",
                       variable=self.keep_cache).pack(side="left")
        playback = tk.Frame(self.actions)
        playback.pack(fill="x")
        self.read_button = tk.Button(playback, text="Read confirmed text",
                                     command=self._read_confirmed, state="disabled")
        self.read_button.pack(side="left")
        self.stop_button = tk.Button(playback, text="Stop speech", command=self._stop_read)
        self.stop_button.pack(side="left")
        self.speech_status = tk.StringVar(value="Choose a voice and speaker, then confirm the text.")
        tk.Label(self.actions, textvariable=self.speech_status, anchor="w").pack(fill="x")
        self._render(overview=True)
        self._refresh_devices()
        self.root.after(100, self._poll_read)

    def _render(self, *, overview: bool, center: PixelRect | None = None) -> None:
        self._clear_review()
        self.stage = "overview" if overview else "refine"
        scale = min(1.0, 1200 / self.frame.width, 800 / self.frame.height) if overview else 1.0
        self.viewport = Viewport(self.frame.width, self.frame.height, scale)
        shown = self.frame.resize((round(self.frame.width * scale),
                                   round(self.frame.height * scale)))
        self.photo = ImageTk.PhotoImage(shown, master=self.root)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, shown.width, shown.height))
        self.selection = None
        self.refine_button.configure(state="normal" if overview else "disabled")
        self.ocr_button.configure(state="disabled" if overview else "normal")
        self.instructions.set("Overview: drag roughly around quest body, then Zoom to selection."
                              if overview else "Native size: scroll to pan, drag precisely around complete body lines, then Preview OCR.")
        if center is not None:
            self.root.update_idletasks()
            self.canvas.xview_moveto(max(0.0, (center.x + center.width / 2 -
                                                self.canvas.winfo_width() / 2) / shown.width))
            self.canvas.yview_moveto(max(0.0, (center.y + center.height / 2 -
                                                self.canvas.winfo_height() / 2) / shown.height))

    def _point(self, event: tk.Event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _press(self, event: tk.Event) -> None:
        if self.job is not None:
            return
        self._clear_review()
        self.drag_start = self._point(event)
        self.selection = None
        self.canvas.delete("selection")

    def _drag(self, event: tk.Event) -> None:
        if self.drag_start is None or self.job is not None:
            return
        end = self._point(event)
        self.selection = self.viewport.crop(*self.drag_start, *end)
        self.canvas.delete("selection")
        self.canvas.create_rectangle(*self.drag_start, *end, outline="red",
                                     width=2, tags="selection")

    def refine(self) -> None:
        if self.stage != "overview" or self.selection is None or self.job is not None:
            self.status.set("Drag a visible area of at least 20 x 20 source pixels first.")
            return
        self._render(overview=False, center=self.selection)
        self.status.set("At native size, pan with the scrollbars and select complete quest body text.")

    def _set_output(self, value: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", value)
        self.output.configure(state="disabled")

    @staticmethod
    def _set_source(widget: scrolledtext.ScrolledText, value: str,
                    differences: tuple[tuple[int, int], ...] = ()) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.tag_remove("difference", "1.0", "end")
        for start, end in differences:
            widget.tag_add("difference", f"1.0+{start}c", f"1.0+{end}c")
        widget.configure(state="disabled")

    def _set_draft(self, value: str) -> None:
        self._loading_draft = True
        self.draft.delete("1.0", "end")
        self.draft.insert("1.0", value)
        self.draft.edit_modified(False)
        self._loading_draft = False

    def _clear_review(self) -> None:
        self.reader.stop()
        self.review = self.review.invalidate()
        self._set_source(self.tesseract_text, "")
        self._set_source(self.windows_text, "")
        self._set_draft("")
        self.confirm_button.configure(state="disabled")
        self._update_read_button()

    def _draft_modified(self, _event: tk.Event) -> None:
        if self._loading_draft or not self.draft.edit_modified():
            return
        self.draft.edit_modified(False)
        self.review = self.review.edit(self.draft.get("1.0", "end-1c"))
        self.reader.stop()
        self.confirm_button.configure(state="normal" if self.review.can_confirm else "disabled")
        self.status.set("Review changed; confirmation cleared. Press Confirm before Read.")
        self._update_read_button()

    def confirm_review(self) -> None:
        self.review = self.review.edit(self.draft.get("1.0", "end-1c")).confirm()
        if self.review.confirmed and len(self.review.draft) > MAX_TEXT_CHARS:
            self.status.set("Text confirmed, but manual Read is limited to 3,000 characters."
                            " Shorten the draft and confirm it again.")
        else:
            self.status.set("Text confirmed for this manual read. Press Read when ready."
                            if self.review.confirmed else
                            "Review requires OCR source and 1-10,000 nonblank characters.")
        self._update_read_button()

    def _update_read_button(self) -> None:
        ready = (self.review.confirmed and self.review.can_confirm
                 and len(self.review.draft) <= MAX_TEXT_CHARS
                 and not self.reader.busy and self.voice_choice.get()
                 in {"Emma (British)", "Fable (British)"}
                 and self.device_choice.get() in self.devices)
        self.read_button.configure(state="normal" if ready else "disabled")

    def _speech_choice_changed(self, _event: tk.Event) -> None:
        self.reader.stop()
        self._update_read_button()

    def _refresh_devices(self) -> None:
        self.reader.stop()
        self.devices.clear()
        self.device_choice.set("")
        self.device_choice.configure(values=())
        self.speech_status.set("Finding local speakers; no audio is played...")
        self._update_read_button()

        def work() -> None:
            try:
                self.device_results.put(list_output_devices())
            except (ManualReadError, OSError, subprocess.TimeoutExpired) as exc:
                self.device_results.put(exc)

        threading.Thread(target=work, daemon=True).start()

    def _poll_read(self) -> None:
        if self.closed:
            return
        try:
            while True:
                result = self.device_results.get_nowait()
                if isinstance(result, Exception):
                    self.speech_status.set(f"Speaker list unavailable: {result}.")
                    continue
                devices = cast(tuple[OutputDevice, ...], result)
                self.devices = {f"{item.description} [{item.id[-8:]}]": item
                                for item in devices}
                self.device_choice.configure(values=tuple(self.devices))
                self.speech_status.set("Select the Realtek speakers or another intended output.")
        except queue.Empty:
            pass
        try:
            while True:
                event, value = self.reader.events.get_nowait()
                descriptions = {
                    "SYNTHESIZING": "Rendering confirmed text with the local offline voice...",
                    "CACHE_HIT": "Using verified private local audio cache...",
                    "PREPARING_AUDIO": "Checking complete audio and selected speaker...",
                    "READY": "Audio owner ready; reading starts now.",
                    "UNIT_RENDERED": f"Voice rendered unit {value}.",
                    "UNIT_STARTED": f"Reading unit {value}.",
                    "UNIT_DONE": f"Completed unit {value}.",
                    "STOPPING": "Stopping and fencing the current read...",
                    "STOPPED": "Stopped. The reviewed text remains available to read again.",
                    "COMPLETED": "Read completed. Press Read to hear it again.",
                    "ERROR": f"Read stopped safely: {value}. Review setup and retry.",
                }
                self.speech_status.set(descriptions.get(event, "Read status unavailable."))
        except queue.Empty:
            pass
        self._update_read_button()
        self.root.after(100, self._poll_read)

    def _read_confirmed(self) -> None:
        current = self.draft.get("1.0", "end-1c")
        if current != self.review.draft:
            self.review = self.review.edit(current)
            self.status.set("Text changed; confirm it again before reading.")
            self._update_read_button()
            return
        voice = {"Emma (British)": "bf_emma", "Fable (British)": "bm_fable"}.get(
            self.voice_choice.get())
        device = self.devices.get(self.device_choice.get())
        if voice is None or device is None:
            self.speech_status.set("Select a voice and exact speaker first.")
            return
        if self.reader.read(self.review, voice, device,
                            keep_local_cache=self.keep_cache.get()):
            self.speech_status.set("Preparing private local speech...")
        self._update_read_button()

    def _stop_read(self) -> None:
        self.reader.stop()
        self._update_read_button()

    def preview_ocr(self) -> None:
        if self.job is not None:
            return
        if self.stage != "refine" or self.selection is None:
            self.status.set("Drag a precise body-text crop at native size first.")
            return
        crop = self.selection
        if not crop_is_bounded(crop):
            self.status.set("Crop is too large for bounded OCR. Select only the quest body.")
            return
        body = self.frame.crop((crop.x, crop.y, crop.x + crop.width,
                                crop.y + crop.height))
        self._clear_review()
        compare_tesseract = self.compare_tesseract.get()
        self.attempt += 1
        attempt = self.attempt
        runner = OcrProcessRunner()
        self.job = runner
        self.ocr_button.configure(state="disabled")
        self.refine_button.configure(state="disabled")
        self.retry_button.configure(state="disabled")
        self.status.set("Windows OCR running (3-second child timeout).")
        self._set_output("")

        def work() -> None:
            try:
                comparison = perform_comparison(
                    body, self.recognize, self.native, runner,
                    lambda: self.results.put((attempt, "SECOND_PASS")),
                    lambda: None,
                    compare_tesseract=compare_tesseract)
                self.results.put((attempt, (comparison, crop)))
            except (OcrCancelled, OSError, ValueError, RuntimeError,
                    subprocess.TimeoutExpired) as exc:
                self.results.put((attempt, exc))
            except Exception:  # noqa: BLE001 - always release UI busy state
                self.results.put((attempt, RuntimeError("OCR_INTERNAL_ERROR")))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._poll)

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            attempt, result = self.results.get_nowait()
        except queue.Empty:
            if self.job is not None:
                self.root.after(100, self._poll)
            return
        if attempt != self.attempt:
            if self.job is not None:
                self.root.after(100, self._poll)
            return
        if result == "SECOND_PASS":
            self.status.set("Tesseract pass 2 of 2 running (at most 10 seconds).")
            self.root.after(100, self._poll)
            return
        if result == "WINDOWS_PASS":
            self.status.set("Windows OCR running (at most 3 seconds if available).")
            self.root.after(100, self._poll)
            return
        canceled = self.job is not None and self.job.cancelled.is_set()
        self.job = None
        self.retry_button.configure(state="normal")
        self.ocr_button.configure(state="normal")
        if canceled:
            self._clear_review()
            self.status.set("OCR canceled; no result retained.")
            return
        if isinstance(result, Exception):
            self.status.set("OCR canceled." if isinstance(result, OcrCancelled)
                            else f"OCR stopped: {result}. Refine and retry this frame.")
            return
        comparison, crop = cast(tuple[EngineComparison, PixelRect], result)
        self.review = self.review.load(crop, comparison.tesseract_text,
                                       comparison.windows_text)
        left = comparison.tesseract_text or ""
        right = comparison.windows_text or ""
        left_diff, right_diff = disagreement_spans(left, right) if left and right else ((), ())
        self._set_source(self.tesseract_text, left, left_diff)
        self._set_source(self.windows_text, right, right_diff)
        self._set_draft(self.review.draft)
        self.confirm_button.configure(state="normal" if self.review.can_confirm else "disabled")
        tesseract_status = (comparison.tesseract.reason if comparison.tesseract is not None
                            else comparison.tesseract_error or "UNAVAILABLE")
        windows_status = ("returned text" if right else
                          comparison.windows_error or "EMPTY_OCR_OUTPUT")
        comparison_hint = ("Highlighted words differ. " if left and right else "")
        self.status.set(f"Windows OCR: {windows_status}; Tesseract diagnostic: {tesseract_status}. "
                        f"{comparison_hint}Check the image and confirm your edit.")
        explanation = (gate_explanation(comparison.tesseract, comparison.first,
                                        comparison.second)
                       if comparison.tesseract is not None and comparison.first is not None
                       and comparison.second is not None else
                       f"Tesseract: {comparison.tesseract_error or 'unavailable'}.")
        self._set_output(f"{explanation}\nWindows OCR: {windows_status}. "
                         "Neither agreement nor an edit is an automated speech pass.\n"
                         f"Crop: x={crop.x}, y={crop.y}, {crop.width}x{crop.height}; "
                         f"frame: {self.frame.width}x{self.frame.height}.")
        print(f"Comparison: Tesseract={tesseract_status}; Windows={windows_status}; "
              f"crop={crop.x},{crop.y},{crop.width},{crop.height}; "
              f"frame={self.frame.width}x{self.frame.height}.", flush=True)

    def cancel_ocr(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status.set("Canceling OCR child process; review invalidated...")

    def retry(self) -> None:
        if self.job is not None:
            self.cancel_ocr()
            return
        self._render(overview=True)
        self.status.set("Retry with the same captured frame; no new game capture occurs.")
        self._set_output("")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.job is not None:
            self.job.cancel()
        try:
            self.reader.close()
        except ManualReadError as exc:
            self.closed = False
            self.speech_status.set(f"Cannot close while audio is active: {exc}. Press Stop and retry.")
            return
        self.review = self.review.invalidate()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def show_preview(frame: Image.Image, recognize: Callable[..., OcrPass]) -> None:
    PreviewWindow(frame, recognize).run()
