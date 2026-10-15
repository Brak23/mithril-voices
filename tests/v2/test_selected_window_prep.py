"""Synthetic identity, freshness, crop and text oracles; no screen is opened."""
from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from lvc.vision.binding import (
    FrameMetadata,
    FrameStatus,
    NativeWindowIdentity,
    PixelRect,
    SelectedWindow,
    WindowFacts,
)
from lvc.vision.pipeline import GrayFrame, inspect_frame
from lvc.vision.text_gate import OcrPass, OcrWord, decide_text

IDENTITY = NativeWindowIdentity(101, 501, 90001, r"C:\Games\LOTRO\lotroclient64.exe")
OTHER = NativeWindowIdentity(102, 502, 90002, IDENTITY.executable_path)
REUSED_HANDLE = NativeWindowIdentity(101, 502, 90002, IDENTITY.executable_path)
BINDING = UUID("00000000-0000-4000-8000-000000000021")
CROP = PixelRect(20, 30, 400, 300)


def facts(identity: NativeWindowIdentity = IDENTITY) -> WindowFacts:
    return WindowFacts(identity, True, True, False, True, 800, 600, 120)


def frame(identity: NativeWindowIdentity | None = IDENTITY,
          *, seq: int = 1, acquired_ns: int = 200) -> FrameMetadata:
    return FrameMetadata(identity, identity is not None, seq, acquired_ns, 800, 600)


def selected() -> SelectedWindow:
    return SelectedWindow.select(facts(), IDENTITY.executable_path, BINDING, 100)


def test_selected_window_accepts_only_fresh_verified_frame_and_bounded_crop() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    updated, status = window.accept(ticket, facts(), frame(), CROP)
    assert status is FrameStatus.READY
    assert updated.last_capture_seq == 1
    assert updated.identity == IDENTITY


@pytest.mark.parametrize("bad_facts", [replace(facts(), native_verified=False),
                                       replace(facts(), visible=False),
                                       replace(facts(), minimized=True),
                                       replace(facts(), focused=False),
                                       replace(facts(), client_width=0)])
def test_unverified_or_unusable_window_cannot_be_selected(bad_facts: WindowFacts) -> None:
    with pytest.raises(ValueError):
        SelectedWindow.select(bad_facts, IDENTITY.executable_path, BINDING, 100)


def test_selection_requires_the_approved_executable_path() -> None:
    with pytest.raises(ValueError):
        SelectedWindow.select(facts(), r"C:\Other\lotroclient64.exe", BINDING, 100)


@pytest.mark.parametrize("replacement", [OTHER, REUSED_HANDLE])
def test_identical_title_or_reused_handle_cannot_change_selected_window(
        replacement: NativeWindowIdentity) -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    updated, status = window.accept(ticket, facts(replacement), frame(replacement), CROP)
    assert status is FrameStatus.WRONG_WINDOW
    assert updated.suspended
    assert updated.ticket() is None


def test_unknown_frame_source_suspends_instead_of_trusting_a_qt_description() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    updated, status = window.accept(ticket, facts(), frame(None), CROP)
    assert status is FrameStatus.SOURCE_UNVERIFIED
    assert updated.suspended


def test_focus_loss_fences_old_ticket_and_revalidation_needs_new_frame() -> None:
    window = selected()
    old_ticket = window.ticket()
    assert old_ticket is not None
    suspended, status = window.accept(old_ticket, replace(facts(), focused=False), frame(), CROP)
    assert status is FrameStatus.SUSPENDED
    recovered = suspended.revalidate(facts(), 300)
    assert recovered.ticket() is not None
    _, status = recovered.accept(old_ticket, facts(), frame(seq=2, acquired_ns=400), CROP)
    assert status is FrameStatus.STALE_FRAME
    new_ticket = recovered.ticket()
    assert new_ticket is not None
    _, status = recovered.accept(new_ticket, facts(), frame(seq=2, acquired_ns=250), CROP)
    assert status is FrameStatus.STALE_FRAME
    _, status = recovered.accept(new_ticket, facts(), frame(seq=2, acquired_ns=400), CROP)
    assert status is FrameStatus.READY


def test_geometry_change_and_out_of_bounds_crop_never_authorize_ocr() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    changed, status = window.accept(ticket, replace(facts(), dpi=144), frame(), CROP)
    assert status is FrameStatus.GEOMETRY_INVALID and changed.suspended
    _, status = window.accept(ticket, facts(), frame(), PixelRect(700, 30, 400, 300))
    assert status is FrameStatus.GEOMETRY_INVALID
    _, status = window.accept(ticket, facts(), frame(), None)
    assert status is FrameStatus.GEOMETRY_INVALID


def test_duplicate_and_preselection_frames_are_stale() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    advanced, status = window.accept(ticket, facts(), frame(seq=5), CROP)
    assert status is FrameStatus.READY
    _, status = advanced.accept(ticket, facts(), frame(seq=5, acquired_ns=300), CROP)
    assert status is FrameStatus.STALE_FRAME
    _, status = window.accept(ticket, facts(), frame(acquired_ns=100), CROP)
    assert status is FrameStatus.STALE_FRAME


def ocr(raw: str, *words: str, confidence: float = 96,
        clipped: bool = False) -> OcrPass:
    return OcrPass(raw, tuple(OcrWord(word, confidence, clipped) for word in words))


def test_ocr_preserves_original_visible_words_including_rewards() -> None:
    first = ocr("The sign says REWARDS are delayed.", "The", "sign", "says",
                "REWARDS", "are", "delayed.")
    second = ocr("the sign says rewards are delayed.", "the", "sign", "says",
                 "rewards", "are", "delayed.")
    decision = decide_text(first, second, qualified_region=True)
    assert decision.accepted_text == first.raw_text
    assert decision.reason == "ACCEPTED"


def test_ocr_disagreed_number_abstains_but_keeps_raw_preview() -> None:
    first = ocr("Bring 10 stones, not 18.", "Bring", "10", "stones,", "not", "18.")
    second = ocr("Bring 18 stones, not 18.", "Bring", "18", "stones,", "not", "18.")
    decision = decide_text(first, second, qualified_region=True)
    assert decision.reason == "OCR_PASS_DISAGREEMENT"
    assert decision.accepted_text is None and decision.raw_text == first.raw_text


@pytest.mark.parametrize("first,second,qualified,reason", [
    (ocr("", ), ocr("", ), True, "EMPTY_OCR_OUTPUT"),
    (ocr("A clipped line", "A", "clipped", "line", clipped=True),
     ocr("A clipped line", "A", "clipped", "line"), True, "INCOMPLETE_OR_INVALID_WORD"),
    (ocr("A weak word", "A", "weak", "word", confidence=39),
     ocr("A weak word", "A", "weak", "word"), True, "LOW_OCR_CONFIDENCE"),
    (ocr("A valid line", "A", "valid", "line"),
     ocr("A valid line", "A", "valid", "line"), False, "GEOMETRY_INVALID"),
])
def test_ocr_abstains_on_empty_clipped_weak_or_unqualified_input(
        first: OcrPass, second: OcrPass, qualified: bool, reason: str) -> None:
    result = decide_text(first, second, qualified_region=qualified)
    assert result.reason == reason and result.accepted_text is None


def test_qualified_frame_passes_only_selected_crop_to_recognizer() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    pixels = bytes(row % 256 for row in range(600) for _ in range(800))
    expected = bytes(row % 256 for row in range(30, 330) for _ in range(400))
    seen: list[tuple[bytes, int, int]] = []

    def recognize(cropped: bytes, width: int, height: int) -> tuple[OcrPass, OcrPass]:
        seen.append((cropped, width, height))
        result = ocr("Bring 10 stones", "Bring", "10", "stones")
        return result, result

    result = inspect_frame(window, ticket, facts(), GrayFrame(frame(), pixels),
                           CROP, recognize)
    assert result.frame_status is FrameStatus.READY
    assert result.text is not None and result.text.accepted_text == "Bring 10 stones"
    assert seen == [(expected, 400, 300)]


@pytest.mark.parametrize("bad_metadata,bad_crop", [
    (frame(None), CROP),
    (frame(OTHER), CROP),
    (frame(acquired_ns=100), CROP),
    (frame(), None),
    (frame(), PixelRect(790, 0, 20, 20)),
])
def test_rejected_frame_or_crop_never_reaches_ocr(
        bad_metadata: FrameMetadata, bad_crop: PixelRect | None) -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None
    calls = 0

    def recognize(_pixels: bytes, _width: int, _height: int) -> tuple[OcrPass, OcrPass]:
        nonlocal calls
        calls += 1
        raise AssertionError("OCR must not see rejected pixels")

    result = inspect_frame(window, ticket, facts(),
                           GrayFrame(bad_metadata, bytes(800 * 600)), bad_crop, recognize)
    assert result.frame_status is not FrameStatus.READY
    assert result.text is None and calls == 0


def test_malformed_frame_buffer_suspends_before_ocr() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None

    def recognize(_pixels: bytes, _width: int, _height: int) -> tuple[OcrPass, OcrPass]:
        raise AssertionError("OCR must not see malformed pixels")

    result = inspect_frame(window, ticket, facts(), GrayFrame(frame(), b"short"),
                           CROP, recognize)
    assert result.frame_status is FrameStatus.GEOMETRY_INVALID
    assert result.window.suspended and result.text is None


def test_ocr_error_suspends_live_binding() -> None:
    window = selected()
    ticket = window.ticket()
    assert ticket is not None

    def recognize(_pixels: bytes, _width: int, _height: int) -> tuple[OcrPass, OcrPass]:
        raise OSError("synthetic OCR failure")

    result = inspect_frame(window, ticket, facts(),
                           GrayFrame(frame(), bytes(800 * 600)), CROP, recognize)
    assert result.window.suspended and result.text is None
    assert result.frame_status is FrameStatus.SUSPENDED
