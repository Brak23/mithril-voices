"""Original synthetic wire worker; no capture, model, or audio output."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

CHILD = Path(__file__).resolve().parent / "windows_job_child.py"
PROTOCOL = {"major": 1, "minor": 0}


def emit(kind: str, init: dict, seq: int, payload: dict) -> None:
    message = {"protocol": PROTOCOL, "type": kind,
               "session_id": init["session_id"],
               "worker_instance_id": init["worker_instance_id"],
               "seq": seq, "payload": payload}
    sys.stdout.buffer.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def wait_finite() -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        time.sleep(0.05)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "startup_timeout", "malformed", "wrong_sequence", "cancel_hang", "late_canceled", "success"
    }:
        return 2
    mode = sys.argv[1]
    raw_init = sys.stdin.buffer.readline()
    if len(raw_init) > 262_144:
        return 3
    init = json.loads(raw_init)
    if init.get("type") != "init":
        return 4
    descendant = subprocess.Popen(
        [sys.executable, str(CHILD), "--descendant"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.stderr.write(f"probe-descendant:{descendant.pid}\n")
    sys.stderr.flush()
    if mode == "startup_timeout":
        wait_finite()
        return 0
    payload = init["payload"]
    emit("hello", init, 0, {"nonce": payload["nonce"], "role": "tts",
                           "runtime_id": "synthetic.qprocess.1",
                           "artifact_manifest_sha256": payload["artifact_manifest_sha256"]})
    emit("ready", init, 1, {"role": "tts", "runtime_id": "synthetic.qprocess.1",
                           "capabilities": ["synthesize"]})
    request = json.loads(sys.stdin.buffer.readline())
    if request.get("type") != "synthesize":
        return 5
    request_id = request["payload"]["request_id"]
    emit("accepted", init, 2, {"request_id": request_id})
    if mode == "success":
        emit("completed", init, 3, {"request_id": request_id,
                                    "context": request["payload"]["context"],
                                    "result": {"kind": "audio",
                                               "unit_id": request["payload"]["unit_id"],
                                               "filename": f"{request_id}.wav",
                                               "sha256": "e" * 64, "bytes": 54,
                                               "sample_rate": 48000, "channels": 1,
                                               "sample_format": "s16le", "frame_count": 5}})
        return 0
    if mode == "malformed":
        sys.stdout.buffer.write(b'{"type":\n')
        sys.stdout.buffer.flush()
        wait_finite()
        return 0
    if mode == "wrong_sequence":
        emit("heartbeat", init, 4, {"active_request_id": request_id, "ready": True})
        wait_finite()
        return 0
    cancel = json.loads(sys.stdin.buffer.readline())
    if cancel.get("type") != "cancel" or cancel["payload"]["request_id"] != request_id:
        return 6
    emit("cancel_ack", init, 3, {"request_id": request_id})
    if mode == "late_canceled":
        emit("canceled", init, 4, {"request_id": request_id})
    wait_finite()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
