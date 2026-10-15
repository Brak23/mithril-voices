"""Pinned, offline Kokoro CPU audition adapter. No audio device is opened here."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import io
import os
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lvc.voice.cache import validate_complete_wav
from lvc.voice.text_plan import chunk_speech

MAX_PHONEMES = 510
MODEL_SHA256 = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
CONFIG_SHA256 = "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"
VOICE_SHA256 = {
    "bf_emma": "d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701",
    "bm_fable": "d44935f3135257a9064df99f007fc1342ff1aa767552b4a4fa4c3b2e6e59079c",
}
RUNTIME_VERSIONS = {
    "kokoro": "0.9.4", "misaki": "0.9.4", "spacy": "3.8.11",
    "torch": "2.14.1", "transformers": "4.53.3", "scipy": "1.16.2",
    "en-core-web-sm": "3.8.0", "espeakng-loader": "0.2.4",
}


class IncompletePhonemes(ValueError):
    """G2P changed text, dropped a spoken token, or exceeded model capacity."""


class GenerationCanceled(RuntimeError):
    """The current request lost authority; discard its inference result."""


@dataclass(frozen=True)
class PlannedUnit:
    text: str
    phonemes: str


@dataclass(frozen=True)
class RenderedPassage:
    wav: bytes
    unit_count: int
    first_unit_ready_ms: float
    render_ms: float
    phoneme_lengths: tuple[int, ...]


def _current(still_current: Callable[[], bool]) -> None:
    if not still_current():
        raise GenerationCanceled("Request was canceled")


def plan_phonemes(text: str, g2p: Callable[[str], tuple[str, list[Any]]], *,
                  max_phonemes: int = MAX_PHONEMES,
                  still_current: Callable[[], bool] = lambda: True) -> tuple[PlannedUnit, ...]:
    """Preserve exact source units and reject Kokoro's silent truncation path."""
    _current(still_current)
    if not 1 <= max_phonemes <= MAX_PHONEMES:
        raise ValueError("Invalid phoneme limit")

    def count(candidate: str) -> int:
        _current(still_current)
        return len(g2p(candidate.strip())[0])

    chunks = chunk_speech(text, max_tokens=max_phonemes, count_tokens=count)
    units: list[PlannedUnit] = []
    for chunk in chunks:
        _current(still_current)
        source = chunk.text.strip()
        phonemes, tokens = g2p(source)
        reconstructed = "".join(token.text + token.whitespace for token in tokens).strip()
        if (not phonemes or len(phonemes) > max_phonemes or reconstructed != source
                or any(any(char.isalnum() for char in token.text) and not token.phonemes
                       for token in tokens)):
            raise IncompletePhonemes("G2P cannot represent this complete speech unit")
        units.append(PlannedUnit(chunk.text, phonemes))
    if "".join(unit.text for unit in units) != text:
        raise IncompletePhonemes("Speech units changed the input text")
    return tuple(units)


def _verified(path: Path, expected_sha256: str) -> None:
    if not path.is_file():
        raise FileNotFoundError("Pinned speech asset is missing")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected_sha256:
        raise ValueError("Pinned speech asset hash mismatch")


class KokoroCpu:
    """Construct only inside the designated CPU worker process."""

    def __init__(self, assets: Path, voice_id: str):
        if voice_id not in VOICE_SHA256:
            raise ValueError("Voice is outside the approved audition set")
        # Set before importing any library that can contact a model hub.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        for name, version in RUNTIME_VERSIONS.items():
            if importlib.metadata.version(name) != version:
                raise ValueError("Pinned speech runtime version mismatch")
        config = assets / "config.json"
        weights = assets / "kokoro-v1_0.pth"
        voice = assets / f"{voice_id}.pt"
        _verified(config, CONFIG_SHA256)
        _verified(weights, MODEL_SHA256)
        _verified(voice, VOICE_SHA256[voice_id])

        spacy = importlib.import_module("spacy")
        if not spacy.util.is_package("en_core_web_sm"):
            raise RuntimeError("Pinned English spaCy package is missing")
        espeak = importlib.import_module("misaki.espeak")
        # Without this, KPipeline catches the failure and Misaki may load BART.
        espeak.EspeakFallback(british=True)
        original_download = spacy.cli.download
        spacy.cli.download = lambda *_a, **_kw: (_ for _ in ()).throw(
            RuntimeError("Automatic spaCy downloads are disabled"))
        try:
            kokoro = importlib.import_module("kokoro")
            self.pipeline = kokoro.KPipeline(lang_code="b", model=False,
                                             device="cpu", repo_id="hexgrad/Kokoro-82M")
        finally:
            spacy.cli.download = original_download
        if not isinstance(self.pipeline.g2p.fallback, espeak.EspeakFallback):
            raise TypeError("Required offline eSpeak pronunciation fallback is absent")
        torch = importlib.import_module("torch")
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.model = kokoro.KModel(repo_id="hexgrad/Kokoro-82M",
                                   config=str(config), model=str(weights)).to("cpu").eval()
        self.pack = torch.load(str(voice), map_location="cpu", weights_only=True)
        self.torch = torch
        self.kokoro = kokoro

    def render(self, text: str, *, still_current: Callable[[], bool] = lambda: True) -> RenderedPassage:
        np = importlib.import_module("numpy")
        signal = importlib.import_module("scipy.signal")
        units = plan_phonemes(text, self.pipeline.g2p, still_current=still_current)
        pcm = bytearray()
        first_ready = 0.0
        start = time.perf_counter()
        for unit in units:
            _current(still_current)
            with self.torch.inference_mode():
                output = self.kokoro.KPipeline.infer(self.model, unit.phonemes,
                                                     self.pack, 1.0)
            _current(still_current)  # A late result cannot be admitted after Stop.
            samples = output.audio.numpy()
            if samples.ndim != 1 or not samples.size or not np.all(np.isfinite(samples)):
                raise ValueError("Invalid Kokoro waveform")
            samples48 = signal.resample_poly(samples, 2, 1)
            samples48 = np.clip(samples48, -1.0, 1.0)
            pcm.extend(np.rint(samples48 * 32767.0).astype("<i2").tobytes())
            if not first_ready:
                first_ready = (time.perf_counter() - start) * 1000
            if len(pcm) > 16 * 1024 * 1024 - 44:
                raise ValueError("Audition WAV exceeds the bounded unit size")
        _current(still_current)
        if len(pcm) // 2 > 30 * 48_000:
            raise ValueError("Audition passage exceeds 30 seconds")
        output_bytes = io.BytesIO()
        with wave.open(output_bytes, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48_000)
            wav.writeframes(pcm)
        result = output_bytes.getvalue()
        validate_complete_wav(result)
        _current(still_current)
        return RenderedPassage(result, len(units), first_ready,
                               (time.perf_counter() - start) * 1000,
                               tuple(len(unit.phonemes) for unit in units))
