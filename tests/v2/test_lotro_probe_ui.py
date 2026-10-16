"""Synthetic-only crop, OCR, cancellation and preview lifecycle checks."""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest
from PIL import Image

from lvc.platform.windows.lotro_probe_ui import (
    OcrCancelled,
    OcrProcessRunner,
    PreviewWindow,
    Viewport,
    crop_is_bounded,
    gate_explanation,
    perform_two_pass,
)
from lvc.platform.windows.manual_read import ManualReadController
from lvc.vision.binding import PixelRect
from lvc.vision.comparison import ReviewState
from lvc.vision.text_gate import OcrPass, OcrWord


def test_ultrawide_overview_and_native_scrolled_crop_mapping() -> None:
    overview = Viewport(5120, 1440, 1200 / 5120)
    # An approximate 80x50 display-pixel selection remains bounded in source pixels.
    assert overview.crop(710, 145, 790, 195) == PixelRect(3029, 619, 342, 213)
    native = Viewport(5120, 1440, 1)
    # Canvas coordinates include scroll offset; no second scaling is applied.
    assert native.crop(3040, 635, 3370, 875) == PixelRect(3040, 635, 330, 240)
    assert native.crop(10, 10, 20, 20) is None
    assert native.crop(-100, -100, 5200, 1500) == PixelRect(0, 0, 5120, 1440)
    assert crop_is_bounded(PixelRect(3040, 635, 330, 240))
    assert not crop_is_bounded(PixelRect(0, 0, 5120, 1440))


def _pass(text: str, *, clipped: bool = False) -> OcrPass:
    words = tuple(OcrWord(word, 97, clipped) for word in text.split())
    return OcrPass(text, words)


def test_two_pass_acceptance_rejection_and_reason_explanation() -> None:
    image = Image.new("RGB", (100, 40), "white")
    updates: list[str] = []
    accepted = _pass("Lanterns glow tonight")
    decision, first, second = perform_two_pass(
        image, lambda _image, **_kwargs: accepted, OcrProcessRunner(),
        lambda: updates.append("second"))
    assert decision.reason == "ACCEPTED" and decision.accepted_text == "Lanterns glow tonight"
    assert updates == ["second"]
    assert "agree" in gate_explanation(decision, first, second)

    clipped = _pass("Lanterns glow tonight", clipped=True)
    decision, first, second = perform_two_pass(
        image, lambda _image, **_kwargs: clipped, OcrProcessRunner(), lambda: None)
    assert decision.reason == "INCOMPLETE_OR_INVALID_WORD"
    assert decision.accepted_text is None
    assert "crop edge" in gate_explanation(decision, first, second)

    low = OcrPass("Arin", (OcrWord("Arin", 14.8),))
    decision, first, second = perform_two_pass(
        image, lambda _image, **_kwargs: low, OcrProcessRunner(), lambda: None)
    assert decision.reason == "LOW_OCR_CONFIDENCE"
    assert "min 14.8" in gate_explanation(decision, first, second)
    assert "#1 recognized as 'Arin' (14.8)" in gate_explanation(decision, first, second)

    punctuation = OcrPass("...", (OcrWord("...", 96),))
    decision, first, second = perform_two_pass(
        image, lambda _image, **_kwargs: punctuation,
        OcrProcessRunner(), lambda: None)
    assert decision.reason == "LOW_OCR_CONFIDENCE"
    assert "no alphanumeric word guesses" in gate_explanation(decision, first, second)


def test_cancel_between_passes_prevents_second_ocr_call() -> None:
    calls: list[bool] = []
    runner = OcrProcessRunner()

    def recognize(_image: Image.Image, *, alternative: bool,
                  runner: OcrProcessRunner) -> OcrPass:
        calls.append(alternative)
        runner.cancel()
        return _pass("Test words")

    with pytest.raises(OcrCancelled):
        perform_two_pass(Image.new("RGB", (50, 50)), recognize, runner, lambda: None)
    assert calls == [False]


def test_timeout_kills_and_reaps_ocr_child() -> None:
    runner = OcrProcessRunner(timeout=0.1)
    with pytest.raises(RuntimeError, match="OCR_TIMEOUT"):
        runner([sys.executable, "-c", "import time; time.sleep(30)"],
               input=b"", capture_output=True, timeout=10, check=False)
    assert runner._active is None


def test_cancel_kills_and_reaps_ocr_child() -> None:
    runner = OcrProcessRunner(timeout=10)
    finished = threading.Event()
    failures: list[Exception] = []

    def work() -> None:
        try:
            runner([sys.executable, "-c", "import time; time.sleep(30)"],
                   input=b"", capture_output=True, timeout=10, check=False)
        except OcrCancelled as exc:
            failures.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=work)
    thread.start()
    deadline = time.monotonic() + 3
    while runner._active is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner._active is not None
    runner.cancel()
    assert finished.wait(3)
    thread.join()
    assert len(failures) == 1 and isinstance(failures[0], OcrCancelled)
    assert runner._active is None


def test_repeated_preview_click_retry_and_close_lifecycle(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRoot:
        destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    preview = object.__new__(PreviewWindow)
    preview.job = OcrProcessRunner()
    preview.closed = False
    preview.review = ReviewState.empty()
    preview.reader = ManualReadController()
    messages: list[str] = []

    class FakeStatus:
        def set(self, value: str) -> None:
            messages.append(value)

    preview.status = FakeStatus()  # type: ignore[assignment]
    root = FakeRoot()
    preview.root = root  # type: ignore[assignment]
    preview.preview_ocr()  # No new OCR task while one is already running.
    preview.preview_ocr()
    assert preview.job is not None and not preview.job.cancelled.is_set()
    preview.retry()  # A retry while busy cancels rather than starting another job.
    assert preview.job.cancelled.is_set()
    preview.close()
    preview.close()
    assert preview.job.cancelled.is_set()
    assert root.destroyed

    # Once the worker is done, retry only resets the view of the same frame.
    preview.job = None
    preview.closed = False
    renders: list[bool] = []
    messages.clear()
    monkeypatch.setattr(PreviewWindow, "_render",
                        lambda _self, *, overview: renders.append(overview))
    monkeypatch.setattr(PreviewWindow, "_set_output",
                        lambda _self, value: messages.append(value))
    preview.retry()
    assert renders == [True]
    assert "no new game capture" in messages[0]


def test_ocr_runner_preserves_binary_output() -> None:
    runner = OcrProcessRunner()
    result = runner([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'OK')"],
                    input=b"", capture_output=True, timeout=10, check=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0 and result.stdout == b"OK"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Tk preview layout")
def test_manual_controls_have_reserved_footer_in_ultrawide_preview() -> None:
    preview = PreviewWindow(Image.new("RGB", (5120, 1440)),
                            lambda _image, **_kwargs: _pass("Synthetic words"),
                            lambda _image, _runner: "Synthetic words")
    try:
        preview.root.withdraw()
        preview.root.update_idletasks()
        assert preview.actions.pack_info()["side"] == "bottom"
        assert preview.confirm_button.master is preview.actions
        assert preview.voice_choice.master.master is preview.actions
        assert preview.read_button.master.master is preview.actions
        assert preview.root.winfo_reqheight() <= 950
    finally:
        preview.close()
