"""Bounded stream protocol and fail-closed focus behavior without LOTRO."""
from __future__ import annotations

import hashlib
import io
import struct
from pathlib import Path

import pytest

from lvc.platform.windows import lotro_observation_ui as module
from lvc.platform.windows.lotro_user_probe import Candidate


class FakeProcess:
    def __init__(self, output: bytes) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output)
        self.killed = False

    def poll(self) -> int | None:
        return -1 if self.killed else None

    def kill(self) -> None:
        self.killed = True


def frame() -> bytes:
    width, height = 800, 500
    return b"LVCF" + struct.pack("<II", width, height) + b"\x20" * (width * height * 3)


def test_one_owned_session_serves_frames_then_focus_loss_stops_without_retry(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selected = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    helper = tmp_path / "stream.exe"
    helper.write_bytes(b"reviewed fixture helper")
    monkeypatch.setattr(module, "STREAM_PROBE", helper)
    monkeypatch.setattr(module, "EXPECTED_STREAM_SHA256",
                        hashlib.sha256(helper.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "candidate_for_hwnd", lambda _hwnd: selected)
    monkeypatch.setattr(module, "window_dpi", lambda _candidate: 96)
    monkeypatch.setattr(module, "stream_command", lambda _candidate: [str(helper)])
    child = FakeProcess(b"READY\n" + frame() + frame() +
                        b"LVCE" + struct.pack("<II", 1, 0))
    launches: list[int] = []

    def launch(*_args, **_kwargs) -> FakeProcess:
        launches.append(1)
        return child

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    runner = module.StreamCaptureRunner()
    runner.streaming = True
    for _ in range(2):
        image, dpi = runner.capture(selected)
        assert image.size == (800, 500) and dpi == 96
    assert launches == [1]
    assert child.stdin.getvalue() == b"FRAME\nFRAME\n"
    assert runner.session_active
    with pytest.raises(RuntimeError, match="SELECTED_WINDOW_NOT_FOREGROUND"):
        runner.capture(selected)
    assert child.killed and not runner.session_active
    assert launches == [1]  # No silent restart after focus loss.


def test_stream_rejects_changed_identity_and_malformed_frame(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selected = Candidate(10, 20, 30, "C:/lotroclient64.exe", "Synthetic", 800, 500)
    helper = tmp_path / "stream.exe"
    helper.write_bytes(b"fixture")
    monkeypatch.setattr(module, "STREAM_PROBE", helper)
    monkeypatch.setattr(module, "EXPECTED_STREAM_SHA256",
                        hashlib.sha256(helper.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "window_dpi", lambda _candidate: 96)
    monkeypatch.setattr(module, "stream_command", lambda _candidate: [str(helper)])
    monkeypatch.setattr(module, "candidate_for_hwnd", lambda _hwnd: selected)
    child = FakeProcess(b"READY\nINVALIDFRAME")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kw: child)
    runner = module.StreamCaptureRunner()
    runner.streaming = True
    with pytest.raises(RuntimeError, match="CAPTURE_SESSION_INVALID_FRAME"):
        runner.capture(selected)
    assert child.killed
    monkeypatch.setattr(module, "candidate_for_hwnd", lambda _hwnd: None)
    runner.reset()
    runner.streaming = True
    with pytest.raises(RuntimeError, match="WINDOW_IDENTITY_OR_SIZE_CHANGED"):
        runner.capture(selected)


def test_old_capture_failure_cannot_kill_new_session() -> None:
    runner = module.StreamCaptureRunner()
    old = FakeProcess(b"")
    new = FakeProcess(b"")
    runner._process = old  # type: ignore[assignment]
    runner.cancel()
    assert old.killed
    runner.reset()
    runner.streaming = True
    runner.session_active = True
    runner._process = new  # type: ignore[assignment]
    runner._discard(old)  # old capture worker fails after Stop and restart
    assert not new.killed
    assert runner._process is new
    assert runner.session_active
    assert not runner._cancelled.is_set()
