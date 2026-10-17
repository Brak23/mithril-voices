"""Local Windows OCR for a body crop qualified independently as a quest panel."""
from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageOps

from lvc.platform.windows.lotro_probe_ui import OcrCancelled, OcrProcessRunner
from lvc.platform.windows.windows_ocr import recognize_windows
from lvc.vision.text_gate import TextDecision
from lvc.vision.windows_text_gate import crop_edge_clear, decide_windows_text


def recognize_auto_crop(
    body: Image.Image, runner: OcrProcessRunner,
    native: Callable[[Image.Image, OcrProcessRunner], str] = recognize_windows,
) -> TextDecision:
    """Two input variants check consistency; neither result gives confidence."""
    if not crop_edge_clear(body):
        return decide_windows_text("", "", clear_edge=False)
    first = native(body, runner)
    if runner.cancelled.is_set():
        raise OcrCancelled()
    padded = ImageOps.expand(body, border=12,
                             fill=tuple(body.convert("RGB").tobytes()[:3]))
    second = native(padded, runner)
    if runner.cancelled.is_set():
        raise OcrCancelled()
    return decide_windows_text(first, second, clear_edge=True)
