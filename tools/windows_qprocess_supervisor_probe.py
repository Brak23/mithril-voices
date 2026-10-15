"""Bounded Windows QProcess/Job Object integration against an original synthetic worker.

This fixture deliberately starts a worker that cannot spawn until the host's
init message. It does not qualify an arbitrary production worker launch race.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QCoreApplication, QProcess, QProcessEnvironment, QTimer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lvc.core import PageIdentity, RequestToken
from lvc.safeguards import WorkerLedger
from tools.validate_contracts import ContractError, validate_ipc
from tools.windows_job_probe import (
    PROCESS_QUERY_LIMITED_INFORMATION,
    SYNCHRONIZE,
    WAIT_OBJECT_0,
    OwnedJob,
    kernel32,
)

PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
MAX_LINE = 262_144
MAX_BUFFER = 1_048_576
SESSION = UUID("00000000-0000-4000-8000-000000000001")
WORKER = UUID("00000000-0000-4000-8000-000000000002")
REQUEST = UUID("00000000-0000-4000-8000-000000000003")
NONCE = "a" * 64
MANIFEST = "b" * 64
EXAMPLES = json.loads((ROOT / "docs/design-v2/contracts/ipc.examples.json").read_text(encoding="utf-8"))["examples"]


def strict_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def reject_constant(_: str) -> None:
    raise ValueError("nonfinite")


class Probe:
    def __init__(self, case: str):
        self.case = case
        self.app = QCoreApplication([])
        self.proc = QProcess()
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.api = kernel32()
        self.job = OwnedJob(self.api)
        self.parent_handle = None
        self.descendant_handle = None
        self.out = bytearray()
        self.err = bytearray()
        self.seq = 0
        self.host_seq = 0
        self.started_at = time.monotonic()
        self.cancel_at: float | None = None
        self.ledger = WorkerLedger(SESSION)
        self.result = {
            "case": case, "status": "BLOCKED", "outcome": None,
            "job_assigned": False, "descendant_spawned": False,
            "descendant_in_job": False, "parent_reclaimed": False,
            "descendant_reclaimed": False, "cancel_ack_seen": False,
            "cancel_ack_after_ms": None,
            "running_after_ack": False, "termination_requested_after_ms": None,
            "stale_terminals": 0, "effective_terminal_count": 0,
            "other_processes_targeted": False,
            "limits": "Synthetic gated worker only; production launch race and LOTRO unqualified",
        }
        self.proc.started.connect(self.started)
        self.proc.errorOccurred.connect(self.error)
        self.proc.readyReadStandardOutput.connect(self.read_stdout)
        self.proc.readyReadStandardError.connect(self.read_stderr)
        self.proc.finished.connect(self.finished)
        self.timer = QTimer()
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.watchdog = QTimer()
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(lambda: self.fail("WATCHDOG"))
        self.watchdog.start(6000)

    def ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def send(self, example_index: int) -> None:
        msg = EXAMPLES[example_index]
        assert msg["seq"] == self.host_seq
        validate_ipc(msg)
        wire = json.dumps(msg, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        if len(wire) > MAX_LINE or self.proc.write(wire) != len(wire):
            raise RuntimeError("outgoing IPC write rejected")
        self.host_seq += 1

    def started(self) -> None:
        try:
            pid = int(self.proc.processId())
            rights = PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
            self.parent_handle = self.api.OpenProcess(rights, False, pid)
            if not self.parent_handle or self.proc.state() != QProcess.Running or self.proc.processId() != pid:
                raise RuntimeError("owned process not available for assignment")
            if self.case == "containment_failure":
                raise RuntimeError("injected assignment failure")
            self.job.assign_owned_handle(pid, self.parent_handle)
            self.result["job_assigned"] = self.job.contains(self.parent_handle)
            self.send(0)  # The synthetic worker cannot spawn before init.
        except (OSError, RuntimeError, ValueError, ContractError, AssertionError):
            self.fail("CONTAINMENT_FAILED")

    def error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            self.result["outcome"] = "STARTUP_FAILED"
            self.app.quit()

    def read_stderr(self) -> None:
        self.err.extend(bytes(self.proc.readAllStandardError()))
        if len(self.err) > MAX_BUFFER:
            del self.err[:-MAX_BUFFER]
        for line in self.err.split(b"\n")[:-1]:
            if line.startswith(b"probe-descendant:") and not self.result["descendant_spawned"]:
                try:
                    pid = int(line.split(b":", 1)[1])
                    self.descendant_handle = self.api.OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
                    self.result["descendant_spawned"] = bool(self.descendant_handle)
                    self.result["descendant_in_job"] = bool(
                        self.descendant_handle and self.job.contains(self.descendant_handle))
                except (ValueError, OSError):
                    self.fail("DESCENDANT_INVALID")
        self.err = bytearray(self.err.rsplit(b"\n", 1)[-1])

    def read_stdout(self) -> None:
        self.out.extend(bytes(self.proc.readAllStandardOutput()))
        if len(self.out) > MAX_BUFFER:
            self.fail("PROTOCOL_INVALID")
            return
        count = 0
        deadline = time.monotonic() + 0.005
        while b"\n" in self.out and count < 32 and time.monotonic() < deadline:
            line, _, remainder = self.out.partition(b"\n")
            self.out = bytearray(remainder)
            if len(line) + 1 > MAX_LINE:
                self.fail("PROTOCOL_INVALID")
                return
            try:
                msg = json.loads(line.decode("utf-8"), object_pairs_hook=strict_pairs,
                                 parse_constant=reject_constant)
                if not isinstance(msg, dict):
                    raise TypeError("root")
                validate_ipc(msg)
                self.accept(msg)
            except (ValueError, UnicodeError, ContractError, KeyError, TypeError):
                self.fail("PROTOCOL_INVALID")
                return
            count += 1
        if len(self.out) > MAX_LINE and b"\n" not in self.out:
            self.fail("PROTOCOL_INVALID")
        elif b"\n" in self.out:
            QTimer.singleShot(0, self.read_stdout)

    def accept(self, msg: dict) -> None:
        if msg["session_id"] != str(SESSION) or msg["worker_instance_id"] != str(WORKER) or msg["seq"] != self.seq:
            raise ValueError("sender or sequence")
        self.seq += 1
        kind, payload = msg["type"], msg["payload"]
        if kind == "hello" and self.seq == 1:
            if payload["nonce"] != NONCE or payload["role"] != "tts" or payload["artifact_manifest_sha256"] != MANIFEST:
                raise ValueError("handshake")
        elif kind == "ready" and self.seq == 2:
            if payload["role"] != "tts" or "synthesize" not in payload["capabilities"]:
                raise ValueError("readiness")
            self.ledger = self.ledger.submit(RequestToken(
                REQUEST, SESSION, 1, 1, "manual",
                PageIdentity(UUID("00000000-0000-4000-8000-000000000011"), 1,
                             "quest_body", "synthetic")), WORKER, self.ms())
            self.send(2)
        elif kind == "accepted" and self.seq == 3:
            if payload["request_id"] != str(REQUEST):
                raise ValueError("request")
            if self.case in {"cancel_hang", "late_canceled"}:
                self.ledger, effects = self.ledger.cancel(REQUEST, self.ms())
                assert len(effects) == 1 and effects[0].kind == "send_cancel"
                self.cancel_at = time.monotonic()
                self.result["effective_terminal_count"] = 1
                self.send(5)
        elif kind == "cancel_ack" and self.seq == 4:
            if payload["request_id"] != str(REQUEST):
                raise ValueError("request")
            if self.cancel_at is None:
                raise ValueError("ack without cancel")
            self.ledger = self.ledger.cancel_ack(REQUEST, WORKER, self.ms())
            self.result["cancel_ack_seen"] = True
            self.result["cancel_ack_after_ms"] = int((time.monotonic() - self.cancel_at) * 1000)
            self.result["running_after_ack"] = self.proc.state() == QProcess.Running
        elif kind == "canceled" and self.seq == 5 and self.case == "late_canceled":
            if payload["request_id"] != str(REQUEST):
                raise ValueError("request")
            self.ledger, admitted = self.ledger.terminal(REQUEST, WORKER, "canceled", self.ms())
            if admitted is None:
                self.result["stale_terminals"] += 1
            # A stale terminal cannot release the physical slot or stop escalation.
        else:
            raise ValueError("unexpected message")

    def fail(self, outcome: str) -> None:
        if self.result["outcome"] is None:
            self.result["outcome"] = outcome
        if self.result["job_assigned"] and self.proc.state() == QProcess.Running:
            self.job.terminate_owned_tree()
        elif self.proc.state() == QProcess.Running:
            # Assignment failed before init. Kill only this known QProcess child.
            self.proc.kill()
        elif self.proc.state() == QProcess.NotRunning:
            self.app.quit()

    def tick(self) -> None:
        if self.result["outcome"] is not None:
            return
        if self.case == "startup_timeout" and self.ms() >= 300 and self.seq == 0:
            self.fail("STARTUP_TIMEOUT")
            return
        if self.cancel_at is not None:
            self.ledger, effects = self.ledger.tick(self.ms())
            for effect in effects:
                if effect.kind == "terminate_tree":
                    self.result["termination_requested_after_ms"] = int(
                        (time.monotonic() - self.cancel_at) * 1000)
                    self.fail("CANCELED")

    def finished(self, _code: int, _status: QProcess.ExitStatus) -> None:
        self.read_stderr()
        self.ledger = self.ledger.tree_exit(WORKER, self.ms())
        if self.result["outcome"] is None:
            self.result["outcome"] = "EARLY_EXIT"
        self.app.quit()

    def run(self) -> tuple[dict, int]:
        executable = ROOT.parent / "qt-dev-venv/Scripts/python.exe"
        program = str(executable if self.case != "startup_failure" else ROOT / "nonexistent-synthetic-worker.exe")
        self.proc.setProgram(program)
        worker_case = "startup_timeout" if self.case == "containment_failure" else self.case
        self.proc.setArguments([str(ROOT / "tools/fixtures/qprocess_worker.py"), worker_case])
        self.proc.setWorkingDirectory(str(ROOT))
        env = QProcessEnvironment()
        source = QProcessEnvironment.systemEnvironment()
        for key in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
            if source.contains(key):
                env.insert(key, source.value(key))
        env.insert("PATH", f"{executable.parent};{source.value('SystemRoot')}\\System32")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        self.proc.setProcessEnvironment(env)
        self.proc.start()
        self.app.exec()
        self.timer.stop()
        self.watchdog.stop()
        self.job.close()  # Kill-on-close is the final owned-tree backstop.
        if self.parent_handle:
            self.result["parent_reclaimed"] = self.api.WaitForSingleObject(self.parent_handle, 2000) == WAIT_OBJECT_0
            self.api.CloseHandle(self.parent_handle)
        if self.descendant_handle:
            self.result["descendant_reclaimed"] = self.api.WaitForSingleObject(self.descendant_handle, 2000) == WAIT_OBJECT_0
            self.api.CloseHandle(self.descendant_handle)
        expected = {"startup_failure": "STARTUP_FAILED", "containment_failure": "CONTAINMENT_FAILED",
                    "startup_timeout": "STARTUP_TIMEOUT",
                    "malformed": "PROTOCOL_INVALID", "wrong_sequence": "PROTOCOL_INVALID",
                    "cancel_hang": "CANCELED", "late_canceled": "CANCELED"}[self.case]
        good = self.result["outcome"] == expected
        if self.case != "startup_failure":
            good = good and self.result["parent_reclaimed"]
            if self.case != "containment_failure":
                good = good and all(self.result[k] for k in (
                    "job_assigned", "descendant_spawned", "descendant_in_job",
                    "descendant_reclaimed"))
        if self.case == "cancel_hang":
            good = good and self.result["cancel_ack_seen"] and self.result["running_after_ack"]
            good = good and self.result["cancel_ack_after_ms"] <= 250
            good = good and self.result["termination_requested_after_ms"] >= 1000
        if self.case == "late_canceled":
            good = good and self.result["stale_terminals"] == 1
            good = good and self.result["cancel_ack_after_ms"] <= 250
            good = good and self.result["termination_requested_after_ms"] >= 1000
        self.result["status"] = "PASSED" if good else "FAILED"
        return self.result, 0 if good else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=[
        "startup_failure", "containment_failure", "startup_timeout", "malformed", "wrong_sequence",
        "cancel_hang", "late_canceled"])
    args = parser.parse_args()
    result, status = Probe(args.case).run()
    print(json.dumps(result, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
