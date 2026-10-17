"""Stage a checked, immutable-source personal Auto snapshot and Desktop launcher."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from lvc.platform.windows.manual_preferences import PreferencesStore
from tools.build_personal_package import (
    ASSETS,
    HELPERS,
    ROOT,
    RUNTIME_VERSIONS,
    TASK_ROOT,
    _archive,
    _build_id,
    _extract,
    _safe_remove_temporary,
    _source_files,
    _verified_dependencies,
    _write_atomic,
)

VOICES = ("bf_emma", "bm_fable")


def _settings_source(desktop: Path) -> Path | None:
    for metadata, prefix, settings in (
        (desktop / "Mithril Automatic" / "installation.json",
         "Mithril Voices Automatic ", "auto-preferences.json"),
        (desktop / "Mithril Voices" / "installation.json",
         "Mithril Voices Personal ", "preferences.json"),
    ):
        try:
            if metadata.stat().st_size > 4096:
                continue
            data = json.loads(metadata.read_text(encoding="utf-8"))
            root = Path(data["active_snapshot"])
            if root.resolve().parent != TASK_ROOT.resolve() or not root.name.startswith(prefix):
                continue
            source = root / ".audition" / settings
            if source.is_file():
                return source
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _cmd(snapshot: Path) -> str:
    quoted = str(snapshot)
    if any(char in quoted for char in ('"', "\r", "\n")):
        raise ValueError("INVALID_SNAPSHOT_PATH")
    return "\r\n".join([
        "@echo off", "setlocal", f'cd /d "{quoted}" || exit /b 2',
        ('".venv\\Scripts\\python.exe" -u -m '
         'lvc.platform.windows.auto_installed_launcher %*'),
        'set "mithril_status=%ERRORLEVEL%"',
        'if /I "%~1"=="--check" exit /b %mithril_status%',
        'if /I "%~1"=="--check-ui" exit /b %mithril_status%',
        'if /I "%~1"=="--version" exit /b %mithril_status%',
        "echo.", "echo Mithril Automatic finished. Press a key to close.",
        "pause", "exit /b %mithril_status%", "",
    ])


def stage(desktop: Path) -> dict[str, str]:
    if not desktop.is_dir():
        raise RuntimeError("DESKTOP_UNAVAILABLE")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=ROOT, text=True).strip():
        raise RuntimeError("COMMIT_CODE_BEFORE_STAGING")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                     cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("SOURCE_COMMIT_INVALID")
    qt_version = _verified_dependencies()
    temporary = TASK_ROOT / f".mithril-package-building-{uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    try:
        _extract(_archive(commit), temporary)
        files = _source_files(temporary)
        build_id = _build_id(commit, files)
        destination = TASK_ROOT / f"Mithril Voices Automatic {build_id}"
        manifest = {"format": 1, "build_id": build_id, "source_commit": commit,
                    "files": files, "helpers": HELPERS, "assets": ASSETS,
                    "runtime_versions": RUNTIME_VERSIONS, "qt_version": qt_version}
        (temporary / "personal-build.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        for link, target in (
            (temporary / ".venv", ROOT / ".venv"),
            (temporary / ".audition-venv", ROOT / ".audition-venv"),
            (temporary / ".audition" / "assets", ROOT / ".audition" / "assets"),
        ):
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target.resolve(), link, target_is_directory=True)
        if destination.exists():
            if (destination / "personal-build.json").read_bytes() != (
                    temporary / "personal-build.json").read_bytes():
                raise RuntimeError("PACKAGE_VERSION_PATH_CONFLICT")
        else:
            os.replace(temporary, destination)
        result = subprocess.run(
            [str(destination / ".venv" / "Scripts" / "python.exe"), "-m",
             "lvc.platform.windows.auto_installed_launcher", "--check"],
            cwd=destination, capture_output=True, text=True, timeout=40, check=False)
        if result.returncode or '"status": "READY"' not in result.stdout:
            raise RuntimeError("PACKAGE_PREFLIGHT_BLOCKED")
        settings = destination / ".audition" / "auto-preferences.json"
        source = _settings_source(desktop)
        if not settings.exists() and source is not None:
            saved, issue = PreferencesStore(source, VOICES).load()
            if issue is None:
                PreferencesStore(settings, VOICES).save(saved)
        package = desktop / "Mithril Automatic"
        package.mkdir(exist_ok=True)
        metadata = {"build_id": build_id, "source_commit": commit,
                    "active_snapshot": str(destination)}
        _write_atomic(package / "installation.json",
                      json.dumps(metadata, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
        _write_atomic(desktop / "Mithril Automatic.cmd", _cmd(destination), encoding="ascii")
        return {"status": "READY", "build_id": build_id, "source_commit": commit,
                "snapshot": str(destination), "launcher": str(desktop / "Mithril Automatic.cmd")}
    finally:
        if temporary.exists():
            _safe_remove_temporary(temporary)


if __name__ == "__main__":
    try:
        print(json.dumps(stage(Path(os.environ["USERPROFILE"]) / "Desktop"), sort_keys=True))
    except Exception:  # noqa: BLE001 - paths and private settings stay out of failure output
        print('{"status":"BLOCKED","code":"AUTO_PACKAGE_FAILED"}')
        raise SystemExit(2) from None
