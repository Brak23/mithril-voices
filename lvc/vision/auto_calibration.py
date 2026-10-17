"""Local observation-only quest crop calibration; no saved pixels or text."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageStat

from lvc.vision.binding import PixelRect

MAX_PROFILE_BYTES = 2048
MAX_BODY_PIXELS = 2_000_000
ANCHOR_SIZE = (32, 32)
MIN_ANCHOR_STDDEV = 12.0


def selection_issue(frame: Image.Image | None, anchor: PixelRect | None,
                    body: PixelRect | None) -> str | None:
    """Give the next drawing action before constructing a saved calibration."""
    if frame is None:
        return "Capture an open quest window first, then mark the yellow and blue boxes."
    if anchor is None:
        return ("Draw the yellow box around a small corner or decorative border of the "
                "quest window. Keep changing title and dialogue words outside it.")
    if not anchor.inside(*frame.size) or anchor.width < 20 or anchor.height < 20:
        return "Redraw the yellow border box inside the image, at least 20 x 20 pixels."
    if anchor.width * anchor.height > 250_000:
        return ("The yellow box is too large. It should mark a small fixed corner or "
                "border detail, not the whole quest window. Redraw yellow and keep blue.")
    if body is None:
        return ("Switch to the blue box and draw around all dialogue words inside the "
                "quest window. The yellow box stays in place.")
    if not body.inside(*frame.size) or body.width < 20 or body.height < 20:
        return "Redraw the blue dialogue box inside the image, at least 20 x 20 pixels."
    if body.width * body.height > MAX_BODY_PIXELS:
        return ("The blue box is too large. Include the complete dialogue area, "
                "but leave out the rest of the screen and quest controls.")
    if (anchor.x < body.x + body.width and anchor.x + anchor.width > body.x
            and anchor.y < body.y + body.height and anchor.y + anchor.height > body.y):
        return ("Yellow and blue overlap. Redraw yellow on a small fixed border or "
                "corner outside the blue dialogue area. Switching colors keeps the other box.")
    return None


@dataclass(frozen=True)
class Calibration:
    frame_width: int
    frame_height: int
    client_width: int
    client_height: int
    dpi: int
    anchor: PixelRect
    body: PixelRect

    def __post_init__(self) -> None:
        if (self.frame_width < 100 or self.frame_height < 100
                or self.client_width < 100 or self.client_height < 100
                or not 48 <= self.dpi <= 960
                or not self.anchor.inside(self.frame_width, self.frame_height)
                or not self.body.inside(self.frame_width, self.frame_height)
                or self.anchor.width < 20 or self.anchor.height < 20
                or self.anchor.width * self.anchor.height > 250_000
                or self.body.width < 20 or self.body.height < 20
                or self.body.width * self.body.height > MAX_BODY_PIXELS):
            raise ValueError("CALIBRATION_INVALID")
        if (self.anchor.x < self.body.x + self.body.width
                and self.anchor.x + self.anchor.width > self.body.x
                and self.anchor.y < self.body.y + self.body.height
                and self.anchor.y + self.anchor.height > self.body.y):
            raise ValueError("CALIBRATION_REGIONS_OVERLAP")

    def matches(self, frame: Image.Image, client_width: int,
                client_height: int, dpi: int) -> bool:
        return (frame.size == (self.frame_width, self.frame_height)
                and (client_width, client_height, dpi) ==
                (self.client_width, self.client_height, self.dpi))


def region(frame: Image.Image, rect: PixelRect) -> Image.Image:
    if not rect.inside(*frame.size):
        raise ValueError("REGION_OUTSIDE_FRAME")
    return frame.crop((rect.x, rect.y, rect.x + rect.width,
                       rect.y + rect.height))


def anchor_signature(frame: Image.Image, profile: Calibration) -> Image.Image:
    if frame.size != (profile.frame_width, profile.frame_height):
        raise ValueError("FRAME_GEOMETRY_CHANGED")
    return region(frame, profile.anchor).convert("RGB").resize(ANCHOR_SIZE)


def anchor_quality_issue(frame: Image.Image, anchor: PixelRect) -> str | None:
    """Reject a plain patch that can match ordinary backgrounds at the same spot."""
    if not anchor.inside(*frame.size):
        return "Yellow box is outside the captured frame. Redraw yellow."
    sample = region(frame, anchor).convert("RGB").resize(ANCHOR_SIZE)
    if max(ImageStat.Stat(sample).stddev) < MIN_ANCHOR_STDDEV:
        return ("Yellow covers a mostly plain color. Keep blue; redraw only yellow "
                "around a visible corner, line or emblem of the quest pane, then Save.")
    return None


def anchor_difference(reference: Image.Image, frame: Image.Image,
                      profile: Calibration) -> float:
    if reference.mode != "RGB" or reference.size != ANCHOR_SIZE:
        raise ValueError("ANCHOR_REFERENCE_INVALID")
    current = anchor_signature(frame, profile)
    delta = ImageChops.difference(reference, current)
    average = sum(ImageStat.Stat(delta).mean) / (3 * 255)
    # A narrow emblem/line can disappear while most of its same-colored
    # background stays unchanged. Mean-only scoring loses that evidence.
    channels = delta.tobytes()
    pixel_changes = sorted(max(channels[index:index + 3])
                           for index in range(0, len(channels), 3))
    upper_tail = pixel_changes[int(0.95 * (len(pixel_changes) - 1))] / 255
    return max(average, upper_tail * 0.5)


def scene_fingerprint(frame: Image.Image) -> bytes:
    """Transient exact scene identity for rejecting repeated safety frames."""
    return hashlib.sha256(frame.convert("RGB").tobytes()).digest()


def body_digest(frame: Image.Image, profile: Calibration) -> str:
    return hashlib.sha256(region(frame, profile.body).convert("RGB").tobytes()).hexdigest()


def save_profile(path: Path, profile: Calibration) -> None:
    # The schema deliberately has no screenshot, OCR, window title or text field.
    def rectangle(value: PixelRect) -> list[int]:
        return [value.x, value.y, value.width, value.height]

    value = {"version": 1, "frame": [profile.frame_width, profile.frame_height],
             "client": [profile.client_width, profile.client_height],
             "dpi": profile.dpi, "anchor": rectangle(profile.anchor),
             "body": rectangle(profile.body)}
    payload = (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_PROFILE_BYTES:
        raise ValueError("CALIBRATION_TOO_LARGE")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_profile(path: Path) -> Calibration:
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ValueError("CALIBRATION_TOO_LARGE")

    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("CALIBRATION_INVALID")
            value[key] = item
        return value

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        if not isinstance(value, dict) or set(value) != {
                "version", "frame", "client", "dpi", "anchor", "body"}:
            raise ValueError("CALIBRATION_INVALID")
        vectors = (value["frame"], value["client"], value["anchor"], value["body"])
        if (type(value["version"]) is not int or value["version"] != 1
                or type(value["dpi"]) is not int
                or any(not isinstance(item, list) or len(item) != count
                       or any(type(number) is not int for number in item)
                       for item, count in zip(vectors, (2, 2, 4, 4), strict=True))):
            raise ValueError("CALIBRATION_INVALID")
        width, height = value["frame"]
        client_width, client_height = value["client"]
        return Calibration(width, height, client_width, client_height,
                           value["dpi"], PixelRect(*value["anchor"]),
                           PixelRect(*value["body"]))
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CALIBRATION_INVALID") from exc
