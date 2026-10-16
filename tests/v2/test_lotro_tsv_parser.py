"""Literal Tesseract TSV fixtures; no game frames or owner text."""
from __future__ import annotations

import pytest

from lvc.platform.windows.lotro_user_probe import TSV_HEADER, parse_tesseract_tsv
from lvc.vision.text_gate import decide_text


def tsv(*rows: tuple[object, ...], newline: str = "\n") -> bytes:
    return (newline.join(("\t".join(TSV_HEADER),
                          *("\t".join(str(field) for field in row) for row in rows)))
            + newline).encode("utf-8")


def word(number: int, text: str, confidence: object = 96,
         *, line: int = 1) -> tuple[object, ...]:
    return (5, 1, 1, 1, line, number, 15 + number * 35, 20, 30, 14,
            confidence, text)


def test_quotes_do_not_turn_literal_tsv_rows_into_preview_text() -> None:
    structural = (4, 1, 1, 1, 1, 0, 0, 0, 400, 70, -1, "")
    for newline in ("\n", "\r\n"):
        payload = tsv(structural, word(1, '"Lantern'), word(2, "glows"),
                      word(3, '"tonight'), newline=newline)
        result = parse_tesseract_tsv(payload, width=400, height=100, margin=3)
        assert result.raw_text == '"Lantern glows "tonight'
        assert tuple(item.text for item in result.words) == (
            '"Lantern', "glows", '"tonight')
        assert "\t" not in result.raw_text and "\n5\t" not in result.raw_text
        assert decide_text(result, result, qualified_region=True).reason == "ACCEPTED"


def test_punctuation_names_and_distinct_lines_are_preserved() -> None:
    result = parse_tesseract_tsv(
        tsv(word(1, "O'Mar"), word(2, "‘Lám’"), word(1, "waits.", line=2)),
        width=400, height=100, margin=3)
    assert result.raw_text == "O'Mar ‘Lám’\nwaits."
    assert decide_text(result, result, qualified_region=True).accepted_text == result.raw_text


def test_real_low_confidence_and_clipped_words_still_fail_closed() -> None:
    low = parse_tesseract_tsv(tsv(word(1, "Arin", 14.8)),
                               width=400, height=100, margin=3)
    assert decide_text(low, low, qualified_region=True).reason == "LOW_OCR_CONFIDENCE"
    clipped = parse_tesseract_tsv(
        tsv((5, 1, 1, 1, 1, 1, 1, 20, 30, 14, 97, "Arin")),
        width=400, height=100, margin=3)
    assert decide_text(clipped, clipped,
                       qualified_region=True).reason == "INCOMPLETE_OR_INVALID_WORD"


def test_empty_or_negative_confidence_word_cannot_be_silently_dropped() -> None:
    result = parse_tesseract_tsv(
        tsv(word(1, "Lantern"), word(2, "", -1)),
        width=400, height=100, margin=3)
    assert result.raw_text == "Lantern"
    assert len(result.words) == 2
    assert decide_text(result, result,
                       qualified_region=True).reason == "INCOMPLETE_OR_INVALID_WORD"


@pytest.mark.parametrize("payload", [
    b"not-a-tesseract-header\n",
    tsv(word(1, "lantern")[:-1]),
    tsv(word(1, "lantern\textra")),
    tsv((5, 1, 1, 1, 1, 1, "bad-x", 20, 30, 14, 96, "lantern")),
])
def test_malformed_rows_fail_closed(payload: bytes) -> None:
    with pytest.raises(ValueError, match="OCR_TSV_"):
        parse_tesseract_tsv(payload, width=400, height=100, margin=3)
