"""Original passages and fault fixtures; no model, game or device is touched."""
from __future__ import annotations

import hashlib
import io
import itertools
import json
import math
import sqlite3
import wave
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from lvc.core import (
    PageIdentity,
    ReadCurrent,
    State,
    Stop,
    ValidatedText,
    WorkerCompleted,
    reduce,
)
from lvc.safeguards import AudioGate, WorkerLedger
from lvc.vision.text_gate import TextDecision
from lvc.voice.artifacts import AuditionArtifact, audition_readiness
from lvc.voice.assignments import (
    VoiceAssignmentStore,
    VoiceCatalog,
    VoiceRealization,
    VoiceUnavailable,
)
from lvc.voice.cache import (
    CompletedAudioCache,
    InvalidCachedAudio,
    StaleCacheWork,
    SynthesisIdentity,
    cache_key,
)
from lvc.voice.text_plan import (
    CHUNKER_VERSION,
    Lexicon,
    LexiconEntry,
    TextTooLong,
    chunk_speech,
    load_lexicon,
    prepare_accepted_ocr,
    prepare_text,
)
from tests.v2.support import RecordingSink

FIXTURES = Path(__file__).parent / "fixtures" / "pregame_passages.json"
DIGEST = "a" * 64


def passages() -> list[dict[str, str]]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("passage", passages(), ids=lambda passage: passage["id"])
def test_six_original_passages_chunk_exactly_once(passage: dict[str, str]) -> None:
    original = passage["text"]
    units = chunk_speech(original, max_codepoints=45)
    assert "".join(unit.text for unit in units) == original
    assert all(unit.text == original[unit.start:unit.end] and len(unit.text) <= 45
               for unit in units)
    assert units[0].start == 0 and units[-1].end == len(original)
    assert all(left.end == right.start for left, right in itertools.pairwise(units))


def test_chunker_abbreviation_decimal_and_backend_token_limit() -> None:
    text = "Dr. Vale measured 3.5 spans. Then she left."
    units = chunk_speech(text)
    assert units[0].text == "Dr. Vale measured 3.5 spans. "
    assert "".join(unit.text for unit in units) == text
    limited = chunk_speech("one two three four", max_tokens=2,
                           count_tokens=lambda part: len(part.split()))
    assert all(len(unit.text.split()) <= 2 for unit in limited)


def test_long_unbroken_word_fails_instead_of_truncating() -> None:
    with pytest.raises(TextTooLong):
        chunk_speech("A " + "x" * 281, max_codepoints=280)


def entry(source: str, spoken: str, *, scope: str = "global") -> LexiconEntry:
    return LexiconEntry(source, spoken, "en", "kokoro_cpu", scope, 10,
                        "original local audition", "owner review pending")


def test_lexicon_preserves_raw_and_display_and_matches_whole_words() -> None:
    lexicon = Lexicon("draft-1", (entry("Serevale", "seh-reh-vail"),))
    plan = prepare_text("Serevale?", "Serevale and Serevales.", lexicon,
                        locale="en", engine="kokoro_cpu")
    assert plan.raw_ocr == "Serevale?"
    assert plan.accepted_display == "Serevale and Serevales."
    assert plan.speech_text == "seh-reh-vail and Serevales."
    assert plan.replacements[0].source == "Serevale"
    assert plan.lexicon_sha256 == lexicon.sha256


def test_lexicon_rejects_protected_changes_and_duplicate_rules() -> None:
    with pytest.raises(ValueError):
        entry("10 stones", "1 stone")
    with pytest.raises(ValueError):
        entry("do not go", "do go")
    with pytest.raises(ValueError):
        entry("don't go", "do go")
    with pytest.raises(ValueError):
        Lexicon("v1", (entry("Serevale", "one"), entry("serevale", "two")))
    with pytest.raises(ValueError):
        Lexicon("v1", (entry("Serevale", "one"),
                       entry("Serevale", "two", scope="speaker-1")))


def test_rejected_ocr_cannot_create_automatic_speech_plan() -> None:
    lexicon = load_lexicon(Path(__file__).parents[2] / "lvc/voice/lexicon.en.json")
    with pytest.raises(ValueError):
        prepare_accepted_ocr(TextDecision("10 stones", None, "LOW_OCR_CONFIDENCE"),
                             lexicon, locale="en", engine="kokoro_cpu")
    accepted = prepare_accepted_ocr(TextDecision("10 stones", "10 stones", "ACCEPTED"),
                                    lexicon, locale="en", engine="kokoro_cpu")
    assert accepted.raw_ocr == accepted.accepted_display == accepted.speech_text


def test_lexicon_loader_rejects_code_like_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": "v1", "entries": [
        {**entry("Serevale", "seh-reh-vail").__dict__, "regex": ".*"}]}),
        encoding="utf-8")
    with pytest.raises(ValueError):
        load_lexicon(path)


def voice(voice_id: str, archetype: str = "keeper") -> VoiceRealization:
    return VoiceRealization(voice_id, "kokoro_cpu", hashlib.sha256(voice_id.encode()).hexdigest(),
                            "en", archetype, approved=True)


def test_voice_assignment_survives_restart_and_catalog_insertion(tmp_path: Path) -> None:
    db_path = tmp_path / "voices.sqlite3"
    first_catalog = VoiceCatalog((voice("narrator", "narrator"), voice("keeper-a"),
                                  voice("keeper-b")), "narrator")
    with sqlite3.connect(db_path) as connection:
        store = VoiceAssignmentStore(connection)
        selected = store.resolve("trusted-interaction-77", first_catalog, "keeper")
        assert store.resolve(None, first_catalog) == first_catalog.get("narrator")
    expanded = VoiceCatalog((*first_catalog.by_id.values(), voice("keeper-c")), "narrator")
    with sqlite3.connect(db_path) as connection:
        store = VoiceAssignmentStore(connection)
        assert store.resolve("trusted-interaction-77", expanded, "keeper") == selected
        assert store.override("trusted-interaction-77", "keeper-c", expanded).realization_id == "keeper-c"
    with sqlite3.connect(db_path) as connection:
        assert VoiceAssignmentStore(connection).resolve(
            "trusted-interaction-77", expanded).realization_id == "keeper-c"


def test_removed_voice_requires_explicit_replacement(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "voices.db") as connection:
        original = VoiceCatalog((voice("narrator"), voice("keeper-a")), "narrator")
        store = VoiceAssignmentStore(connection)
        store.override("trusted-speaker", "keeper-a", original)
        with pytest.raises(VoiceUnavailable):
            store.resolve("trusted-speaker", VoiceCatalog((voice("narrator"),), "narrator"))


def identity(text: str = "The road is clear.") -> SynthesisIdentity:
    return SynthesisIdentity(text, "en", "kokoro_cpu", DIGEST, "runtime-1",
                             "narrator", DIGEST, "lex-1", DIGEST, DIGEST, 1.0,
                             "neutral", CHUNKER_VERSION, "pcm-1")


def synthetic_wav() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\x10\x00" * 2400)
    return stream.getvalue()


def test_cache_key_covers_exact_voice_text_and_processing_identity() -> None:
    original = identity()
    changes = (replace(original, speech_text="The road is clear!"),
               replace(original, voice_realization_id="keeper-a"),
               replace(original, lexicon_sha256="b" * 64),
               replace(original, chunker_version="sentence-2"),
               replace(original, output_version="pcm-2"))
    assert all(cache_key(item) != cache_key(original) for item in changes)
    assert math.isfinite(original.speed)


def test_cache_rejects_corruption_and_truncation(tmp_path: Path) -> None:
    cache = CompletedAudioCache(tmp_path)
    original = identity()
    data = synthetic_wav()
    key = cache.put(original, data, lambda: True)
    assert cache.get(original, lambda: True) == data
    (tmp_path / f"{key}.wav").write_bytes(data[:-20])
    assert cache.get(original, lambda: True) is None
    (tmp_path / f"{key}.wav").write_bytes(data)
    (tmp_path / f"{key}.json").write_text("{" + "x" * 600, encoding="utf-8")
    assert cache.get(original, lambda: True) is None
    with pytest.raises(InvalidCachedAudio):
        cache.put(identity("other"), b"RIFF", lambda: True)


def test_cache_fences_late_worker_and_mid_lookup_stop(tmp_path: Path) -> None:
    cache = CompletedAudioCache(tmp_path)
    original = identity()
    with pytest.raises(StaleCacheWork):
        cache.put(original, synthetic_wav(), lambda: False)
    assert not list(tmp_path.glob("*.wav"))
    cache.put(original, synthetic_wav(), lambda: True)
    current = iter((True, False))
    with pytest.raises(StaleCacheWork):
        cache.get(original, lambda: next(current))
    current = iter((True, False))
    with pytest.raises(StaleCacheWork):
        cache.put(identity("later"), synthetic_wav(), lambda: next(current))
    assert not list(tmp_path.glob("*.tmp"))
    assert cache.get(identity("later"), lambda: True) is None


def test_completed_cache_hit_still_obeys_existing_audio_generation_fence(
        tmp_path: Path) -> None:
    cache = CompletedAudioCache(tmp_path)
    cache.put(identity(), synthetic_wav(), lambda: True)
    session, request_id = UUID(int=101), UUID(int=102)
    page = PageIdentity(UUID(int=103), 1, "quest", "synthetic")
    state = State(session_id=session, bound=True)
    state, _ = reduce(state, ReadCurrent(request_id), 0)
    state, _ = reduce(state, ValidatedText(request_id, page, "The road is clear."), 0)
    token = state.synthesis
    assert token is not None and cache.get(identity(), lambda: True) is not None
    state, _ = reduce(state, WorkerCompleted(token, "cache-unit"), 0)
    ledger = WorkerLedger(session)
    gate = AudioGate(session).fence(state.generation).ack_fence(state.generation, 0)
    gate = gate.start_unit(state, ledger, token, "cache-unit", 0, 2400, 0, source="cache")
    stopped, _ = reduce(state, Stop(), 1)
    sink = RecordingSink()
    _, wrote = gate.write(stopped, ledger, token, "cache-unit", 0, 0, 100, sink)
    assert not wrote and sink.calls == []


def test_audition_requires_pinned_approved_local_artifacts(tmp_path: Path) -> None:
    assert set(audition_readiness(()).values()) == {"MISSING_MANIFEST_ENTRY"}
    local = tmp_path / "synthetic.bin"
    local.write_bytes(b"original synthetic artifact")
    artifact = AuditionArtifact("kokoro_weights", local,
                                hashlib.sha256(local.read_bytes()).hexdigest(),
                                "https://example.invalid/original", "synthetic test permission", True)
    assert artifact.inspect() == "VERIFIED"
    assert replace(artifact, approved_for_local_use=False).inspect() == "APPROVAL_OR_RIGHTS_MISSING"
    assert replace(artifact, sha256=DIGEST).inspect() == "HASH_MISMATCH"
