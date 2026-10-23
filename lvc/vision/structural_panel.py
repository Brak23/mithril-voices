"""Color-independent two-column quest-panel proposals in physical pixels.

This is a conservative visual baseline, not a quest classifier. A candidate
requires independently found column boundaries and corroborating horizontal
structure. Its score is a ranking heuristic, never a probability of a quest.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from lvc.vision.binding import PixelRect
from lvc.vision.text_gate import OcrPass

MAX_PIXELS = 12_000_000


@dataclass(frozen=True)
class PanelProposal:
    panel: PixelRect
    body: PixelRect
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class PanelDetection:
    reason: str
    candidates: tuple[PanelProposal, ...]

    @property
    def selected(self) -> PanelProposal | None:
        return self.candidates[0] if self.reason == "FOUND" else None


class QuestPanelDetector(Protocol):
    """Shared interface for structural and later rights-cleared learned models."""

    def detect(self, frame: Image.Image) -> PanelDetection: ...


def readable_body(passage: OcrPass) -> bool:
    """Admit a paragraph layout without depending on language or button text."""
    words = [word for word in passage.words
             if any(character.isalnum() for character in word.text)]
    return (len(words) >= 8 and len(passage.raw_text.splitlines()) >= 2
            and not any(word.clipped for word in passage.words)
            and min(word.confidence for word in words) >= 15
            and median(word.confidence for word in words) >= 75)


def body_retains_reference(broad: OcrPass, candidate: OcrPass) -> bool:
    """Abstain if a clean word in the broad pane disappeared from the crop."""
    def tokens(passage: OcrPass, confidence: float) -> Counter[str]:
        return Counter("".join(char.casefold() for char in word.text if char.isalnum())
                       for word in passage.words
                       if word.confidence >= confidence and not word.clipped
                       and any(char.isalnum() for char in word.text))

    source = tokens(broad, 50)
    kept = tokens(candidate, 15)
    total = source.total()
    return total >= 8 and (source & kept).total() / total >= .98


def _clear_crop_edges(gray: np.ndarray, rect: PixelRect) -> bool:
    """Apply the existing edge-color gate to one panel-local rectangle."""
    crop = gray[rect.y:rect.y + rect.height, rect.x:rect.x + rect.width]
    if crop.shape != (rect.height, rect.width):
        return False
    corners = crop[np.ix_([0, 1, -2, -1], [0, 1, -2, -1])]
    background = float(np.median(corners))
    border = np.concatenate((crop[:2, :].ravel(), crop[-2:, :].ravel(),
                             crop[2:-2, :2].ravel(), crop[2:-2, -2:].ravel()))
    return bool(np.all(np.abs(border.astype(np.int16) - background) < 75))


def edge_checked_body(frame: Image.Image, proposal: PanelProposal) -> PixelRect | None:
    """Find the largest clear-edged narrative crop inside a geometric proposal.

    Lower quest controls can occupy a different share of a resized panel. This
    bounded native-pixel search keeps the longest usable body, and abstains if
    no crop clears the same border gate used by the Windows OCR adapter.
    """
    panel, broad = proposal.panel, proposal.body
    if not panel.inside(*frame.size) or not broad.inside(*frame.size):
        return None
    if broad.width * broad.height > 2_000_000:
        return None
    gray = np.asarray(frame.crop((panel.x, panel.y, panel.x + panel.width,
                                  panel.y + panel.height)).convert("L"))
    best: PixelRect | None = None
    best_area = 0
    for side in (0, .02, .04, .06, .08):
        shift = round(broad.width * side)
        left, right = broad.x + shift, broad.x + broad.width - shift
        for top in (0, .02, .04, .06):
            upper = broad.y + round(panel.height * top)
            for fraction in (.78, .82, .86, .90, .94, .98):
                lower = min(broad.y + broad.height,
                            panel.y + round(panel.height * fraction))
                width, height = right - left, lower - upper
                area = width * height
                if area <= best_area or width < 250 or height < 250:
                    continue
                candidate = PixelRect(left, upper, width, height)
                local = PixelRect(left - panel.x, upper - panel.y, width, height)
                if _clear_crop_edges(gray, local):
                    best, best_area = candidate, area
    if best_area < broad.width * broad.height * .65:
        return None
    return best


def _independent_lines(lines: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    chosen: list[tuple[int, int, int]] = []
    for line in sorted(lines, key=lambda item: item[2] - item[1], reverse=True):
        if not any(abs(line[0] - previous[0]) <= 12 for previous in chosen):
            chosen.append(line)
    return sorted(chosen)


def _overlap(first: PixelRect, second: PixelRect) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    area = max(0, right - left) * max(0, bottom - top)
    union = first.width * first.height + second.width * second.height - area
    return area / union if union else 0.0


def _bar_support(horizontal: list[tuple[int, int, int]], edges: np.ndarray,
                 *, boundary: int, left: int, middle: int,
                 right: int, height: int) -> bool:
    width = right - left
    radius = max(65, round(height * 0.13))
    nearby = [(y, begin, end) for y, begin, end in horizontal
              if abs(y - boundary) <= radius]
    if any(begin <= left + round(width * 0.12)
           and end >= right - round(width * 0.12)
           for _, begin, end in nearby):
        return True
    first = [(y, begin, end) for y, begin, end in nearby
             if begin <= left + round(width * 0.08)
             and end >= middle - round(width * 0.05)]
    second = [(y, begin, end) for y, begin, end in nearby
              if begin <= middle + round(width * 0.05)
              and end >= right - round(width * 0.08)]
    if any(abs(one[0] - two[0]) <= 10 for one in first for two in second):
        return True
    # Hough sometimes keeps one of two equal length bars. An edge row still
    # needs visible coverage at both ends, so an adjacent pane cannot lend it.
    band = max(20, round(width * 0.1))
    for y in range(max(0, boundary - radius),
                   min(edges.shape[0], boundary + radius + 1)):
        row = edges[y, left:right] != 0
        if (np.mean(row) >= 0.55 and np.mean(row[:band]) >= 0.4
                and np.mean(row[-band:]) >= 0.4):
            return True
    return False


def _aligned_inner_top(horizontal: list[tuple[int, int, int]],
                       left: tuple[int, int, int], middle: tuple[int, int, int],
                       right: tuple[int, int, int]) -> bool:
    """Corroborate either complete column top when a full stroke is absent."""
    for first, second, spanning in ((left, middle, right),
                                    (middle, right, left)):
        pair_top = max(first[1], second[1])
        pair_bottom = min(first[2], second[2])
        if (abs(first[1] - second[1]) > 12
                or abs(first[2] - second[2]) > 12
                or spanning[1] > pair_top + 20
                or spanning[2] < pair_bottom - 20):
            continue
        width = second[0] - first[0]
        if any(abs(y - pair_top) <= 12
               and begin <= first[0] + round(width * .07)
               and end >= second[0] - round(width * .07)
               for y, begin, end in horizontal):
            return True
    return False


class StructuralPanelDetector:
    """Find a tall narrative column beside a shorter objective column.

    No whole-frame resize, color test, remembered location, or font assumption
    is involved. Borderless or single-column skins may correctly abstain.
    """

    def detect(self, frame: Image.Image) -> PanelDetection:
        if (frame.width < 400 or frame.height < 300
                or frame.width * frame.height > MAX_PIXELS):
            return PanelDetection("UNSUPPORTED", ())
        gray = cv2.cvtColor(np.asarray(frame.convert("RGB")), cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 40, 110)
        raw = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=75,
                              minLineLength=120, maxLineGap=18)
        if raw is None:
            return PanelDetection("NOT_FOUND", ())
        vertical: list[tuple[int, int, int]] = []
        horizontal: list[tuple[int, int, int]] = []
        for x1, y1, x2, y2 in raw[:, 0, :]:
            if abs(x2 - x1) <= 3 and abs(y2 - y1) >= 120:
                vertical.append((int(x1), int(min(y1, y2)), int(max(y1, y2))))
            elif abs(y2 - y1) <= 3 and abs(x2 - x1) >= 120:
                horizontal.append((int(y1), int(min(x1, x2)), int(max(x1, x2))))
        boundaries = _independent_lines(vertical)
        proposals: list[PanelProposal] = []
        for ai, left in enumerate(boundaries):
            for bi in range(ai + 1, len(boundaries)):
                middle = boundaries[bi]
                left_width = middle[0] - left[0]
                if left_width < 150:
                    continue
                for right in boundaries[bi + 1:]:
                    side_width = right[0] - middle[0]
                    if side_width < 90 or not 0.85 <= left_width / side_width <= 4.5:
                        continue
                    top = max(left[1], middle[1], right[1])
                    bottom = min(left[2], middle[2], right[2])
                    height = bottom - top
                    width = right[0] - left[0]
                    if height < 250 or not 0.6 <= width / height <= 3.0:
                        continue
                    top_bar = _bar_support(horizontal, edges, boundary=top,
                                           left=left[0], middle=middle[0],
                                           right=right[0], height=height)
                    bottom_bar = _bar_support(horizontal, edges, boundary=bottom,
                                              left=left[0], middle=middle[0],
                                              right=right[0], height=height)
                    inner_top = _aligned_inner_top(horizontal, left, middle, right)
                    if not bottom_bar or not (top_bar or inner_top):
                        continue
                    inset = max(7, round(left_width * 0.018))
                    left_inset = max(3, round(left_width * 0.005))
                    body = PixelRect(left[0] + left_inset, top + inset,
                                     left_width - left_inset - inset,
                                     height - 2 * inset)
                    panel = PixelRect(left[0], top, width, height)
                    if (not body.inside(*frame.size) or body.width < 250
                            or body.height < 250):
                        continue
                    # Ranking is structural only. A user-labeled negative and
                    # readable-body gate must qualify any speech use separately.
                    score = min(0.99, 0.82 + 0.1 * min(1.0, height / 700)
                                + (0.02 if inner_top else 0.0))
                    proposals.append(PanelProposal(
                        panel, body, score, ("three-column-edges", "bottom-crossbar",
                                             "aligned-inner-top" if inner_top
                                             else "top-crossbar")))
        proposals.sort(key=lambda item: item.score, reverse=True)
        unique: list[PanelProposal] = []
        for proposal in proposals:
            if not any(_overlap(proposal.panel, other.panel) >= 0.65 for other in unique):
                unique.append(proposal)
            if len(unique) == 5:
                break
        if not unique:
            return PanelDetection("NOT_FOUND", ())
        if len(unique) > 1:
            return PanelDetection("AMBIGUOUS", tuple(unique))
        return PanelDetection("FOUND", tuple(unique))


class StructuralSessionGuard:
    """A fresh positive plus two distinct absence checks for one armed session."""

    LABELS = frozenset({"closed-control", "journal-control"})

    def __init__(self, detector: QuestPanelDetector, positive: Image.Image) -> None:
        found = detector.detect(positive)
        if found.selected is None:
            raise ValueError("STRUCTURAL_POSITIVE_NOT_UNIQUE")
        self.detector = detector
        self.size = positive.size
        self.positive = found.selected
        self.negatives: set[str] = set()

    @property
    def ready(self) -> bool:
        return self.negatives == self.LABELS

    def negative(self, label: str, frame: Image.Image) -> bool:
        if label not in self.LABELS or frame.size != self.size:
            raise ValueError("STRUCTURAL_NEGATIVE_INVALID")
        clear = self.detector.detect(frame).reason == "NOT_FOUND"
        if clear:
            self.negatives.add(label)
        else:
            self.negatives.discard(label)
        return clear

    def locate(self, frame: Image.Image) -> PanelProposal | None:
        if not self.ready or frame.size != self.size:
            return None
        return self.detector.detect(frame).selected
