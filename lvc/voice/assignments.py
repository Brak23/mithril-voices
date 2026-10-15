"""Stable voice realization selection on a caller-owned SQLite connection."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass


class VoiceUnavailable(LookupError):
    """An existing realization is missing; a visible replacement is needed."""


@dataclass(frozen=True)
class VoiceRealization:
    realization_id: str
    engine: str
    artifact_sha256: str
    locale: str
    archetype: str
    approved: bool = False

    def __post_init__(self) -> None:
        if (not all((self.realization_id, self.engine, self.locale, self.archetype))
                or not re.fullmatch(r"[0-9a-f]{64}", self.artifact_sha256)):
            raise ValueError("Voice realization needs a stable ID and pinned artifact")


class VoiceCatalog:
    def __init__(self, realizations: tuple[VoiceRealization, ...], narrator_id: str):
        by_id = {voice.realization_id: voice for voice in realizations}
        if len(by_id) != len(realizations) or narrator_id not in by_id:
            raise ValueError("Catalog needs unique IDs and a fixed narrator")
        if not by_id[narrator_id].approved:
            raise ValueError("Narrator must be explicitly approved")
        self.by_id = by_id
        self.narrator_id = narrator_id

    def get(self, realization_id: str) -> VoiceRealization:
        voice = self.by_id.get(realization_id)
        if voice is None or not voice.approved:
            raise VoiceUnavailable("Voice realization is unavailable")
        return voice


class VoiceAssignmentStore:
    """Use on the storage owner's thread; the caller owns the connection."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        connection.execute("""CREATE TABLE IF NOT EXISTS voice_assignments (
            speaker_key TEXT PRIMARY KEY,
            realization_id TEXT NOT NULL,
            engine TEXT NOT NULL,
            artifact_sha256 TEXT NOT NULL
        )""")
        connection.commit()

    def resolve(self, trusted_speaker_key: str | None, catalog: VoiceCatalog,
                archetype: str | None = None) -> VoiceRealization:
        if not trusted_speaker_key:
            return catalog.get(catalog.narrator_id)
        if len(trusted_speaker_key) > 256 or "\x00" in trusted_speaker_key:
            raise ValueError("Invalid speaker identity")
        row = self.connection.execute(
            "SELECT realization_id, engine, artifact_sha256 FROM voice_assignments "
            "WHERE speaker_key = ?", (trusted_speaker_key,)).fetchone()
        if row is not None:
            voice = catalog.get(row[0])
            if (voice.engine, voice.artifact_sha256) != (row[1], row[2]):
                raise VoiceUnavailable("Pinned voice realization changed")
            return voice
        pool = sorted((voice for voice in catalog.by_id.values()
                       if voice.approved and voice.archetype == archetype),
                      key=lambda voice: voice.realization_id) if archetype else []
        if pool:
            digest = hashlib.sha256(trusted_speaker_key.encode("utf-8")).digest()
            chosen = pool[int.from_bytes(digest[:8], "big") % len(pool)]
        else:
            chosen = catalog.get(catalog.narrator_id)
        self.connection.execute(
            "INSERT INTO voice_assignments VALUES (?, ?, ?, ?)",
            (trusted_speaker_key, chosen.realization_id, chosen.engine,
             chosen.artifact_sha256))
        self.connection.commit()  # Persist before first use.
        return chosen

    def override(self, trusted_speaker_key: str, realization_id: str,
                 catalog: VoiceCatalog) -> VoiceRealization:
        if not trusted_speaker_key or len(trusted_speaker_key) > 256:
            raise ValueError("Trusted speaker identity required")
        voice = catalog.get(realization_id)
        self.connection.execute(
            "INSERT INTO voice_assignments VALUES (?, ?, ?, ?) "
            "ON CONFLICT(speaker_key) DO UPDATE SET realization_id=excluded.realization_id, "
            "engine=excluded.engine, artifact_sha256=excluded.artifact_sha256",
            (trusted_speaker_key, voice.realization_id, voice.engine,
             voice.artifact_sha256))
        self.connection.commit()
        return voice
