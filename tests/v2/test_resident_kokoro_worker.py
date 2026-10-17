"""Bounded phrase protocol tests; no model or physical audio is loaded."""
from __future__ import annotations

import io
import struct
import wave
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from lvc.tts.resident_kokoro_worker import messages, read_command, request_units
from lvc.voice.cache import validate_complete_wav

REQUEST = "93154e70-813b-4b7b-a99e-07e9df60b5d0"


def command(text: str) -> dict[str, object]:
    return {"action": "render", "request_id": REQUEST, "generation": 3,
            "voice": "bf_emma", "text": text}


def wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(b"".join(struct.pack("<h", 100 if n % 2 else -100)
                                    for n in range(480)))
    return output.getvalue()


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def render(self, text: str) -> object:
        self.calls.append(text)
        return SimpleNamespace(wav=wav())


def test_one_prepared_unit_and_exact_next_ack(tmp_path: Path) -> None:
    renderer = FakeRenderer()
    source = "The lanterns are lit. The gate is open."
    units = request_units(command(source), "bf_emma")[2]
    assert len(units) == 2 and "".join(units) == source
    next_calls = 0

    def acknowledge() -> dict[str, object]:
        nonlocal next_calls
        next_calls += 1
        return {"action": "next", "request_id": REQUEST,
                "generation": 3, "after_index": 0}

    produced = messages(command(source), "bf_emma", renderer,
                        tmp_path, acknowledge)
    first = next(produced)
    assert first["event"] == "UNIT_READY" and first["index"] == 0
    assert renderer.calls == [units[0]] and next_calls == 0
    assert validate_complete_wav(Path(str(first["path"])).read_bytes()) == 480
    second = next(produced)
    assert second["event"] == "UNIT_READY" and second["index"] == 1
    assert renderer.calls == list(units) and next_calls == 1
    assert next(produced)["event"] == "DONE"
    with pytest.raises(StopIteration):
        next(produced)


def test_invalid_next_does_not_render_following_unit(tmp_path: Path) -> None:
    renderer = FakeRenderer()
    produced = messages(command("First sentence. Second sentence."),
                        "bf_emma", renderer, tmp_path,
                        lambda: {"action": "next", "request_id": REQUEST,
                                 "generation": True, "after_index": 0})
    next(produced)
    with pytest.raises(ValueError, match="NEXT_INVALID"):
        next(produced)
    assert len(renderer.calls) == 1


def test_cancel_after_first_unit_keeps_resident_protocol_available(tmp_path: Path) -> None:
    renderer = FakeRenderer()
    produced = messages(command("First sentence. Second sentence."),
                        "bf_emma", renderer, tmp_path,
                        lambda: {"action": "cancel", "request_id": REQUEST,
                                 "generation": 3})
    assert next(produced)["event"] == "UNIT_READY"
    assert next(produced)["event"] == "CANCELED"
    with pytest.raises(StopIteration):
        next(produced)
    assert len(renderer.calls) == 1


@pytest.mark.parametrize("payload", [
    b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'[]\n', b'{\n',
])
def test_malformed_json_never_becomes_a_command(payload: bytes) -> None:
    with pytest.raises(ValueError):
        read_command(io.BytesIO(payload))


def test_request_requires_voice_generation_and_bounded_text() -> None:
    assert request_units(command("Bring 10 Ore."), "bf_emma")[0] == UUID(REQUEST)
    for invalid in (
        {**command("Valid."), "generation": True},
        {**command("Valid."), "voice": "bm_fable"},
        {**command("Valid."), "text": ""},
        {**command("Valid."), "text": "word " * 601},
        {**command("Valid."), "extra": "ignored"},
    ):
        with pytest.raises(ValueError):
            request_units(invalid, "bf_emma")
