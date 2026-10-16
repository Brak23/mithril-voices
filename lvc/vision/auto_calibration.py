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
ANCHOR_SIZE = (16, 16)


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
    return region(frame, profile.anchor).convert("L").resize(ANCHOR_SIZE)


def anchor_difference(reference: Image.Image, frame: Image.Image,
                      profile: Calibration) -> float:
    if reference.mode != "L" or reference.size != ANCHOR_SIZE:
        raise ValueError("ANCHOR_REFERENCE_INVALID")
    current = anchor_signature(frame, profile)
    return ImageStat.Stat(ImageChops.difference(reference, current)).mean[0] / 255


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
