"""Pure source comparison and human review state for the manual OCR preview."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from lvc.vision.binding import PixelRect

MAX_REVIEW_CHARACTERS = 10_000


def disagreement_spans(first: str, second: str) -> tuple[
    tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]
]:
    """Return character ranges of differing nonspace tokens in each raw source."""
    left = tuple(re.finditer(r"\S+", first))
    right = tuple(re.finditer(r"\S+", second))
    matcher = SequenceMatcher(None, [token.group() for token in left],
                              [token.group() for token in right], autojunk=False)
    left_spans: list[tuple[int, int]] = []
    right_spans: list[tuple[int, int]] = []
    for operation, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        left_spans.extend((left[i].start(), left[i].end())
                          for i in range(a_start, a_end))
        right_spans.extend((right[i].start(), right[i].end())
                           for i in range(b_start, b_end))
    return tuple(left_spans), tuple(right_spans)


@dataclass(frozen=True)
class ReviewState:
    """Sources are immutable guesses; editing and confirmation never alter them."""

    crop: PixelRect | None = None
    tesseract_source: str | None = None
    windows_source: str | None = None
    draft: str = ""
    confirmed: bool = False

    @classmethod
    def empty(cls) -> ReviewState:
        return cls()

    def load(self, crop: PixelRect, tesseract: str | None,
             windows: str | None) -> ReviewState:
        draft = windows if windows and windows.strip() else tesseract or ""
        return ReviewState(crop, tesseract, windows, draft, False)

    def edit(self, text: str) -> ReviewState:
        return replace(self, draft=text, confirmed=False)

    def confirm(self) -> ReviewState:
        if not self.can_confirm:
            return replace(self, confirmed=False)
        return replace(self, confirmed=True)

    def invalidate(self) -> ReviewState:
        return ReviewState.empty()

    @property
    def can_confirm(self) -> bool:
        return (self.crop is not None and bool(self.tesseract_source or self.windows_source)
                and bool(self.draft.strip()) and len(self.draft) <= MAX_REVIEW_CHARACTERS)

    @property
    def automated_acceptance(self) -> bool:
        """This manual preview has no authority to admit automatic narration."""
        return False
