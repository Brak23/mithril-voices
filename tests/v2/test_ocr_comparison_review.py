"""Independent synthetic oracles for the manual comparison preview."""
from __future__ import annotations

import queue
import sys
import threading
import time

import pytest
from PIL import Image

from lvc.platform.windows.lotro_probe_ui import (
    OcrCancelled,
    OcrProcessRunner,
    PreviewWindow,
    perform_comparison,
)
from lvc.vision.binding import PixelRect
from lvc.vision.comparison import ReviewState, disagreement_spans
from lvc.vision.text_gate import OcrPass, OcrWord


def _pass(text: str) -> OcrPass:
    return OcrPass(text, tuple(OcrWord(token, 98) for token in text.split()))


def test_disagreement_spans_mark_each_source_without_erasing_agreement() -> None:
    left = "I am in North Gate."
    right = "Iam in North Gates."
    a, b = disagreement_spans(left, right)
    assert [left[start:end] for start, end in a] == ["I", "am", "Gate."]
    assert [right[start:end] for start, end in b] == ["Iam", "Gates."]
    assert disagreement_spans("Same words.", "Same words.") == ((), ())


def test_review_never_promotes_agreement_or_edit_to_automated_pass() -> None:
    crop = PixelRect(20, 20, 200, 80)
    state = ReviewState.empty().load(crop, "Lanterns glow", "Lanterns glow")
    assert not state.confirmed
    assert state.tesseract_source == state.windows_source
    assert state.automated_acceptance is False
    state = state.confirm()
    assert state.confirmed and state.draft == "Lanterns glow"
    assert state.automated_acceptance is False
    state = state.edit("Lanterns glow tonight")
    assert not state.confirmed
    assert state.tesseract_source == "Lanterns glow"
    assert state.windows_source == "Lanterns glow"
    assert state.confirm().confirmed
    assert not state.invalidate().confirmed


def test_cannot_confirm_blank_or_unrelated_source_free_review() -> None:
    crop = PixelRect(0, 0, 50, 50)
    assert not ReviewState.empty().confirm().confirmed
    assert not ReviewState.empty().load(crop, None, None).edit("Invented").confirm().confirmed
    assert not ReviewState.empty().load(crop, "Known", None).edit(" \n ").confirm().confirmed


def test_engine_failure_keeps_independent_source_and_no_confirmation() -> None:
    image = Image.new("RGB", (80, 50), "white")
    runner = OcrProcessRunner()

    def bad_tesseract(_image: Image.Image, **_kwargs: object) -> OcrPass:
        raise RuntimeError("TESSERACT_FAILED")

    result = perform_comparison(image, bad_tesseract,
                                lambda _image, _runner: "Windows saw text", runner,
                                lambda: None, lambda: None)
    assert result.tesseract is None and result.tesseract_error == "TESSERACT_FAILED"
    assert result.windows_text == "Windows saw text"
    assert not ReviewState.empty().load(PixelRect(0, 0, 80, 50),
                                        result.tesseract_text, result.windows_text).confirmed

    result = perform_comparison(image, lambda _image, **_kwargs: _pass("Tess saw text"),
                                lambda _image, _runner: (_ for _ in ()).throw(
                                    RuntimeError("WINDOWS_OCR_TIMEOUT")),
                                OcrProcessRunner(), lambda: None, lambda: None)
    assert result.tesseract is not None and result.windows_text is None
    assert result.windows_error == "WINDOWS_OCR_TIMEOUT"


def test_cancel_during_native_child_reaps_it_and_never_returns_result() -> None:
    runner = OcrProcessRunner()
    started = threading.Event()
    finished = threading.Event()
    outcomes: list[object] = []

    def native(_image: Image.Image, active: OcrProcessRunner) -> str:
        started.set()
        active([sys.executable, "-c", "import time; time.sleep(30)"], input=b"",
               capture_output=True, timeout=10, check=False)
        return "stale text"

    def work() -> None:
        try:
            outcomes.append(perform_comparison(
                Image.new("RGB", (80, 50)),
                lambda _image, **_kwargs: _pass("Synthetic words"), native,
                runner, lambda: None, lambda: None))
        except OcrCancelled as exc:
            outcomes.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=work)
    thread.start()
    assert started.wait(2)
    deadline = time.monotonic() + 3
    while runner._active is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner._active is not None
    runner.cancel()
    assert finished.wait(3)
    thread.join()
    assert len(outcomes) == 1 and isinstance(outcomes[0], OcrCancelled)
    assert runner._active is None


def test_native_child_timeout_is_bounded() -> None:
    runner = OcrProcessRunner(timeout=0.1)
    with pytest.raises(RuntimeError, match="OCR_TIMEOUT"):
        runner([sys.executable, "-c", "import time; time.sleep(30)"],
               input=b"", capture_output=True, timeout=1, check=False)
    assert runner._active is None


def test_stale_and_canceled_results_cannot_restore_a_confirmed_review() -> None:
    class FakeRoot:
        def after(self, _delay: int, _callback: object) -> None:
            pass

    class FakeButton:
        def configure(self, **_kwargs: object) -> None:
            pass

    class FakeStatus:
        value = ""

        def set(self, value: str) -> None:
            self.value = value

    crop = PixelRect(0, 0, 80, 50)
    preview = object.__new__(PreviewWindow)
    preview.closed = False
    preview.attempt = 2
    preview.job = OcrProcessRunner()
    preview.results = queue.Queue()
    preview.root = FakeRoot()  # type: ignore[assignment]
    preview.retry_button = FakeButton()  # type: ignore[assignment]
    preview.ocr_button = FakeButton()  # type: ignore[assignment]
    preview.status = FakeStatus()  # type: ignore[assignment]
    preview.review = ReviewState.empty().load(crop, "Old text", "Old text").confirm()
    preview.results.put((1, ("obsolete result", crop)))
    preview._poll()
    assert preview.review.confirmed and preview.job is not None

    preview.job.cancel()
    preview.results.put((2, ("result after cancel", crop)))
    preview._clear_review = lambda: setattr(preview, "review", ReviewState.empty())  # type: ignore[method-assign]
    preview._poll()
    assert not preview.review.confirmed and preview.review.crop is None
    assert preview.job is None


def test_starting_a_new_crop_invalidates_prior_human_confirmation() -> None:
    class FakeText:
        def configure(self, **_kwargs: object) -> None:
            pass

        def delete(self, *_args: object) -> None:
            pass

        def insert(self, *_args: object) -> None:
            pass

        def tag_remove(self, *_args: object) -> None:
            pass

        def edit_modified(self, *_args: object) -> None:
            pass

    class FakeCanvas:
        def delete(self, *_args: object) -> None:
            pass

    preview = object.__new__(PreviewWindow)
    preview.job = None
    preview._loading_draft = False
    preview.review = ReviewState.empty().load(PixelRect(0, 0, 80, 50),
                                              "Source", "Source").confirm()
    preview.tesseract_text = FakeText()  # type: ignore[assignment]
    preview.windows_text = FakeText()  # type: ignore[assignment]
    preview.draft = FakeText()  # type: ignore[assignment]
    preview.confirm_button = FakeText()  # type: ignore[assignment]
    preview.canvas = FakeCanvas()  # type: ignore[assignment]
    preview._point = lambda _event: (10, 20)  # type: ignore[method-assign]
    preview._press(object())  # type: ignore[arg-type]
    assert preview.review == ReviewState.empty()
    assert preview.drag_start == (10, 20)
