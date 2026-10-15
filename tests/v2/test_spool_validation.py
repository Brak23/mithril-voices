"""Generated Windows WAV spool outcomes; no model or physical endpoint."""
from __future__ import annotations

import hashlib
import struct
import sys
import wave
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from lvc import spool as spool_module
from lvc.core import PageIdentity, RequestToken
from lvc.spool import (
    MAX_ADMITTED_BYTES,
    MAX_UNIT_BYTES,
    MAX_UNIT_FRAMES,
    AdmittedUsage,
    InvalidSpool,
    SpoolValidator,
)
from lvc.synthetic_flow import StaleArtifact, SyntheticFlow
from tests.v2.support import RecordingSink
from tools.validate_contracts import load_json, validate_ipc

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = load_json(ROOT / "docs/design-v2/contracts/ipc.examples.json")["examples"][4]
SESSION = UUID(EXAMPLE["session_id"])
WORKER = UUID(EXAMPLE["worker_instance_id"])
REQUEST = UUID(EXAMPLE["payload"]["request_id"])
UNIT = UUID(EXAMPLE["payload"]["result"]["unit_id"])
TOKEN = RequestToken(REQUEST, SESSION, 1, 1, "manual",
                     PageIdentity(UUID(EXAMPLE["payload"]["context"]["interaction_id"]),
                                  1, "quest_body", "synthetic"))


@pytest.fixture
def spool(tmp_path: Path) -> Path:
    assert sys.platform == "win32"
    root = tmp_path / str(SESSION)
    root.mkdir()
    return root


def write_wav(root: Path, samples: tuple[int, ...] = (1000, -1000, 500, -500, 250),
              *, rate: int = 48_000, channels: int = 1, width: int = 2) -> tuple[Path, dict]:
    path = root / f"{REQUEST}.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path, descriptor(path, len(samples) // channels)


def descriptor(path: Path, frames: int) -> dict:
    raw = path.read_bytes()
    return {"kind": "audio", "unit_id": str(UNIT), "filename": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "sample_rate": 48_000, "channels": 1, "sample_format": "s16le",
            "frame_count": frames}


def verify(root: Path, result: dict, *, current=lambda: True,
           admitted: tuple[AdmittedUsage, ...] = (), text: str = "synthetic words"):
    return SpoolValidator(root, SESSION, UNIT, root.parent, admitted)(TOKEN, result, text, current)


def test_valid_generated_pcm_and_maximum_30_second_unit(spool: Path):
    _, result = write_wav(spool)
    unit = verify(spool, result)
    assert unit.frames == 5 and len(unit.pcm) == 10
    assert unit.artifact == result["sha256"]
    # This stays below the 16 MiB file cap but exercises the exact duration cap.
    samples = (1000,) * MAX_UNIT_FRAMES
    _, result = write_wav(spool, samples)
    assert verify(spool, result).frames == MAX_UNIT_FRAMES


@pytest.mark.parametrize("change", ["truncated_header", "bad_riff", "bad_riff_length",
                                    "truncated_payload", "hash_mismatch", "frame_mismatch"])
def test_malformed_or_inconsistent_wav_rejected(spool: Path, change: str):
    path, result = write_wav(spool)
    raw = bytearray(path.read_bytes())
    if change == "truncated_header":
        raw = raw[:40]
    elif change == "bad_riff":
        raw[:4] = b"NOPE"
    elif change == "bad_riff_length":
        raw[4:8] = struct.pack("<I", len(raw))
    elif change == "truncated_payload":
        raw = raw[:-2]
        raw[4:8] = struct.pack("<I", len(raw) - 8)
    elif change == "hash_mismatch":
        result["sha256"] = "0" * 64
    else:
        result["frame_count"] += 1
    if change not in {"hash_mismatch", "frame_mismatch"}:
        path.write_bytes(raw)
        result = descriptor(path, 5)
    with pytest.raises(InvalidSpool):
        verify(spool, result)


@pytest.mark.parametrize("rate,channels,width", [(44_100, 1, 2), (48_000, 2, 2),
                                                 (48_000, 1, 1)])
def test_only_mono_48k_16bit_pcm_allowed(spool: Path, rate: int, channels: int, width: int):
    _, result = write_wav(spool, rate=rate, channels=channels, width=width)
    with pytest.raises(InvalidSpool):
        verify(spool, result)


@pytest.mark.parametrize("field,value", [("sample_rate", 44_100), ("channels", 2),
                                         ("sample_format", "f32le")])
def test_descriptor_format_mismatch_rejected_before_read(spool: Path, monkeypatch,
                                                         field: str, value):
    _, result = write_wav(spool)
    result[field] = value
    monkeypatch.setattr("lvc.spool._read_owned_file", lambda *_: pytest.fail("file was read"))
    with pytest.raises(InvalidSpool):
        verify(spool, result)


def test_float_nan_wav_and_silent_nonempty_speech_rejected(spool: Path):
    path = spool / f"{REQUEST}.wav"
    fmt = struct.pack("<HHIIHH", 3, 1, 48_000, 192_000, 4, 32)
    data = struct.pack("<f", float("nan"))
    path.write_bytes(b"RIFF" + struct.pack("<I", 40) + b"WAVE"
                     + b"fmt " + struct.pack("<I", 16) + fmt
                     + b"data" + struct.pack("<I", 4) + data)
    with pytest.raises(InvalidSpool):
        verify(spool, descriptor(path, 1))
    _, silent = write_wav(spool, (0, 0, 0, 0, 0))
    with pytest.raises(InvalidSpool):
        verify(spool, silent)


@pytest.mark.parametrize("field,value", [("bytes", MAX_UNIT_BYTES + 1),
                                         ("frame_count", MAX_UNIT_FRAMES + 1)])
def test_per_unit_limits_rejected_before_file_read(spool: Path, monkeypatch,
                                                    field: str, value: int):
    _, result = write_wav(spool)
    result[field] = value
    monkeypatch.setattr("lvc.spool._read_owned_file", lambda *_: pytest.fail("file was read"))
    with pytest.raises(InvalidSpool):
        verify(spool, result)


def test_cumulative_bytes_duration_and_unit_count_checked_before_read(spool: Path,
                                                                       monkeypatch):
    _, result = write_wav(spool)
    monkeypatch.setattr("lvc.spool._read_owned_file", lambda *_: pytest.fail("file was read"))
    budgets = [
        (AdmittedUsage(MAX_ADMITTED_BYTES, 1),),
        (AdmittedUsage(1, 60 * 48_000),),
        (AdmittedUsage(1, 1), AdmittedUsage(1, 1)),
    ]
    for admitted in budgets:
        with pytest.raises(InvalidSpool):
            verify(spool, result, admitted=admitted)
    with pytest.raises(InvalidSpool):
        SpoolValidator(spool, SESSION, UNIT, spool.parent, (AdmittedUsage(-1, 1),))


def test_spool_session_must_be_direct_child_of_designated_owner(spool: Path):
    with pytest.raises(InvalidSpool):
        SpoolValidator(spool, SESSION, UNIT, spool.parent / "other")


def test_traversal_and_request_mismatch_rejected_before_open(spool: Path, monkeypatch):
    _, result = write_wav(spool)
    monkeypatch.setattr("lvc.spool._read_owned_file", lambda *_: pytest.fail("file was read"))
    for name in (f"../{REQUEST}.wav", f"{UUID(int=99)}.wav", str(spool / f"{REQUEST}.wav")):
        altered = dict(result, filename=name)
        with pytest.raises(InvalidSpool):
            verify(spool, altered)


def test_file_symlink_root_symlink_and_link_count_rejected(spool: Path, monkeypatch):
    path, result = write_wav(spool)
    outside = spool.parent / "outside.wav"
    path.replace(outside)
    path.symlink_to(outside)
    with pytest.raises(InvalidSpool):
        verify(spool, result)
    path.unlink()
    outside.replace(path)
    original_info = spool_module._info

    def linked_info(api, handle):
        info = original_info(api, handle)
        if not info.attributes & spool_module.FILE_ATTRIBUTE_DIRECTORY:
            info.link_count = 2
        return info

    monkeypatch.setattr(spool_module, "_info", linked_info)
    with pytest.raises(InvalidSpool):
        verify(spool, result)
    monkeypatch.setattr(spool_module, "_info", original_info)
    path.unlink()
    linked_root = spool.parent / "alias" / str(SESSION)
    linked_root.parent.mkdir()
    linked_root.symlink_to(spool, target_is_directory=True)
    with pytest.raises(InvalidSpool):
        verify(linked_root, result)


def test_stale_generation_rejected_before_and_after_bounded_read(spool: Path):
    _, result = write_wav(spool)
    with pytest.raises(StaleArtifact):
        verify(spool, result, current=lambda: False)
    calls = 0

    def changes_during_check() -> bool:
        nonlocal calls
        calls += 1
        return calls == 1

    with pytest.raises(StaleArtifact):
        verify(spool, result, current=changes_during_check)
    assert calls == 2


class NoopWorker:
    def submit(self, token: RequestToken, text: str) -> None:
        _ = token, text

    def cancel(self, token: RequestToken) -> None:
        _ = token


def test_stop_during_real_verification_cannot_admit_or_write(spool: Path):
    _, result = write_wav(spool)
    validator = SpoolValidator(spool, SESSION, UNIT, spool.parent)
    sink = RecordingSink()
    controller: SyntheticFlow

    def verifier(token, descriptor, text, current):
        calls = 0

        def stop_on_second_check():
            nonlocal calls
            calls += 1
            if calls == 2:
                controller.stop(3)
            return current()

        return validator(token, descriptor, text, stop_on_second_check)

    controller = SyntheticFlow(SESSION, WORKER,
                               UUID(EXAMPLE["payload"]["context"]["binding_id"]),
                               1, NoopWorker(), sink, verifier, validate_ipc)
    controller.read_current(REQUEST, 0)
    assert TOKEN.page is not None
    controller.text_accepted(REQUEST, TOKEN.page, "synthetic words", 1)
    controller.acknowledge_fence(1, 1)
    message = deepcopy(EXAMPLE)
    message["seq"] = 3
    message["payload"]["result"] = result
    assert not controller.receive_terminal(message, 2)
    assert controller.state.playback == "STOPPED" and not controller.pump(5)
    assert not [call for call in sink.calls if call.kind == "write"]
