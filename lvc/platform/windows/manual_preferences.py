"""Small private settings file; never stores quest text, pixels, or WAV data."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

MAX_SETTINGS_BYTES = 4_096


@dataclass(frozen=True)
class ManualPreferences:
    voice_id: str | None = None
    device_id: str | None = None
    device_description: str | None = None
    keep_local_cache: bool = False

    def voice(self, voice_id: str | None) -> ManualPreferences:
        return replace(self, voice_id=voice_id)

    def device(self, device_id: str | None,
               description: str | None) -> ManualPreferences:
        return replace(self, device_id=device_id,
                       device_description=description)

    def cache(self, enabled: bool) -> ManualPreferences:
        return replace(self, keep_local_cache=enabled)


class PreferencesStore:
    def __init__(self, path: Path, allowed_voices: tuple[str, ...]):
        self.path = path
        self.allowed_voices = allowed_voices

    def _validate(self, value: object) -> ManualPreferences:
        if not isinstance(value, dict) or set(value) != {
                "version", "voice_id", "device_id", "device_description",
                "keep_local_cache"} or value["version"] != 1:
            raise ValueError("SETTINGS_INVALID")
        voice, device, description, cache = (value[key] for key in
                                             ("voice_id", "device_id",
                                              "device_description", "keep_local_cache"))
        if (voice is not None and (not isinstance(voice, str)
                                   or voice not in self.allowed_voices)):
            raise ValueError("SETTINGS_VOICE_UNAVAILABLE")
        if (device is None) != (description is None):
            raise ValueError("SETTINGS_INVALID")
        if (device is not None and (not isinstance(device, str)
                                    or not 0 < len(device) <= 512
                                    or not isinstance(description, str)
                                    or not 0 < len(description) <= 256)):
            raise ValueError("SETTINGS_INVALID")
        if type(cache) is not bool:
            raise ValueError("SETTINGS_INVALID")
        return ManualPreferences(voice, device, description, cache)

    def load(self) -> tuple[ManualPreferences, str | None]:
        try:
            if self.path.stat().st_size > MAX_SETTINGS_BYTES:
                raise ValueError("SETTINGS_TOO_LARGE")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return self._validate(value), None
        except FileNotFoundError:
            return ManualPreferences(), None
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith(
                "SETTINGS_") else "SETTINGS_INVALID"
            return ManualPreferences(), code

    def save(self, settings: ManualPreferences) -> None:
        value = {"version": 1, "voice_id": settings.voice_id,
                 "device_id": settings.device_id,
                 "device_description": settings.device_description,
                 "keep_local_cache": settings.keep_local_cache}
        self._validate(value)
        payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        if len(payload) > MAX_SETTINGS_BYTES:
            raise ValueError("SETTINGS_TOO_LARGE")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
