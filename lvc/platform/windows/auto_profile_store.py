"""Geometry-only Auto boxes shared across immutable local builds.

The file key binds the approved game installation and capture geometry, not a
transient HWND or PID. Anchor pixels and safety-sample authority stay in memory.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from lvc.platform.windows.lotro_user_probe import (
    TASK_ROOT,
    Candidate,
    approved_executable,
)
from lvc.vision.auto_calibration import Calibration, load_profile, save_profile

STATE_ROOT = TASK_ROOT / "mithril-auto-state"
LEGACY_PROFILE = STATE_ROOT / "legacy-calibration.json"


def profile_path(candidate: Candidate, frame: Image.Image, dpi: int,
                 *, root: Path = STATE_ROOT) -> Path:
    if not approved_executable(candidate.executable_path) or not 48 <= dpi <= 960:
        raise ValueError("CALIBRATION_BINDING_INVALID")
    binding = [candidate.executable_path.casefold(), frame.width, frame.height,
               candidate.client_width, candidate.client_height, dpi]
    digest = hashlib.sha256(json.dumps(binding, separators=(",", ":"),
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    return root / f"calibration-{digest}.json"


def load_saved(candidate: Candidate, frame: Image.Image, dpi: int,
               *, root: Path = STATE_ROOT) -> tuple[Calibration | None, str]:
    path = profile_path(candidate, frame, dpi, root=root)
    if path.exists():
        try:
            saved = load_profile(path)
            if saved.matches(frame, candidate.client_width, candidate.client_height, dpi):
                return saved, "SAVED_BOXES_LOADED"
        except (OSError, ValueError):
            pass
        return None, "SAVED_BOXES_INVALID"
    try:
        legacy = load_profile(root / LEGACY_PROFILE.name)
        if legacy.matches(frame, candidate.client_width, candidate.client_height, dpi):
            return legacy, "PREVIOUS_BOXES_LOADED"
    except (OSError, ValueError):
        pass
    return None, "NO_SAVED_BOXES_FOR_GEOMETRY"


def save_saved(candidate: Candidate, frame: Image.Image, dpi: int,
               profile: Calibration, *, root: Path = STATE_ROOT) -> Path:
    if not profile.matches(frame, candidate.client_width, candidate.client_height, dpi):
        raise ValueError("CALIBRATION_BINDING_INVALID")
    path = profile_path(candidate, frame, dpi, root=root)
    save_profile(path, profile)
    return path
