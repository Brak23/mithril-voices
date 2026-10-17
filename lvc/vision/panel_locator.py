"""Replaceable local panel localization contract and conservative visual baseline.

The template locator is a box-only preview. Its similarity is not a calibrated
probability or authority to start automatic speech on a new layout.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import cv2
import numpy as np
from PIL import Image

from lvc.vision.auto_calibration import Calibration, region
from lvc.vision.binding import PixelRect

FindingReason = Literal["FOUND", "NOT_FOUND", "AMBIGUOUS", "UNSUPPORTED"]
SCALES = (0.85, 1.0, 1.15)
MIN_SIMILARITY = 0.88
MIN_LEAD = 0.06
MAX_FRAME_PIXELS = 12_000_000


@dataclass(frozen=True)
class PanelFinding:
    reason: FindingReason
    similarity: float
    anchor: PixelRect | None = None
    panel: PixelRect | None = None
    body: PixelRect | None = None
    scale: float | None = None


class PanelLocator(Protocol):
    def locate(self, frame: Image.Image,
               previous: PixelRect | None = None) -> PanelFinding: ...


class TemplatePanelLocator:
    """Find a distinctive session anchor, then map the body relative to it."""

    def __init__(self, calibration_frame: Image.Image, profile: Calibration) -> None:
        if not profile.matches(calibration_frame, profile.client_width,
                               profile.client_height, profile.dpi):
            raise ValueError("DETECTOR_CALIBRATION_INVALID")
        patch = region(calibration_frame, profile.anchor).convert("L")
        self.template = np.frombuffer(patch.tobytes(), dtype=np.uint8).reshape(
            patch.height, patch.width).copy()
        if float(np.std(self.template)) < 12:
            raise ValueError("DETECTOR_ANCHOR_NOT_DISTINCTIVE")
        self.anchor = profile.anchor
        self.body = profile.body

    def _proposals(self, pixels: np.ndarray, offset_x: int, offset_y: int,
                   scales: tuple[float, ...]) -> list[tuple[float, PixelRect, float]]:
        found: list[tuple[float, PixelRect, float]] = []
        for scale in scales:
            width = round(self.anchor.width * scale)
            height = round(self.anchor.height * scale)
            if width < 16 or height < 16 or width > pixels.shape[1] or height > pixels.shape[0]:
                continue
            sample = cv2.resize(self.template, (width, height), interpolation=cv2.INTER_AREA)
            if float(np.std(sample)) < 10:
                continue
            scores = cv2.matchTemplate(pixels, sample, cv2.TM_CCOEFF_NORMED)
            for _ in range(2):
                _, score, _, at = cv2.minMaxLoc(scores)
                if not np.isfinite(score):
                    break
                rect = PixelRect(offset_x + at[0], offset_y + at[1], width, height)
                found.append((float(score), rect, scale))
                left = max(0, at[0] - width)
                top = max(0, at[1] - height)
                right = min(scores.shape[1], at[0] + width + 1)
                bottom = min(scores.shape[0], at[1] + height + 1)
                scores[top:bottom, left:right] = -1
        return found

    def locate(self, frame: Image.Image,
               previous: PixelRect | None = None) -> PanelFinding:
        if (frame.width < 100 or frame.height < 100
                or frame.width * frame.height > MAX_FRAME_PIXELS):
            return PanelFinding("UNSUPPORTED", 0)
        pixels = np.frombuffer(frame.convert("L").tobytes(), dtype=np.uint8).reshape(
            frame.height, frame.width)
        proposals: list[tuple[float, PixelRect, float]] = []
        if previous is not None and previous.inside(frame.width, frame.height):
            pad_x = max(2 * previous.width, 60)
            pad_y = max(2 * previous.height, 60)
            left = max(0, previous.x - pad_x)
            top = max(0, previous.y - pad_y)
            right = min(frame.width, previous.x + previous.width + pad_x)
            bottom = min(frame.height, previous.y + previous.height + pad_y)
            proposals = self._proposals(pixels[top:bottom, left:right], left, top, SCALES)
        if not proposals or max(item[0] for item in proposals) < MIN_SIMILARITY:
            proposals = self._proposals(pixels, 0, 0, SCALES)
        if not proposals:
            return PanelFinding("NOT_FOUND", 0)
        proposals.sort(key=lambda item: item[0], reverse=True)
        score, anchor, scale = proposals[0]
        if score < MIN_SIMILARITY:
            return PanelFinding("NOT_FOUND", score)
        distinct = [item for item in proposals[1:] if
                    abs(item[1].x - anchor.x) > max(item[1].width, anchor.width)
                    or abs(item[1].y - anchor.y) > max(item[1].height, anchor.height)]
        if distinct and score - distinct[0][0] < MIN_LEAD:
            return PanelFinding("AMBIGUOUS", score)
        body = PixelRect(
            anchor.x + round((self.body.x - self.anchor.x) * scale),
            anchor.y + round((self.body.y - self.anchor.y) * scale),
            round(self.body.width * scale), round(self.body.height * scale))
        if not body.inside(frame.width, frame.height) or body.width * body.height > 2_000_000:
            return PanelFinding("UNSUPPORTED", score)
        margin = round(12 * scale)
        left = max(0, min(anchor.x, body.x) - margin)
        top = max(0, min(anchor.y, body.y) - margin)
        right = min(frame.width, max(anchor.x + anchor.width, body.x + body.width) + margin)
        bottom = min(frame.height, max(anchor.y + anchor.height, body.y + body.height) + margin)
        panel = PixelRect(left, top, right - left, bottom - top)
        return PanelFinding("FOUND", score, anchor, panel, body, scale)
