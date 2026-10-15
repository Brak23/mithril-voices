"""Windows-only, bounded Job Object probe against our own harmless child tree.

This is evidence for one controlled descendant, not a production QProcess
launcher or a qualification of arbitrary inherited job restrictions.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
CHILD = Path(__file__).resolve().parent / "fixtures" / "windows_job_child.py"
ROOT = Path(__file__).resolve().parents[1]


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("per_process_time", ctypes.c_longlong), ("per_job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes"
    )]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class JobApiError(OSError):
    def __init__(self, operation: str):
        self.operation = operation
        self.winerror = ctypes.get_last_error()
        super().__init__(f"{operation} failed with Windows error {self.winerror}")


def kernel32() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                            ctypes.c_void_p, wintypes.DWORD]
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                  ctypes.POINTER(wintypes.BOOL)]
    api.IsProcessInJob.restype = wintypes.BOOL
    api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateJobObject.restype = wintypes.BOOL
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


class OwnedJob:
    """An unnamed job that can contain only a child explicitly assigned here."""

    def __init__(self, api: Any):
        self.api = api
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise JobApiError("CreateJobObjectW")
        self.assigned_pid: int | None = None
        limits = ExtendedLimits()
        limits.basic.flags = KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                           ctypes.byref(limits), ctypes.sizeof(limits)):
            error = JobApiError("SetInformationJobObject")
            self.close()
            raise error

    def assign_owned_child(self, child: subprocess.Popen[str]) -> None:
        if self.assigned_pid is not None or child.pid == os.getpid() or child.poll() is not None:
            raise ValueError("Only one live child created by this probe may be assigned")
        handle = getattr(child, "_handle", None)
        if handle is None:
            raise RuntimeError("Popen child process handle unavailable")
        if not self.api.AssignProcessToJobObject(self.handle, handle):
            raise JobApiError("AssignProcessToJobObject")
        self.assigned_pid = child.pid
        if not self.contains(handle):
            raise RuntimeError("Assigned child is not observable in its new job")

    def contains(self, process_handle: int) -> bool:
        result = wintypes.BOOL()
        if not self.api.IsProcessInJob(process_handle, self.handle, ctypes.byref(result)):
            raise JobApiError("IsProcessInJob")
        return bool(result.value)

    def in_any_job(self, process_handle: int) -> bool:
        result = wintypes.BOOL()
        if not self.api.IsProcessInJob(process_handle, None, ctypes.byref(result)):
            raise JobApiError("IsProcessInJob inherited")
        return bool(result.value)

    def terminate_owned_tree(self) -> None:
        if self.assigned_pid is None:
            raise RuntimeError("Refusing to terminate an unassigned job")
        if not self.api.TerminateJobObject(self.handle, 9):
            raise JobApiError("TerminateJobObject")

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def line_with_deadline(stream: Any, timeout_s: float) -> dict[str, Any]:
    result: queue.Queue[str] = queue.Queue(maxsize=1)
    threading.Thread(target=lambda: result.put(stream.readline()), daemon=True).start()
    try:
        line = result.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise TimeoutError("Controlled child did not answer within its deadline") from exc
    if not line or len(line) > 256:
        raise ValueError("Controlled child reply missing or oversized")
    message = json.loads(line)
    if not isinstance(message, dict):
        raise TypeError("Controlled child reply was not an object")
    return message


def run_probe(mode: str) -> tuple[dict[str, Any], int]:
    if mode not in {"terminate", "close"}:
        raise ValueError("Unknown Job Object termination mode")
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    report: dict[str, Any] = {
        "scope": "WINDOWS_CONTROLLED_JOB_OBJECT_PROBE_NOT_PRODUCTION_SUPERVISOR",
        "platform": platform.system(), "python": platform.python_version(),
        "code_sha": base_sha, "dirty_tree": dirty,
        "input_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"):
                         hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (Path(__file__).resolve(), CHILD)},
        "termination_mode": mode,
        "status": "BLOCKED", "parent_assigned": False, "descendant_assigned": False,
        "cancel_ack_seen": False, "parent_reclaimed": False, "descendant_reclaimed": False,
        "other_processes_targeted": False,
        "limits": ["Only this probe's finite-life Python child tree is used",
                   "Production startup race, inherited jobs, QProcess and LOTRO are not qualified"],
    }
    if (sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8
            or ctypes.sizeof(ExtendedLimits) != 144):
        report["reason"] = "Windows x64 required"
        return report, 2
    api = kernel32()
    job: OwnedJob | None = None
    parent: subprocess.Popen[str] | None = None
    descendant_handle: int | None = None
    try:
        job = OwnedJob(api)
        parent = subprocess.Popen(
            [sys.executable, str(CHILD), "--parent"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # The child blocks on stdin and cannot create a descendant before this assignment.
        child_handle = getattr(parent, "_handle", None)
        if child_handle is None:
            raise RuntimeError("Popen child process handle unavailable")
        report["inherited_job_before_assignment"] = job.in_any_job(child_handle)
        job.assign_owned_child(parent)
        report["parent_assigned"] = True
        if parent.stdin is None or parent.stdout is None:
            raise RuntimeError("Controlled child pipes unavailable")
        parent.stdin.write("start\n")
        parent.stdin.flush()
        ready = line_with_deadline(parent.stdout, 3.0)
        descendant_pid = ready.get("descendant_pid")
        if ready.get("type") != "ready" or type(descendant_pid) is not int or descendant_pid <= 0:
            raise ValueError("Controlled descendant handshake invalid")
        descendant_handle = api.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, descendant_pid,
        )
        if not descendant_handle:
            raise JobApiError("OpenProcess descendant")
        report["descendant_assigned"] = job.contains(descendant_handle)
        if not report["descendant_assigned"]:
            raise RuntimeError("Controlled descendant escaped the job")
        parent.stdin.write("cancel\n")
        parent.stdin.flush()
        report["cancel_ack_seen"] = line_with_deadline(parent.stdout, 3.0) == {"type": "cancel_ack"}
        if not report["cancel_ack_seen"]:
            raise ValueError("Controlled child did not acknowledge cancellation")
        start = time.monotonic()
        while time.monotonic() - start < 1.0 and parent.poll() is None:
            time.sleep(0.01)
        report["still_running_after_ack"] = parent.poll() is None
        report["termination_requested_after_ms"] = round((time.monotonic() - start) * 1000)
        if mode == "terminate":
            job.terminate_owned_tree()
        else:
            job.close()  # KILL_ON_JOB_CLOSE must reclaim this owned tree.
        parent_handle = getattr(parent, "_handle", None)
        if parent_handle is None:
            raise RuntimeError("Popen child process handle unavailable")
        report["parent_reclaimed"] = api.WaitForSingleObject(parent_handle, 2000) == WAIT_OBJECT_0
        report["descendant_reclaimed"] = api.WaitForSingleObject(descendant_handle, 2000) == WAIT_OBJECT_0
        report["status"] = "PASSED" if all(report[key] for key in (
            "parent_assigned", "descendant_assigned", "cancel_ack_seen",
            "still_running_after_ack", "parent_reclaimed", "descendant_reclaimed",
        )) and report["termination_requested_after_ms"] >= 1000 else "FAILED"
        return report, 0 if report["status"] == "PASSED" else 1
    except JobApiError as exc:
        report["status"] = "BLOCKED" if exc.operation == "AssignProcessToJobObject" else "FAILED"
        report["reason"] = exc.operation
        report["winerror"] = exc.winerror
        return report, 2 if report["status"] == "BLOCKED" else 1
    except (OSError, ValueError, TypeError, RuntimeError, TimeoutError) as exc:
        report["status"] = "FAILED"
        report["reason"] = type(exc).__name__
        return report, 1
    finally:
        if job is not None:
            job.close()  # KILL_ON_JOB_CLOSE also covers exceptions after assignment.
        if parent is not None:
            if parent.poll() is None:
                parent.kill()  # Exact Popen child only, never a process-name or system-wide kill.
            try:
                parent.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            for stream in (parent.stdin, parent.stdout, parent.stderr):
                if stream is not None:
                    stream.close()
        if descendant_handle:
            api.CloseHandle(descendant_handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--mode", choices=["terminate", "close"], default="terminate")
    args = parser.parse_args()
    report, code = run_probe(args.mode)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
