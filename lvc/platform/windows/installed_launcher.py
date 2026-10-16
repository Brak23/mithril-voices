"""Checked foreground launcher for a versioned personal Windows installation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TASK_ROOT = ROOT.parent
MANIFEST = ROOT / "personal-build.json"
LOG = ROOT / ".audition" / "logs" / "launch.jsonl"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_LOG_BYTES = 1024 * 1024

GUIDANCE = {
    "BUILD_MANIFEST_MISSING": "Run the personal package installer again.",
    "BUILD_MANIFEST_INVALID": "Run the personal package installer again.",
    "PACKAGE_FILE_CHANGED": "Use the previous launcher or reinstall this build.",
    "PYTHON_RUNTIME_UNAVAILABLE": "Restore the existing task Python environment.",
    "QT_RUNTIME_UNAVAILABLE": "Restore the existing Qt development environment.",
    "VOICE_RUNTIME_UNAVAILABLE": "Restore the existing local Kokoro environment.",
    "VOICE_RUNTIME_VERSION_CHANGED": "Use the previous launcher; the pinned voice runtime changed.",
    "CAPTURE_HELPER_MISSING": "Restore the reviewed local window capture helper.",
    "CAPTURE_HELPER_CHANGED": "Rebuild the reviewed capture helper before reinstalling.",
    "OCR_HELPER_MISSING": "Restore the reviewed Windows OCR helper.",
    "OCR_HELPER_CHANGED": "Rebuild the reviewed Windows OCR helper before reinstalling.",
    "VOICE_ASSET_MISSING": "Restore the previously approved local voice assets.",
    "VOICE_ASSET_CHANGED": "Restore the pinned local asset; do not substitute a new model.",
    "DISPLAY_RUNTIME_UNAVAILABLE": "Restore the task Pillow/Tk environment.",
}


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _manifest() -> dict[str, object]:
    try:
        if MANIFEST.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("BUILD_MANIFEST_INVALID")
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("BUILD_MANIFEST_MISSING") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("BUILD_MANIFEST_INVALID") from exc
    if (not isinstance(data, dict)
            or set(data) != {"format", "build_id", "source_commit", "files",
                                 "helpers", "assets", "runtime_versions", "qt_version"}
            or data["format"] != 1
            or not isinstance(data["build_id"], str)
            or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{8}", data["build_id"])
            or not isinstance(data["source_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", data["source_commit"])
            or not isinstance(data["qt_version"], str)):
        raise ValueError("BUILD_MANIFEST_INVALID")
    for key in ("files", "helpers", "assets", "runtime_versions"):
        if not isinstance(data[key], dict) or not data[key]:
            raise ValueError("BUILD_MANIFEST_INVALID")
    return data


def _log(event: str, build_id: str, code: str) -> None:
    """Only codes and build identity; never titles, paths, OCR, or speech text."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:
            LOG.replace(LOG.with_suffix(".jsonl.1"))
        record = {"at_utc": datetime.now(timezone.utc).isoformat(),
                  "build_id": build_id, "event": event, "code": code}
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        print("Launch log unavailable; check the package folder permissions.", file=sys.stderr)


def _runtime_matches(python: Path, versions: dict[str, str]) -> bool:
    if not python.is_file():
        return False
    code = (
        "import json,struct,sys,importlib.metadata as m; "
        "names=json.loads(sys.stdin.read()); "
        "print(json.dumps({'python':list(sys.version_info[:2]),'bits':struct.calcsize('P')*8,"
        "'versions':{name:m.version(name) for name in names}}))"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", code], input=json.dumps(list(versions)).encode(),
            cwd=ROOT, capture_output=True, timeout=12, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        )
        if completed.returncode or len(completed.stdout) > 4096:
            return False
        value = json.loads(completed.stdout)
        return (value["python"] == [3, 12] and value["bits"] == 64
                and value["versions"] == versions)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return False


def preflight() -> tuple[str, list[str], list[str]]:
    """Return build ID, required failure codes, and optional warnings."""
    try:
        manifest = _manifest()
    except ValueError as exc:
        return "unknown", [str(exc)], []
    build_id = str(manifest["build_id"])
    errors: list[str] = []
    warnings: list[str] = []

    def matches(path: Path, digest: object) -> bool:
        try:
            return (isinstance(digest, str) and path.is_file()
                    and _sha256(path) == digest)
        except OSError:
            return False

    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        errors.append("PYTHON_RUNTIME_UNAVAILABLE")
    if importlib.util.find_spec("PIL") is None or importlib.util.find_spec("tkinter") is None:
        errors.append("DISPLAY_RUNTIME_UNAVAILABLE")
    files = manifest["files"]
    assert isinstance(files, dict)
    for name, digest in files.items():
        if (not isinstance(name, str) or not name.startswith(("lvc/", "tools/"))
                or ".." in Path(name).parts or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            errors.append("BUILD_MANIFEST_INVALID")
            break
        path = ROOT / name
        if not matches(path, digest):
            errors.append("PACKAGE_FILE_CHANGED")
            break
    helpers = manifest["helpers"]
    assert isinstance(helpers, dict)
    for name, absent, changed in (
        ("lotro_frame_probe.exe", "CAPTURE_HELPER_MISSING", "CAPTURE_HELPER_CHANGED"),
        ("windows_ocr_stdin.exe", "OCR_HELPER_MISSING", "OCR_HELPER_CHANGED"),
    ):
        path = TASK_ROOT / "test-tmp" / name
        if not path.is_file():
            errors.append(absent)
        elif not matches(path, helpers.get(name)):
            errors.append(changed)
    assets = manifest["assets"]
    assert isinstance(assets, dict)
    for name, digest in assets.items():
        if not isinstance(name, str) or Path(name).name != name or not isinstance(digest, str):
            errors.append("BUILD_MANIFEST_INVALID")
            break
        path = ROOT / ".audition" / "assets" / name
        if not path.is_file():
            errors.append("VOICE_ASSET_MISSING")
            break
        if not matches(path, digest):
            errors.append("VOICE_ASSET_CHANGED")
            break
    qt_version = manifest["qt_version"]
    versions = manifest["runtime_versions"]
    assert isinstance(qt_version, str) and isinstance(versions, dict)
    if not _runtime_matches(TASK_ROOT / "qt-dev-venv" / "Scripts" / "python.exe",
                            {"PySide6": qt_version}):
        errors.append("QT_RUNTIME_UNAVAILABLE")
    if not _runtime_matches(ROOT / ".audition-venv" / "Scripts" / "python.exe",
                            versions):
        errors.append("VOICE_RUNTIME_VERSION_CHANGED" if
                      (ROOT / ".audition-venv" / "Scripts" / "python.exe").is_file()
                      else "VOICE_RUNTIME_UNAVAILABLE")
    if not Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").is_file():
        warnings.append("TESSERACT_OPTIONAL_UNAVAILABLE")
    return build_id, sorted(set(errors)), warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Verify without game capture or audio")
    action.add_argument("--version", action="store_true", help="Show installed build identity")
    args = parser.parse_args()
    build_id, errors, warnings = preflight()
    if args.version:
        print(f"Mithril Voices Personal {build_id}")
        return 0 if build_id != "unknown" else 2
    _log("PREFLIGHT", build_id, "READY" if not errors else ",".join(errors))
    print(f"Mithril Voices Personal {build_id}")
    if errors:
        for code in errors:
            print(f"BLOCKED {code}: {GUIDANCE.get(code, 'Run the installer check.')}")
        return 2
    for warning in warnings:
        print(f"Optional: {warning}; Windows OCR remains available.")
    if args.check:
        print("Ready. This check did not capture a window or open an audio device.")
        return 0
    print("Choose the exact LOTRO window for one manual capture; no background capture starts.")
    try:
        from lvc.platform.windows.lotro_user_probe import main as probe_main

        result = probe_main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        _log("SESSION_EXIT", build_id, "CAPTURE_OR_PREVIEW_FAILED")
        print("Probe stopped safely. Run Check Mithril Voices and retry.", file=sys.stderr)
        return 2
    _log("SESSION_EXIT", build_id, "CLOSED" if result == 0 else "CAPTURE_BLOCKED")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
