"""The QA wrapper must not convert missing or failed execution to success."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.qa import junit_counts, passed


@pytest.mark.parametrize("exit_code,counts", [
    (0, {"collected": 0, "failed": 0, "skipped": 0}),
    (7, {"collected": 1, "failed": 0, "skipped": 0}),
    (0, {"collected": 1, "failed": 1, "skipped": 0}),
    (0, {"collected": 1, "failed": 0, "skipped": 1}),
])
def test_wrapper_rejects_false_success(exit_code, counts):
    assert not passed(exit_code, counts)


def test_junit_errors_and_skips_are_counted(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuites><testsuite><testcase name="ok"/><testcase name="bad"><error/></testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuites>')
    assert junit_counts(path) == {"collected": 3, "failed": 1, "skipped": 1}


def test_unavailable_windows_suite_stays_blocked():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "tools/qa.py", "--suite", "windows"], cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "BLOCKED"
