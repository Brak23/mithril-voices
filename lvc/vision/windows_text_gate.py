"""Conservative admission for Windows OCR on an already identified quest body.

Windows.Media.Ocr returns text through the current local helper, without word
confidence or geometry. These checks are abstention heuristics, not a claim of
OCR confidence or proof that a quest panel was found.
"""
from __future__ import annotations

import statistics
import unicodedata

from PIL import Image

from lvc.vision.text_gate import TextDecision

MAX_AUTO_TEXT_CHARS = 3000


def crop_edge_clear(image: Image.Image) -> bool:
    """Reject a crop with foreground-like pixels touching its outer two pixels."""
    if image.width < 40 or image.height < 40 or image.width * image.height > 2_000_000:
        return False
    pixels = image.convert("L").tobytes()
    width = image.width
    corners = [pixels[y * width + x] for x in (0, 1, width - 2, width - 1)
               for y in (0, 1, image.height - 2, image.height - 1)]
    background = statistics.median(corners)
    for y in range(image.height):
        for x in (0, 1, width - 2, width - 1):
            if abs(pixels[y * width + x] - background) >= 75:
                return False
    for x in range(2, width - 2):
        for y in (0, 1, image.height - 2, image.height - 1):
            if abs(pixels[y * width + x] - background) >= 75:
                return False
    return True


def decide_windows_text(first: str, padded: str, *, clear_edge: bool) -> TextDecision:
    """Keep the first local result verbatim; abstain on missing or changed words."""
    if not clear_edge:
        return TextDecision(first, None, "CROP_EDGE_UNCLEAR")
    if not first.strip() or not padded.strip():
        return TextDecision(first, None, "EMPTY_OCR_OUTPUT")
    if (len(first) > MAX_AUTO_TEXT_CHARS or len(padded) > MAX_AUTO_TEXT_CHARS
            or any(ord(character) < 32 and character not in "\n\r\t" for character in first + padded)
            or "\ufffd" in first + padded):
        return TextDecision(first, None, "OCR_TEXT_INVALID")
    tokens = lambda value: tuple(unicodedata.normalize("NFC", word).casefold()
                                 for word in value.split())
    if tokens(first) != tokens(padded):
        return TextDecision(first, None, "OCR_VARIANT_DISAGREEMENT")
    if not any(character.isalnum() for character in first):
        return TextDecision(first, None, "OCR_TEXT_INVALID")
    return TextDecision(first, first, "ACCEPTED_WINDOWS_OCR")
