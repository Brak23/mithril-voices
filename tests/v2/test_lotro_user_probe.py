"""Synthetic tests of the user-run handoff; never enumerate or capture windows."""
from __future__ import annotations

import struct
import subprocess

import pytest
from PIL import Image

from lvc.platform.windows import lotro_user_probe as probe


def candidate(path: str = r"C:\Games\LOTRO\lotroclient64.exe") -> probe.Candidate:
    return probe.Candidate(1001, 2002, 3003, path, "a title", 800, 600)


def test_native_command_requires_approved_executable_and_exact_identity() -> None:
    assert probe.native_command(candidate())[1:] == [
        "--explicit-lotro-window", "1001", "2002", "3003",
        r"C:\Games\LOTRO\lotroclient64.exe",
    ]
    for other in (r"C:\Games\Other\notepad.exe", r"C:\Games\LOTRO\lotroclient.exe"):
        with pytest.raises(ValueError):
            probe.native_command(candidate(other))


def test_frame_decoder_rejects_missing_truncated_and_oversized_data() -> None:
    valid = b"LVCF" + struct.pack("<II", 2, 2) + bytes(range(12))
    assert probe.decode_frame(valid).size == (2, 2)
    for invalid in (b"", valid[:-1], b"NOTF" + valid[4:],
                    b"LVCF" + struct.pack("<II", 9000, 9000)):
        with pytest.raises(ValueError):
            probe.decode_frame(invalid)


def test_crop_mapping_clamps_to_frame_and_rejects_tiny_selection() -> None:
    assert probe.display_crop_to_frame(10, 20, 110, 120, 0.5, 200, 200) == (
        probe.PixelRect(20, 40, 180, 160))
    assert probe.display_crop_to_frame(10, 10, 12, 12, 1, 200, 200) is None
    assert probe.display_crop_to_frame(10, 10, 100, 100, 0, 200, 200) is None


def test_ocr_pass_uses_binary_stdin_and_preserves_local_words(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bytes]] = []
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t10\t10\t20\t10\t96\tHello\n"
           "5\t1\t1\t1\t1\t2\t35\t10\t20\t10\t95\tworld\n")

    def fake_run(command: list[str], *, input: bytes, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, input))
        return subprocess.CompletedProcess(command, 0, tsv.encode(), b"")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.recognize(Image.new("RGB", (100, 60), "white"), alternative=False)
    assert result.raw_text == "Hello world"
    assert tuple(word.text for word in result.words) == ("Hello", "world")
    assert all(not word.clipped for word in result.words)
    assert calls[0][0][1:3] == ["stdin", "stdout"]
    assert calls[0][1].startswith(b"\x89PNG\r\n\x1a\n")
