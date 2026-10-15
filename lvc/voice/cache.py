"""Complete-WAV cache seam; callers check the renderer fence again on admission."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import struct
import unicodedata
import uuid
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_UNIT_BYTES = 16 * 1024 * 1024
MAX_UNIT_FRAMES = 30 * 48_000


class InvalidCachedAudio(ValueError):
    """A WAV is incomplete, corrupt, silent or in the wrong format."""


class StaleCacheWork(RuntimeError):
    """Stop or replacement revoked cache access before its result was returned."""


@dataclass(frozen=True)
class SynthesisIdentity:
    speech_text: str
    locale: str
    engine: str
    model_sha256: str
    runtime_id: str
    voice_realization_id: str
    voice_artifact_sha256: str
    lexicon_version: str
    lexicon_sha256: str
    overrides_sha256: str
    speed: float
    style: str
    chunker_version: str
    output_version: str

    def __post_init__(self) -> None:
        if not all((self.speech_text, self.locale, self.engine, self.runtime_id,
                    self.voice_realization_id, self.lexicon_version, self.style,
                    self.chunker_version, self.output_version)):
            raise ValueError("Incomplete synthesis identity")
        for digest in (self.model_sha256, self.voice_artifact_sha256,
                       self.lexicon_sha256, self.overrides_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Unpinned synthesis artifact")
        if not math.isfinite(self.speed) or self.speed <= 0:
            raise ValueError("Invalid speech speed")


def cache_key(identity: SynthesisIdentity) -> str:
    fields = {name: unicodedata.normalize("NFC", value) if isinstance(value, str)
              else value for name, value in asdict(identity).items()}
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_complete_wav(data: bytes) -> int:
    if not data or len(data) > MAX_UNIT_BYTES:
        raise InvalidCachedAudio("Invalid WAV byte length")
    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            frames = source.getnframes()
            if (source.getcomptype() != "NONE" or source.getframerate() != 48_000
                    or source.getnchannels() != 1 or source.getsampwidth() != 2
                    or not 0 < frames <= MAX_UNIT_FRAMES):
                raise InvalidCachedAudio("Invalid WAV format or duration")
            pcm = source.readframes(frames)
    except (EOFError, wave.Error) as exc:
        raise InvalidCachedAudio("Unreadable WAV") from exc
    if len(pcm) != frames * 2:
        raise InvalidCachedAudio("Truncated WAV payload")
    if max(abs(sample[0]) for sample in struct.iter_unpack("<h", pcm)) < 4:
        raise InvalidCachedAudio("Effectively silent WAV")
    return frames


class CompletedAudioCache:
    """Run I/O on the storage/preparation thread, never the GUI/audio thread."""

    def __init__(self, root: Path):
        self.root = root

    def _paths(self, key: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid cache key")
        return self.root / f"{key}.wav", self.root / f"{key}.json"

    def get(self, identity: SynthesisIdentity,
            still_current: Callable[[], bool]) -> bytes | None:
        if not still_current():
            raise StaleCacheWork("Cache lookup was canceled")
        key = cache_key(identity)
        audio_path, meta_path = self._paths(key)
        try:
            if meta_path.stat().st_size > 512 or audio_path.stat().st_size > MAX_UNIT_BYTES:
                return None
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            data = audio_path.read_bytes()
            frames = validate_complete_wav(data)
            if metadata != {"key": key, "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "frames": frames}:
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not still_current():
            raise StaleCacheWork("Cache hit became stale")
        return data

    def put(self, identity: SynthesisIdentity, data: bytes,
            still_current: Callable[[], bool]) -> str:
        if not still_current():
            raise StaleCacheWork("Late worker result was canceled")
        frames = validate_complete_wav(data)
        key = cache_key(identity)
        audio_path, meta_path = self._paths(key)
        metadata = {"key": key, "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data), "frames": frames}
        self.root.mkdir(parents=True, exist_ok=True)
        nonce = uuid.uuid4().hex
        temp_audio = self.root / f".{key}.{nonce}.wav.tmp"
        temp_meta = self.root / f".{key}.{nonce}.json.tmp"
        try:
            for path, payload in ((temp_audio, data),
                                  (temp_meta, (json.dumps(metadata, sort_keys=True) + "\n").encode())):
                with path.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            if not still_current():
                raise StaleCacheWork("Worker result became stale before cache commit")
            os.replace(temp_audio, audio_path)
            os.replace(temp_meta, meta_path)
            return key
        finally:
            temp_audio.unlink(missing_ok=True)
            temp_meta.unlink(missing_ok=True)
