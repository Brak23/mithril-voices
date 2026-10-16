"""Personal package contracts using synthetic files and no capture or audio."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from lvc.platform.windows import installed_launcher
from lvc.platform.windows.lotro_user_probe import (
    Candidate,
    capture_guidance,
    same_window_and_size,
)
from lvc.platform.windows.manual_preferences import ManualPreferences, PreferencesStore
from lvc.tts.manual_providers import (
    LocalKokoroProvider,
    VoiceOption,
    provider_for_voice,
    voice_options,
)
from tools.build_personal_package import _build_id, _cmd, _extract


def test_preferences_are_atomic_bounded_and_never_store_review_text(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "settings.json", ("bf_emma", "bm_fable"))
    assert store.load() == (ManualPreferences(), None)
    settings = ManualPreferences("bm_fable", "endpoint-1", "My speaker", True)
    store.save(settings)
    assert store.load() == (settings, None)
    raw = store.path.read_text(encoding="utf-8")
    assert "quest" not in raw and "speech" not in raw
    assert sorted(tmp_path.iterdir()) == [store.path]
    store.path.write_text(raw.replace("bm_fable", "unknown_voice"), encoding="utf-8")
    assert store.load() == (ManualPreferences(), "SETTINGS_VOICE_UNAVAILABLE")
    store.path.write_bytes(b"{" + b"x" * 5_000)
    assert store.load() == (ManualPreferences(), "SETTINGS_TOO_LARGE")


def test_provider_ids_and_render_boundary_are_explicit(tmp_path: Path) -> None:
    provider = LocalKokoroProvider(tmp_path / "voice python.exe")
    assert [(option.voice_id, option.provider_id) for option in provider.voices] == [
        ("bf_emma", "kokoro-local-cpu"), ("bm_fable", "kokoro-local-cpu")]
    assert provider_for_voice("bm_fable", (provider,)) is provider
    command, payload = provider.render_command(tmp_path, "bm_fable", "Synthetic words")
    assert command[0] == str(tmp_path / "voice python.exe")
    assert payload == {"text": "Synthetic words", "voice": "bm_fable"}
    with pytest.raises(LookupError):
        provider_for_voice("unapproved", (provider,))
    with pytest.raises(ValueError):
        voice_options((provider, provider))
    assert VoiceOption("bm_fable", "Fable (British)", "kokoro-local-cpu") in provider.voices


def test_window_identity_and_size_change_require_a_new_capture() -> None:
    original = Candidate(42, 200, 123456, r"C:\Game\lotroclient64.exe", "LOTRO", 5120, 1440)
    assert same_window_and_size(original, original)
    resized = Candidate(42, 200, 123456, original.executable_path, "LOTRO", 3840, 1440)
    assert not same_window_and_size(original, resized)
    restarted = Candidate(42, 200, 123457, original.executable_path, "LOTRO", 5120, 1440)
    assert not same_window_and_size(original, restarted)
    assert not same_window_and_size(original, None)
    assert "focus" in capture_guidance("BLOCKED:SELECTED_WINDOW_NOT_FOREGROUND").lower()
    assert "size stable" in capture_guidance("BLOCKED:NO_CURRENT_FRAME")


def test_preflight_rejects_changed_source_helper_and_asset(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "Package With Spaces"
    task = tmp_path
    source = root / "lvc" / "synthetic.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original code")
    helpers = task / "test-tmp"
    helpers.mkdir()
    for name in ("lotro_frame_probe.exe", "windows_ocr_stdin.exe"):
        (helpers / name).write_bytes(name.encode())
    asset = root / ".audition" / "assets" / "synthetic.pt"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"original asset")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {"format": 1, "build_id": "a" * 8 + "-" + "b" * 8,
                "source_commit": "c" * 40,
                "files": {"lvc/synthetic.py": digest(source)},
                "helpers": {name: digest(helpers / name) for name in
                            ("lotro_frame_probe.exe", "windows_ocr_stdin.exe")},
                "assets": {"synthetic.pt": digest(asset)},
                "runtime_versions": {"kokoro": "0.9.4"}, "qt_version": "6.12.0"}
    metadata = root / "personal-build.json"
    metadata.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(installed_launcher, "ROOT", root)
    monkeypatch.setattr(installed_launcher, "TASK_ROOT", task)
    monkeypatch.setattr(installed_launcher, "MANIFEST", metadata)
    monkeypatch.setattr(installed_launcher, "_runtime_matches", lambda *_args: True)
    assert installed_launcher.preflight()[1] == []
    source.write_bytes(b"changed code")
    assert "PACKAGE_FILE_CHANGED" in installed_launcher.preflight()[1]
    source.write_bytes(b"original code")
    (helpers / "lotro_frame_probe.exe").unlink()
    assert "CAPTURE_HELPER_MISSING" in installed_launcher.preflight()[1]
    (helpers / "lotro_frame_probe.exe").write_bytes(b"lotro_frame_probe.exe")
    asset.write_bytes(b"changed asset")
    assert "VOICE_ASSET_CHANGED" in installed_launcher.preflight()[1]


def test_source_archive_blocks_traversal_and_desktop_command_quotes_spaces(tmp_path: Path) -> None:
    assert _build_id("a" * 40, {"lvc/a.py": "b" * 64}) == _build_id(
        "a" * 40, {"lvc/a.py": "b" * 64})
    with io.BytesIO() as stream:
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../escape.py", "bad")
        with pytest.raises(RuntimeError, match="SOURCE_ARCHIVE_INVALID"):
            _extract(stream.getvalue(), tmp_path)
    command = _cmd(tmp_path / "Mithril Voices Personal aaaaaaaa-bbbbbbbb")
    assert f'cd /d "{tmp_path / "Mithril Voices Personal aaaaaaaa-bbbbbbbb"}"' in command
    assert 'if /I "%~1"=="--check" exit /b %mithril_status%' in command
    with pytest.raises(ValueError):
        _cmd(Path('bad"path'))
