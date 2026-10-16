"""Stage versioned personal source snapshots and checked Desktop launchers.

No model, voice, game file, or third-party runtime is copied for distribution.
The snapshots link only to previously installed local development dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

from lvc.platform.windows.manual_preferences import PreferencesStore
from lvc.tts.kokoro_cpu import (
    CONFIG_SHA256,
    MODEL_SHA256,
    RUNTIME_VERSIONS,
    VOICE_SHA256,
)

ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = ROOT.parent
KNOWN_WORKING = "790bf46947dc0f2ebc3336f8ec20f8d48dcc36d7"
HELPERS = {
    "lotro_frame_probe.exe": "3e64737ea1feb5805e5f8430546b7c4d4566a6b40b97635502fad90db277d9ba",
    "windows_ocr_stdin.exe": "159a2fc8a35e7eb9ff151b78566d6977145fa2ec2d6f40cf1ce51b261eeb87e3",
}
ASSETS = {"config.json": CONFIG_SHA256, "kokoro-v1_0.pth": MODEL_SHA256,
          **{f"{name}.pt": digest for name, digest in VOICE_SHA256.items()}}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def _archive(ref: str) -> bytes:
    completed = subprocess.run(
        ["git", "archive", "--format=zip", ref, "lvc", "tools/windows_job_probe.py",
         "LICENSE", "README.md"],
        cwd=ROOT, capture_output=True, timeout=30, check=False)
    if completed.returncode or len(completed.stdout) > 32 * 1024 * 1024:
        raise RuntimeError("SOURCE_ARCHIVE_UNAVAILABLE")
    return completed.stdout


def _extract(data: bytes, target: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            name = Path(item.filename)
            if (name.is_absolute() or ".." in name.parts
                    or not name.parts or name.parts[0] not in {
                        "lvc", "tools", "LICENSE", "README.md"}):
                raise RuntimeError("SOURCE_ARCHIVE_INVALID")
            destination = target / name
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(item))


def _source_files(target: Path) -> dict[str, str]:
    paths = sorted(path for path in (target / "lvc").rglob("*")
                   if path.is_file() and path.suffix in {".py", ".json"})
    paths.append(target / "tools" / "windows_job_probe.py")
    return {path.relative_to(target).as_posix(): sha256(path) for path in paths}


def _build_id(commit: str, files: dict[str, str]) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return f"{commit[:8]}-{hashlib.sha256(canonical).hexdigest()[:8]}"


def _verified_dependencies() -> str:
    for name, expected in HELPERS.items():
        path = TASK_ROOT / "test-tmp" / name
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError("NATIVE_HELPER_UNAVAILABLE_OR_CHANGED")
    for name, expected in ASSETS.items():
        path = ROOT / ".audition" / "assets" / name
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError("APPROVED_VOICE_ASSET_UNAVAILABLE_OR_CHANGED")
    for path in (ROOT / ".venv", ROOT / ".audition-venv", TASK_ROOT / "qt-dev-venv"):
        if not (path / "Scripts" / "python.exe").is_file():
            raise RuntimeError("EXISTING_RUNTIME_UNAVAILABLE")
    version = subprocess.check_output(
        [str(TASK_ROOT / "qt-dev-venv" / "Scripts" / "python.exe"), "-c",
         "import importlib.metadata as m; print(m.version('PySide6'))"],
        cwd=ROOT, text=True, timeout=8).strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
        raise RuntimeError("QT_RUNTIME_VERSION_INVALID")
    return version


def _safe_remove_temporary(path: Path) -> None:
    if (path.resolve().parent != TASK_ROOT.resolve()
            or not path.name.startswith(".mithril-package-building-")):
        raise RuntimeError("TEMPORARY_PATH_OUTSIDE_TASK_ROOT")
    for link in (path / ".venv", path / ".audition-venv",
                 path / ".audition" / "assets"):
        if link.is_symlink():
            link.unlink()
    shutil.rmtree(path)


def _stage_snapshot(ref: str, *, previous: bool, qt_version: str) -> tuple[Path, str]:
    temporary = TASK_ROOT / f".mithril-package-building-{uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    try:
        _extract(_archive(ref), temporary)
        if previous:
            # The proven manual flow predates the personal checked launcher.
            # Only this wrapper is injected; all game and speech code is exact ref.
            wrapper = temporary / "lvc" / "platform" / "windows" / "installed_launcher.py"
            wrapper.write_bytes((ROOT / "lvc" / "platform" / "windows" /
                                 "installed_launcher.py").read_bytes())
        files = _source_files(temporary)
        build_id = _build_id(ref, files)
        folder = TASK_ROOT / ("Mithril Voices Known Working " if previous
                              else "Mithril Voices Personal ")
        destination = folder.with_name(folder.name + build_id)
        manifest = {"format": 1, "build_id": build_id, "source_commit": ref,
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
            existing = destination / "personal-build.json"
            if not existing.is_file() or existing.read_bytes() != (
                    temporary / "personal-build.json").read_bytes():
                raise RuntimeError("PACKAGE_VERSION_PATH_CONFLICT")
            return destination, build_id
        os.replace(temporary, destination)
        return destination, build_id
    finally:
        if temporary.exists():
            _safe_remove_temporary(temporary)


def _cmd(snapshot: Path, *, pause: bool = True) -> str:
    quoted = str(snapshot)
    if '"' in quoted or "\r" in quoted or "\n" in quoted:
        raise ValueError("Invalid snapshot path")
    lines = ["@echo off", "setlocal", f'cd /d "{quoted}" || exit /b 2',
             'if not exist ".venv\\Scripts\\python.exe" (',
             "  echo Existing task Python environment is missing.",
             "  exit /b 2", ")",
             '".venv\\Scripts\\python.exe" -u -m lvc.platform.windows.installed_launcher %*',
             'set "mithril_status=%ERRORLEVEL%"']
    if pause:
        lines.extend(['if /I "%~1"=="--check" exit /b %mithril_status%',
                      'if /I "%~1"=="--version" exit /b %mithril_status%',
                      'echo.', 'echo Mithril Voices finished. Press a key to close.',
                      'pause', 'exit /b %mithril_status%'])
    else:
        lines.append('exit /b %mithril_status%')
    return "\r\n".join(lines) + "\r\n"


def _preflight(snapshot: Path) -> None:
    result = subprocess.run(
        [str(snapshot / ".venv" / "Scripts" / "python.exe"), "-u", "-m",
         "lvc.platform.windows.installed_launcher", "--check"],
        cwd=snapshot, capture_output=True, text=True, timeout=35, check=False)
    if result.returncode or "Ready." not in result.stdout:
        raise RuntimeError(f"PACKAGE_PREFLIGHT_BLOCKED:{result.stdout[-800:]}")


def _write_atomic(path: Path, value: str, *, encoding: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding=encoding)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _carry_preferences(desktop: Path, active: Path) -> None:
    prior_manifest = desktop / "Mithril Voices" / "installation.json"
    try:
        if prior_manifest.stat().st_size > 4096:
            return
        prior = json.loads(prior_manifest.read_text(encoding="utf-8"))
        old_root = Path(prior["active_snapshot"])
        if (old_root.resolve().parent != TASK_ROOT.resolve()
                or not old_root.name.startswith("Mithril Voices Personal ")):
            return
        voices = ("bf_emma", "bm_fable")
        saved, issue = PreferencesStore(old_root / ".audition" / "preferences.json",
                                        voices).load()
        target = active / ".audition" / "preferences.json"
        if issue is None and not target.exists():
            PreferencesStore(target, voices).save(saved)
    except (OSError, ValueError, KeyError, TypeError):
        return


def stage(desktop: Path) -> dict[str, str]:
    if not desktop.is_dir():
        raise RuntimeError("DESKTOP_UNAVAILABLE")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("COMMIT_CODE_BEFORE_STAGING")
    current = _git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", current):
        raise RuntimeError("SOURCE_COMMIT_INVALID")
    qt_version = _verified_dependencies()
    active, active_id = _stage_snapshot(current, previous=False, qt_version=qt_version)
    previous, previous_id = _stage_snapshot(KNOWN_WORKING, previous=True,
                                            qt_version=qt_version)
    _preflight(active)
    _preflight(previous)
    _carry_preferences(desktop, active)
    package = desktop / "Mithril Voices"
    package.mkdir(exist_ok=True)
    active_cmd = _cmd(active)
    previous_cmd = _cmd(previous)
    check_cmd = _cmd(active)
    _write_atomic(package / "Check Mithril Voices.cmd",
        check_cmd.replace("installed_launcher %*", "installed_launcher --check"),
        encoding="ascii")
    _write_atomic(package / "Mithril Voices (previous).cmd", previous_cmd,
                  encoding="ascii")
    _write_atomic(package / "README.txt",
        "Mithril Voices personal Windows installation\n\n"
        f"Current build: {active_id}\nKnown working manual-flow fallback: {previous_id}\n\n"
        "Double-click the Mithril Voices.cmd file on the Desktop. Choose the exact "
        "LOTRO window, type its displayed CAPTURE phrase, then check/edit and explicitly "
        "confirm the quest body before Read. Stop is always available.\n\n"
        "Run Check Mithril Voices.cmd in this folder to verify local code, runtimes, "
        "native helpers, and installed voice assets without capture or audio. "
        "If the current build fails, use Mithril Voices (previous).cmd here. "
        "The previous build is the owner-tested manual flow without saved settings.\n\n"
        "Models and native helpers remain in the existing local task environment; "
        "they are not redistributed in this package. Do not move or delete that "
        "environment. Package snapshots and private settings/logs are under the "
        "versioned folders beside the repository. The log contains build IDs and "
        "status codes only, never screenshots or quest text. No background capture, "
        "autostart, or automatic narration is installed.\n",
        encoding="utf-8")
    _write_atomic(package / "installation.json", json.dumps({
        "active_build": active_id, "active_snapshot": str(active),
        "previous_build": previous_id, "previous_snapshot": str(previous),
        "dependency_root": str(ROOT)}, indent=2) + "\n", encoding="utf-8")
    _write_atomic(desktop / "Mithril Voices.cmd", active_cmd, encoding="ascii")
    return {"desktop_launcher": str(desktop / "Mithril Voices.cmd"),
            "support_folder": str(package), "active_snapshot": str(active),
            "previous_snapshot": str(previous), "active_build": active_id,
            "previous_build": previous_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", type=Path, default=Path.home() / "Desktop")
    args = parser.parse_args()
    try:
        print(json.dumps(stage(args.desktop.resolve()), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"PACKAGE_BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
