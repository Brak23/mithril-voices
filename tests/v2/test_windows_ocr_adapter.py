"""Synthetic contract checks for the optional in-memory Windows OCR adapter."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from lvc.platform.windows import windows_ocr


def test_helper_is_optional_and_does_not_invoke_runner(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(windows_ocr, "NATIVE_OCR_HELPER", tmp_path / "missing.exe")

    def unexpected(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("missing helper must not run")

    with pytest.raises(RuntimeError, match="WINDOWS_OCR_UNAVAILABLE"):
        windows_ocr.recognize_windows(Image.new("RGB", (80, 50)), unexpected)


def test_unreviewed_helper_is_not_executed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_bytes(b"unreviewed synthetic file")
    monkeypatch.setattr(windows_ocr, "NATIVE_OCR_HELPER", helper)

    def unexpected(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("hash mismatch must not run")

    with pytest.raises(RuntimeError, match="WINDOWS_OCR_HELPER_UNVERIFIED"):
        windows_ocr.recognize_windows(Image.new("RGB", (80, 50)), unexpected)


def test_adapter_sends_png_only_to_bounded_local_child(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_bytes(b"synthetic placeholder; never executed")
    monkeypatch.setattr(windows_ocr, "NATIVE_OCR_HELPER", helper)
    monkeypatch.setattr(windows_ocr, "EXPECTED_NATIVE_OCR_SHA256",
                        windows_ocr.hashlib.sha256(helper.read_bytes()).hexdigest())
    calls: list[bytes] = []

    def fake(command: list[str], *, input: bytes, capture_output: bool,
             timeout: float, check: bool) -> subprocess.CompletedProcess[bytes]:
        assert command == [str(helper)]
        assert capture_output and timeout == 3 and not check
        assert input.startswith(b"\x89PNG\r\n\x1a\n")
        calls.append(input)
        return subprocess.CompletedProcess(command, 0, "Lánterns glow".encode())

    assert windows_ocr.recognize_windows(Image.new("RGB", (80, 50)), fake) == "Lánterns glow"
    assert len(calls) == 1


@pytest.mark.parametrize("code,payload,error", [
    (5, b"", "WINDOWS_OCR_FAILED"),
    (0, b"\xff", "WINDOWS_OCR_OUTPUT_INVALID"),
    (0, b"X" * (windows_ocr.MAX_TEXT_BYTES + 1), "WINDOWS_OCR_OUTPUT_TOO_LARGE"),
], ids=["child-failure", "invalid-utf8", "oversized-output"])
def test_failure_and_malformed_output_abstain(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        code: int, payload: bytes, error: str) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_bytes(b"synthetic placeholder; never executed")
    monkeypatch.setattr(windows_ocr, "NATIVE_OCR_HELPER", helper)
    monkeypatch.setattr(windows_ocr, "EXPECTED_NATIVE_OCR_SHA256",
                        windows_ocr.hashlib.sha256(helper.read_bytes()).hexdigest())

    def fake(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, code, payload)

    with pytest.raises((RuntimeError, ValueError), match=error):
        windows_ocr.recognize_windows(Image.new("RGB", (80, 50)), fake)


def test_missing_language_and_timeout_are_reported_without_fallback(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_bytes(b"synthetic placeholder; never executed")
    monkeypatch.setattr(windows_ocr, "NATIVE_OCR_HELPER", helper)
    monkeypatch.setattr(windows_ocr, "EXPECTED_NATIVE_OCR_SHA256",
                        windows_ocr.hashlib.sha256(helper.read_bytes()).hexdigest())

    def missing(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 3, b"", b"ENGLISH_OCR_UNAVAILABLE\n")

    with pytest.raises(RuntimeError, match="WINDOWS_OCR_UNAVAILABLE"):
        windows_ocr.recognize_windows(Image.new("RGB", (80, 50)), missing)

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise RuntimeError("OCR_TIMEOUT")

    with pytest.raises(RuntimeError, match="WINDOWS_OCR_TIMEOUT"):
        windows_ocr.recognize_windows(Image.new("RGB", (80, 50)), timeout)
