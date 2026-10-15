"""Harmless finite-life parent/descendant for the Windows Job Object probe."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def wait_finite(seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.05)


def main() -> int:
    if sys.argv[1:] == ["--descendant"]:
        wait_finite()
        return 0
    if sys.argv[1:] != ["--parent"]:
        return 2
    if sys.stdin.buffer.readline().strip() != b"start":
        return 3
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--descendant"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print(json.dumps({"type": "ready", "descendant_pid": child.pid}), flush=True)
    if sys.stdin.buffer.readline().strip() != b"cancel":
        return 4
    print(json.dumps({"type": "cancel_ack"}), flush=True)
    wait_finite()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
