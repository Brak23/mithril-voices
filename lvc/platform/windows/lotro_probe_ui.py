"""Local, single-frame LOTRO OCR preview. Pixels and OCR stay in memory."""
from __future__ import annotations

import queue
import statistics
import subprocess
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import scrolledtext
from typing import cast

from PIL import Image, ImageTk

from lvc.vision.binding import PixelRect
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


class PreviewWindow:
    """Keep one captured frame visible for overview, native-size refinement and retry."""

    def __init__(self, frame: Image.Image,
                 recognize: Callable[..., OcrPass]) -> None:
        self.frame = frame
        self.recognize = recognize
        self.root = tk.Tk()
        self.root.title("Mithril Voices - one-frame quest OCR preview")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.attributes("-topmost", True)
        self.root.after_idle(self.root.lift)
        self.stage = "overview"
        self.viewport = Viewport(frame.width, frame.height, 1.0)
        self.photo: ImageTk.PhotoImage | None = None
        self.drag_start: tuple[float, float] | None = None
        self.selection: PixelRect | None = None
        self.job: OcrProcessRunner | None = None
        self.attempt = 0
        self.closed = False
        self.results: queue.Queue[tuple[int, object]] = queue.Queue()

        self.instructions = tk.StringVar()
        tk.Label(self.root, textvariable=self.instructions).pack(anchor="w")
        holder = tk.Frame(self.root)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, width=min(1200, frame.width),
                                height=min(800, frame.height), cursor="crosshair")
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
        self.cancel_button = tk.Button(controls, text="Cancel OCR", command=self.cancel_ocr)
        self.cancel_button.pack(side="left")
        tk.Button(controls, text="Close", command=self.close).pack(side="right")
        self.status = tk.StringVar(value="Select an approximate quest-body area.")
        tk.Label(self.root, textvariable=self.status, anchor="w").pack(fill="x")
        self.output = scrolledtext.ScrolledText(self.root, width=110, height=8,
                                                wrap="word")
        self.output.pack(fill="x")
        self.output.configure(state="disabled")
        self._render(overview=True)

    def _render(self, *, overview: bool, center: PixelRect | None = None) -> None:
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
        self.attempt += 1
        attempt = self.attempt
        runner = OcrProcessRunner()
        self.job = runner
        self.ocr_button.configure(state="disabled")
        self.refine_button.configure(state="disabled")
        self.retry_button.configure(state="disabled")
        self.status.set("OCR pass 1 of 2 running. Each Tesseract child has a 10-second timeout.")
        self._set_output("")

        def work() -> None:
            try:
                decision, first, second = perform_two_pass(
                    body, self.recognize, runner,
                    lambda: self.results.put((attempt, "SECOND_PASS")))
                self.results.put((attempt, (decision, first, second, crop)))
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
            self.status.set("OCR pass 2 of 2 running (at most 10 seconds).")
            self.root.after(100, self._poll)
            return
        self.job = None
        self.retry_button.configure(state="normal")
        self.ocr_button.configure(state="normal")
        if isinstance(result, Exception):
            self.status.set("OCR canceled." if isinstance(result, OcrCancelled)
                            else f"OCR stopped: {result}. Refine and retry this frame.")
            return
        decision, first, second, crop = cast(
            tuple[TextDecision, OcrPass, OcrPass, PixelRect], result)
        self.status.set(f"{decision.reason}; accepted={decision.accepted_text is not None}. "
                        "You can refine and retry this same frame.")
        self._set_output(f"{gate_explanation(decision, first, second)}\n"
                         f"Crop: x={crop.x}, y={crop.y}, {crop.width}x{crop.height}; "
                         f"frame: {self.frame.width}x{self.frame.height}.\n\n"
                         f"Raw local OCR preview (not saved or uploaded):\n{decision.raw_text}")
        print(f"Two-pass gate: {decision.reason}; accepted={decision.accepted_text is not None}; "
              f"crop={crop.x},{crop.y},{crop.width},{crop.height}; "
              f"frame={self.frame.width}x{self.frame.height}.", flush=True)

    def cancel_ocr(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status.set("Canceling OCR child process...")

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
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def show_preview(frame: Image.Image, recognize: Callable[..., OcrPass]) -> None:
    PreviewWindow(frame, recognize).run()
