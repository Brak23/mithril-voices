"""Stable manual voice IDs and the bounded renderer seam.

Additional providers must supply the same complete-WAV child protocol and be
explicitly approved before registration. No remote provider is registered.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lvc.tts.kokoro_cpu import MODEL_SHA256, VOICE_SHA256
from lvc.voice.assignments import VoiceCatalog, VoiceRealization
from lvc.voice.cache import SynthesisIdentity
from lvc.voice.text_plan import SpeechUnit


@dataclass(frozen=True)
class VoiceOption:
    voice_id: str
    label: str
    provider_id: str


class ManualVoiceProvider(Protocol):
    """One renderer process per request; output is validated by the host."""

    provider_id: str
    voices: tuple[VoiceOption, ...]

    def render_command(self, spool: Path, voice_id: str, text: str
                       ) -> tuple[list[str], dict[str, object]]: ...

    def identity(self, unit: SpeechUnit, voice_id: str,
                 lexicon_version: str, lexicon_hash: str) -> SynthesisIdentity: ...


class LocalKokoroProvider:
    provider_id = "kokoro-local-cpu"
    voices = (
        VoiceOption("bf_emma", "Emma (British)", provider_id),
        VoiceOption("bm_fable", "Fable (British)", provider_id),
    )

    def __init__(self, python: Path):
        self.python = python
        self.catalog = VoiceCatalog((
            VoiceRealization("bf_emma", "kokoro", VOICE_SHA256["bf_emma"],
                             "en-GB", "manual_narrator", approved=True),
            VoiceRealization("bm_fable", "kokoro", VOICE_SHA256["bm_fable"],
                             "en-GB", "manual_narrator", approved=True),
        ), narrator_id="bf_emma")

    def render_command(self, spool: Path, voice_id: str, text: str
                       ) -> tuple[list[str], dict[str, object]]:
        self.catalog.get(voice_id)
        return ([str(self.python), "-u", "-m", "lvc.tts.manual_kokoro_worker",
                 "--output", str(spool)], {"text": text, "voice": voice_id})

    def identity(self, unit: SpeechUnit, voice_id: str,
                 lexicon_version: str, lexicon_hash: str) -> SynthesisIdentity:
        voice = self.catalog.get(voice_id)
        return SynthesisIdentity(
            speech_text=unit.text, locale="en-GB", engine="kokoro",
            model_sha256=MODEL_SHA256, runtime_id="kokoro-cpu-win-py312-0.9.4",
            voice_realization_id=voice_id,
            voice_artifact_sha256=voice.artifact_sha256,
            lexicon_version=lexicon_version, lexicon_sha256=lexicon_hash,
            overrides_sha256=hashlib.sha256(b"").hexdigest(), speed=1.0,
            style="neutral", chunker_version="sentence-1-180",
            output_version="wav48k-mono-s16-v1",
        )


def provider_for_voice(voice_id: str,
                       providers: tuple[ManualVoiceProvider, ...]
                       ) -> ManualVoiceProvider:
    matches = [provider for provider in providers
               if any(option.voice_id == voice_id for option in provider.voices)]
    if len(matches) != 1:
        raise LookupError("Voice ID unavailable or ambiguous")
    return matches[0]


def voice_options(providers: tuple[ManualVoiceProvider, ...]) -> tuple[VoiceOption, ...]:
    choices = tuple(option for provider in providers for option in provider.voices)
    if (len({item.voice_id for item in choices}) != len(choices)
            or any(item.provider_id != provider.provider_id
                   for provider in providers for item in provider.voices)):
        raise ValueError("Provider voice IDs must be stable and unique")
    return choices
