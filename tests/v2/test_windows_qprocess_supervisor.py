"""Windows-only outcomes for the owned synthetic QProcess supervisor."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QT_PYTHON = ROOT.parent / "qt-dev-venv" / "Scripts" / "python.exe"
PROBE = ROOT / "tools" / "windows_qprocess_supervisor_probe.py"


@pytest.mark.parametrize("case,outcome", [
    ("startup_failure", "STARTUP_FAILED"),
    ("containment_failure", "CONTAINMENT_FAILED"),
    ("startup_timeout", "STARTUP_TIMEOUT"),
    ("malformed", "PROTOCOL_INVALID"),
    ("wrong_sequence", "PROTOCOL_INVALID"),
    ("cancel_hang", "CANCELED"),
    ("late_canceled", "CANCELED"),
])
def test_controlled_windows_qprocess_lifecycle(case, outcome):
    assert sys.platform == "win32", "This lane requires the selected Windows runner"
    assert QT_PYTHON.is_file(), "Pinned isolated PySide6 runner missing"
    result = subprocess.run([str(QT_PYTHON), str(PROBE), "--case", case],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=12, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "PASSED" and report["outcome"] == outcome
    assert report["other_processes_targeted"] is False
    if case in {"startup_failure", "containment_failure"}:
        assert not report["job_assigned"] and not report["descendant_spawned"]
    else:
        assert report["job_assigned"]
        assert report["parent_reclaimed"] and report["descendant_reclaimed"]
    if case == "cancel_hang":
        assert report["cancel_ack_seen"] and report["running_after_ack"]
        assert report["cancel_ack_after_ms"] <= 250
        assert report["termination_requested_after_ms"] >= 1000
        assert report["effective_terminal_count"] == 1
    if case == "late_canceled":
        assert report["stale_terminals"] == 1
        assert report["cancel_ack_after_ms"] <= 250
        assert report["effective_terminal_count"] == 1
        assert report["termination_requested_after_ms"] >= 1000
