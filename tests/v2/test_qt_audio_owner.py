"""Windows-only subprocess probes for the synthetic Qt audio owner."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QT_PYTHON = ROOT.parent / "qt-dev-venv" / "Scripts" / "python.exe"


@pytest.mark.parametrize("case,reason", [
    ("normal", "DRAINED"),
    ("partial", "DRAINED"),
    ("early_idle", "DRAINED"),
    ("stop", "STOP_FENCED"),
    ("device_loss", "DEVICE_LOST"),
    ("no_ack", "NO_ACK_REJECTED"),
    ("negative_write", "DEVICE_LOST"),
    ("physical_without_opt_in", "PHYSICAL_BACKEND_REJECTED"),
])
def test_synthetic_qt_owner_case(case: str, reason: str) -> None:
    qt_python = Path(os.environ.get("MITHRIL_QT_PYTHON", DEFAULT_QT_PYTHON))
    assert qt_python.is_file(), "Set MITHRIL_QT_PYTHON to the isolated PySide6 interpreter"
    run = subprocess.run(
        [str(qt_python), str(ROOT / "tools" / "qt_audio_owner_probe.py"),
         "--case", case],
        cwd=ROOT, capture_output=True, text=True, timeout=12, check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout)
    assert report["status"] == "PASSED"
    assert report["reason"] == reason
    assert report["backend_off_main_thread"] is True
    assert report["physical_enabled"] is False
    assert report["selected_endpoint"] == "synthetic-selected-endpoint"
    assert report["verified_pcm_bytes"] == 1920
