"""Conservative two-pass OCR admission for synthetic, already-qualified crops."""
from __future__ import annotations

import statistics
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class OcrWord:
    text: str
    confidence: float
    clipped: bool = False


@dataclass(frozen=True)
class OcrPass:
    raw_text: str
    words: tuple[OcrWord, ...]


@dataclass(frozen=True)
class TextDecision:
    raw_text: str
    accepted_text: str | None
    reason: str


def decide_text(first: OcrPass, alternative: OcrPass,
                *, qualified_region: bool) -> TextDecision:
    """Preserve the first pass verbatim; abstain on uncertainty or disagreement."""
    preview = first.raw_text
    if not qualified_region:
        return TextDecision(preview, None, "GEOMETRY_INVALID")
    if (not first.raw_text.strip() or not alternative.raw_text.strip()
            or not first.words or not alternative.words):
        return TextDecision(preview, None, "EMPTY_OCR_OUTPUT")
    for result in (first, alternative):
        if tuple(result.raw_text.split()) != tuple(word.text for word in result.words):
            return TextDecision(preview, None, "INCOMPLETE_OR_INVALID_WORD")
        if (any(word.clipped or not word.text.strip() or not 0 <= word.confidence <= 100
                for word in result.words)):
            return TextDecision(preview, None, "INCOMPLETE_OR_INVALID_WORD")
        scores = [word.confidence for word in result.words
                  if any(character.isalnum() for character in word.text)]
        if not scores or min(scores) < 40 or statistics.median(scores) < 85:
            return TextDecision(preview, None, "LOW_OCR_CONFIDENCE")
    tokens = lambda result: tuple(unicodedata.normalize("NFC", word.text).casefold()
                                  for word in result.words)
    if tokens(first) != tokens(alternative):
        return TextDecision(preview, None, "OCR_PASS_DISAGREEMENT")
    return TextDecision(preview, preview, "ACCEPTED")
