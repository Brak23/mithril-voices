"""One silent, supervised local resident Kokoro protocol smoke on Windows."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from lvc.tts.resident_kokoro_worker import SPOOL_ROOT
from lvc.voice.cache import validate_complete_wav
from tools.windows_job_probe import OwnedJob, kernel32

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".audition-venv" / "Scripts" / "python.exe"
TEXT = "The lanterns are lit. The gate is open."
MAX_REPLY = 16_384


def receive(stream, events: queue.Queue[dict[str, object]]) -> None:
    while True:
        raw = stream.readline(MAX_REPLY + 1)
        if not raw:
            events.put({"event": "EOF"})
            return
        if len(raw) > MAX_REPLY:
            events.put({"event": "BAD_REPLY"})
            return
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise TypeError("Invalid response")
            events.put(value)
        except (UnicodeError, ValueError, TypeError):
            events.put({"event": "BAD_REPLY"})
            return


def send(stream, message: dict[str, object]) -> None:
    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
    if len(payload) > 16_384:
        raise ValueError("Probe command too long")
    stream.write(payload)
    stream.flush()


def run() -> dict[str, object]:
    if sys.platform != "win32" or not PYTHON.is_file():
        raise RuntimeError("WINDOWS_VOICE_RUNTIME_UNAVAILABLE")
    SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
    spool = SPOOL_ROOT / str(uuid4())
    spool.mkdir(exist_ok=False)
    nonce, request, warm_request = str(uuid4()), str(uuid4()), str(uuid4())
    started = time.perf_counter()
    process: subprocess.Popen[bytes] | None = None
    job: OwnedJob | None = None
    try:
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "TMP": str(spool),
               "TEMP": str(spool)}
        process = subprocess.Popen(
            [str(PYTHON), "-u", "-m", "lvc.tts.resident_kokoro_worker",
             "--voice", "bf_emma", "--spool", str(spool), "--nonce", nonce],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job = OwnedJob(kernel32())
        handle = getattr(process, "_handle", None)
        if handle is None:
            raise RuntimeError("CHILD_HANDLE_UNAVAILABLE")
        job.assign_owned_handle(process.pid, handle)
        assert process.stdin is not None and process.stdout is not None
        events: queue.Queue[dict[str, object]] = queue.Queue()
        threading.Thread(target=receive, args=(process.stdout, events), daemon=True).start()
        ready = events.get(timeout=45)
        if ready != {"event": "READY", "nonce": nonce, "voice": "bf_emma"}:
            raise RuntimeError("WORKER_READY_INVALID")
        ready_s = time.perf_counter() - started
        send(process.stdin, {"action": "render", "request_id": request,
                             "generation": 1, "voice": "bf_emma", "text": TEXT})
        rows: list[dict[str, object]] = []
        first_s: float | None = None
        for index in range(2):
            reply = events.get(timeout=40)
            if (reply.get("event") != "UNIT_READY" or reply.get("request_id") != request
                    or reply.get("generation") != 1 or reply.get("index") != index
                    or reply.get("total") != 2):
                raise RuntimeError("UNIT_REPLY_INVALID")
            path = spool / request / f"{index:02d}.wav"
            if reply.get("path") != str(path) or not path.is_file():
                raise RuntimeError("UNIT_PATH_INVALID")
            data = path.read_bytes()
            if (reply.get("sha256") != hashlib.sha256(data).hexdigest()
                    or reply.get("frames") != validate_complete_wav(data)):
                raise RuntimeError("UNIT_BYTES_INVALID")
            rows.append({"frames": reply["frames"], "bytes": len(data)})
            if first_s is None:
                first_s = time.perf_counter() - started
            if index == 0:
                send(process.stdin, {"action": "next", "request_id": request,
                                     "generation": 1, "after_index": 0})
        done = events.get(timeout=5)
        if done != {"event": "DONE", "request_id": request,
                    "generation": 1, "total": 2}:
            raise RuntimeError("DONE_INVALID")
        warm_started = time.perf_counter()
        send(process.stdin, {"action": "render", "request_id": warm_request,
                             "generation": 2, "voice": "bf_emma",
                             "text": "The silver map points toward the northern gate."})
        warm = events.get(timeout=40)
        if (warm.get("event") != "UNIT_READY" or warm.get("request_id") != warm_request
                or warm.get("generation") != 2 or warm.get("index") != 0
                or warm.get("total") != 1):
            raise RuntimeError("WARM_UNIT_INVALID")
        warm_ms = round((time.perf_counter() - warm_started) * 1000, 2)
        warm_path = spool / warm_request / "00.wav"
        if warm.get("path") != str(warm_path) or not warm_path.is_file():
            raise RuntimeError("WARM_UNIT_PATH_INVALID")
        warm_bytes = warm_path.read_bytes()
        if (warm.get("sha256") != hashlib.sha256(warm_bytes).hexdigest()
                or warm.get("frames") != validate_complete_wav(warm_bytes)):
            raise RuntimeError("WARM_UNIT_BYTES_INVALID")
        if events.get(timeout=5) != {"event": "DONE", "request_id": warm_request,
                                     "generation": 2, "total": 1}:
            raise RuntimeError("WARM_DONE_INVALID")
        send(process.stdin, {"action": "shutdown"})
        if process.wait(timeout=5) != 0:
            raise RuntimeError("WORKER_EXIT_INVALID")
        return {"status": "PASSED", "scope": "SILENT_LOCAL_WORKER_SMOKE",
                "ready_ms": round(ready_s * 1000, 2),
                "first_unit_ms": round((first_s or 0) * 1000, 2),
                "warm_request_ms": warm_ms,
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
                "units": rows, "audio_played": False, "lotro_used": False}
    finally:
        if process is not None and process.poll() is None:
            if job is not None and job.assigned_pid is not None:
                job.terminate_owned_tree()
            else:
                process.kill()
            process.wait(timeout=5)
        if job is not None:
            job.close()
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
        resolved = spool.resolve()
        if resolved.parent == SPOOL_ROOT.resolve() and resolved.name == spool.name:
            shutil.rmtree(resolved)


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except (OSError, RuntimeError, ValueError, queue.Empty, subprocess.TimeoutExpired) as exc:
        _ = exc  # Never print text, private paths, or model exception detail.
        print('{"status":"BLOCKED","code":"RESIDENT_SMOKE_FAILED"}')
        raise SystemExit(2) from None
