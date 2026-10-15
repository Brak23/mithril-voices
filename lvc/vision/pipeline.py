"""Bounded crop and OCR admission after exact-window frame validation."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lvc.vision.binding import (
    CaptureTicket,
    FrameMetadata,
    FrameStatus,
    PixelRect,
    SelectedWindow,
    WindowFacts,
)
from lvc.vision.text_gate import OcrPass, TextDecision, decide_text

MAX_FRAME_PIXELS = 8192 * 8192


Recognizer = Callable[[bytes, int, int], tuple[OcrPass, OcrPass]]


@dataclass(frozen=True)
class GrayFrame:
    metadata: FrameMetadata
    pixels: bytes


@dataclass(frozen=True)
class VisionResult:
    window: SelectedWindow
    frame_status: FrameStatus
    text: TextDecision | None


def inspect_frame(window: SelectedWindow, ticket: CaptureTicket, facts: WindowFacts,
                  frame: GrayFrame, crop: PixelRect | None,
                  recognize: Recognizer) -> VisionResult:
    """No recognizer call occurs unless provenance and the physical crop pass."""
    width, height = frame.metadata.width, frame.metadata.height
    if (width <= 0 or height <= 0 or width * height > MAX_FRAME_PIXELS
            or len(frame.pixels) != width * height):
        return VisionResult(window.suspend(), FrameStatus.GEOMETRY_INVALID, None)
    updated, status = window.accept(ticket, facts, frame.metadata, crop)
    if status is not FrameStatus.READY or crop is None:
        return VisionResult(updated, status, None)
    cropped = b"".join(frame.pixels[(crop.y + row) * width + crop.x:
                                     (crop.y + row) * width + crop.x + crop.width]
                       for row in range(crop.height))
    try:
        first, alternative = recognize(cropped, crop.width, crop.height)
    except (OSError, RuntimeError, ValueError):
        return VisionResult(updated.suspend(), FrameStatus.SUSPENDED, None)
    return VisionResult(updated, status,
                        decide_text(first, alternative, qualified_region=True))
