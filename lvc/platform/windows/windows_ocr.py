"""Optional, bounded Windows.Media.Ocr adapter for one in-memory crop."""
from __future__ import annotations

import hashlib
import io
import subprocess
import unicodedata
from collections.abc import Callable
from pathlib import Path

from PIL import Image

TASK_ROOT = Path(__file__).resolve().parents[4]
NATIVE_OCR_HELPER = TASK_ROOT / "test-tmp" / "windows_ocr_stdin.exe"
EXPECTED_NATIVE_OCR_SHA256 = "159a2fc8a35e7eb9ff151b78566d6977145fa2ec2d6f40cf1ce51b261eeb87e3"
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def windows_ocr_preflight() -> None:
    """Check the exact local helper before an automatic session can arm."""
    if not NATIVE_OCR_HELPER.is_file():
        raise RuntimeError("WINDOWS_OCR_UNAVAILABLE")
    if hashlib.sha256(NATIVE_OCR_HELPER.read_bytes()).hexdigest() != EXPECTED_NATIVE_OCR_SHA256:
        raise RuntimeError("WINDOWS_OCR_HELPER_UNVERIFIED")


def recognize_windows(image: Image.Image, runner: Runner) -> str:
    """No screen access, file output, confidence score, or speech side effect."""
    windows_ocr_preflight()
    encoded = io.BytesIO()
    image.convert("RGB").save(encoded, format="PNG")
    payload = encoded.getvalue()
    if len(payload) > MAX_PNG_BYTES:
        raise ValueError("WINDOWS_OCR_INPUT_TOO_LARGE")
    try:
        completed = runner([str(NATIVE_OCR_HELPER)], input=payload,
                           capture_output=True, timeout=3, check=False)
    except RuntimeError as exc:
        if str(exc) == "OCR_TIMEOUT":
            raise RuntimeError("WINDOWS_OCR_TIMEOUT") from exc
        raise
    if completed.returncode != 0:
        if (completed.stderr or b"").strip() == b"ENGLISH_OCR_UNAVAILABLE":
            raise RuntimeError("WINDOWS_OCR_UNAVAILABLE")
        raise RuntimeError("WINDOWS_OCR_FAILED")
    if len(completed.stdout) > MAX_TEXT_BYTES:
        raise ValueError("WINDOWS_OCR_OUTPUT_TOO_LARGE")
    try:
        return unicodedata.normalize("NFC", completed.stdout.decode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("WINDOWS_OCR_OUTPUT_INVALID") from exc
