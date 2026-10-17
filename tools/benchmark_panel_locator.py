"""Box-only CPU timing on generated graphics, never real-game validation."""
from __future__ import annotations

import json
import statistics
import time

from PIL import Image, ImageDraw

from lvc.vision.auto_calibration import Calibration
from lvc.vision.binding import PixelRect
from lvc.vision.panel_locator import TemplatePanelLocator


def _frame(width: int, height: int, x: int, y: int) -> Image.Image:
    image = Image.new("RGB", (width, height), "#202020")
    draw = ImageDraw.Draw(image)
    draw.rectangle((x, y, x + 49, y + 49), fill="#c98c31")
    draw.line((x + 4, y + 4, x + 45, y + 45), fill="white", width=4)
    draw.ellipse((x + 13, y + 7, x + 35, y + 27), outline="black", width=3)
    draw.text((x + 70, y + 72), "Generated words", fill="white")
    return image


def run() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for width, height in ((800, 500), (2560, 1440), (5120, 1440)):
        profile = Calibration(width, height, width, height, 96,
                              PixelRect(100, 80, 50, 50),
                              PixelRect(160, 140, 310, 100))
        locator = TemplatePanelLocator(_frame(width, height, 100, 80), profile)
        x, y = width - 420, height - 260
        moved = _frame(width, height, x, y)
        discovery: list[float] = []
        tracking: list[float] = []
        for _ in range(5):
            started = time.perf_counter()
            first = locator.locate(moved)
            discovery.append((time.perf_counter() - started) * 1000)
            if first.reason != "FOUND" or first.anchor is None:
                raise RuntimeError("GENERATED_FIXTURE_NOT_FOUND")
            started = time.perf_counter()
            again = locator.locate(moved, first.anchor)
            tracking.append((time.perf_counter() - started) * 1000)
            if again.reason != "FOUND" or again.body != first.body:
                raise RuntimeError("GENERATED_TRACKING_FAILED")
        results.append({"frame": [width, height], "samples": 5,
                        "discovery_median_ms": round(statistics.median(discovery), 1),
                        "discovery_max_ms": round(max(discovery), 1),
                        "tracking_median_ms": round(statistics.median(tracking), 1),
                        "tracking_max_ms": round(max(tracking), 1),
                        "real_game_accuracy": "NOT_MEASURED"})
    return results


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
