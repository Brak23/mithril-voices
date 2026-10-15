"""Run reviewed pinned tests in the disposable copy, never the preserved worktree."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
COPY = ROOT / "baseline-probe"
os.chdir(COPY)
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
sys.path.insert(0, str(COPY))
sys.dont_write_bytecode = True

from src.config.ConfigManager import ConfigManager

ConfigManager.USER_DATA_DIR = ROOT / "baseline-probe-state"


def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise RuntimeError(f"External effects disabled for baseline discovery: {event}")


sys.addaudithook(audit)

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
