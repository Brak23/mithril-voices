"""One guarded Qt audio session for already rendered private WAV units.

The parent starts this child only after a user presses Read. `--silent` uses the
same owner and admission path with a fake backend and opens no output device.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot
from PySide6.QtMultimedia import QMediaDevices

from lvc.core import PageIdentity, RequestToken, State
from lvc.qt_audio_owner import AudioSubmission, QtAudioService
from lvc.qt_physical_backend import QtSinkBackend
from lvc.safeguards import AudioSource, WorkerLedger
from lvc.synthetic_flow import AcceptedUnit
from lvc.voice.cache import validate_complete_wav

ROOT = Path(__file__).resolve().parents[3]
PRIVATE_ROOT = ROOT / ".audition"
MAX_COMMAND_BYTES = 32_768
MAX_TOTAL_PCM_BYTES = 64 * 1024 * 1024
MAX_UNITS = 32


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def available_devices() -> list[dict[str, str]]:
    return [{"id": bytes(device.id()).decode("utf-8", "replace"),
             "description": device.description()}
            for device in QMediaDevices.audioOutputs()]


@dataclass(frozen=True)
class Prepared:
    state: State
    ledger: WorkerLedger
    token: RequestToken
    units: tuple[AcceptedUnit, ...]
    source: AudioSource
    device_id: str
    device_description: str


def prepare(command: dict[str, object]) -> Prepared:
    """Validate all local artifacts before constructing an audio backend."""
    if set(command) != {"session_id", "request_id", "generation", "page_digest",
                        "source", "device_id", "device_description", "units"}:
        raise ValueError("AUDIO_COMMAND_INVALID")
    session = UUID(str(command["session_id"]))
    request = UUID(str(command["request_id"]))
    generation = command["generation"]
    digest = command["page_digest"]
    source = command["source"]
    device_id = command["device_id"]
    description = command["device_description"]
    rows = command["units"]
    if (type(generation) is not int or generation < 1
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not isinstance(source, str) or source not in {"worker", "cache"}
            or not isinstance(device_id, str) or not device_id
            or not isinstance(description, str) or not description
            or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_UNITS):
        raise ValueError("AUDIO_COMMAND_INVALID")
    permitted = ((PRIVATE_ROOT / "tmp" / "manual-read").resolve(),
                 (PRIVATE_ROOT / "manual-cache").resolve())
    units: list[AcceptedUnit] = []
    total_bytes = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "frames"}:
            raise ValueError("AUDIO_UNIT_INVALID")
        filename, expected_hash, expected_frames = (row[key] for key in
                                                    ("path", "sha256", "frames"))
        if (not isinstance(filename, str) or not isinstance(expected_hash, str)
                or len(expected_hash) != 64 or type(expected_frames) is not int
                or expected_frames < 1):
            raise ValueError("AUDIO_UNIT_INVALID")
        path = Path(filename)
        resolved = path.resolve(strict=True)
        if (not path.is_absolute() or not any(resolved.is_relative_to(root)
                                             for root in permitted)
                or resolved.suffix.lower() != ".wav"
                or resolved.stat().st_size > 16 * 1024 * 1024):
            raise ValueError("AUDIO_UNIT_PATH_INVALID")
        wav = resolved.read_bytes()
        if hashlib.sha256(wav).hexdigest() != expected_hash:
            raise ValueError("AUDIO_UNIT_HASH_INVALID")
        frames = validate_complete_wav(wav)
        if frames != expected_frames:
            raise ValueError("AUDIO_UNIT_FRAMES_INVALID")
        with wave.open(io.BytesIO(wav), "rb") as reader:
            pcm = reader.readframes(frames)
        total_bytes += len(pcm)
        if total_bytes > MAX_TOTAL_PCM_BYTES:
            raise ValueError("AUDIO_SESSION_TOO_LARGE")
        units.append(AcceptedUnit(expected_hash, f"unit-{index}", frames, pcm))
    page = PageIdentity(session, 1, "manual_reviewed_body", digest)
    token = RequestToken(request, session, generation, generation, "manual", page)
    state = State(session_id=session, bound=True, intent=generation,
                  generation=generation, page=page, prepared=digest,
                  prepared_token=token, playback="PREPARING")
    ledger = WorkerLedger(session)
    if source == "worker":
        worker = UUID(int=1)
        ledger = ledger.submit(token, worker, 0)
        ledger, _ = ledger.terminal(request, worker, "completed", 1)
    return Prepared(state, ledger, token, tuple(units), cast(AudioSource, source),
                    device_id, description)


class SilentBackend:
    synthetic = True

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.pending = 0

    def write(self, pcm: bytes) -> int:
        self.pending += len(pcm)
        return len(pcm)

    def poll_drain(self) -> tuple[int, bool]:
        frames = self.pending // 2
        self.pending = 0
        return frames, True

    def reset(self) -> None:
        self.pending = 0


class AudioSession(QObject):
    def __init__(self, prepared: Prepared, *, silent: bool):
        super().__init__()
        self.app = QCoreApplication.instance()
        self.prepared = prepared
        self.index = 0
        self.ending = False
        self.outcome = "INCOMPLETE"
        self.stop_requested = threading.Event()
        self.last_progress = time.monotonic()

        def backend(device_id: str):
            if silent:
                return SilentBackend(device_id)
            physical = QtSinkBackend(device_id)
            if physical.device_description != prepared.device_description:
                raise ValueError("Selected device description changed")
            return physical

        self.service = QtAudioService(prepared.token.session_id,
                                      prepared.device_id, backend,
                                      allow_physical=not silent)
        self.service.owner.fence_ack.connect(self.on_fence)
        self.service.owner.unit_drained.connect(self.on_drained)
        self.service.owner.write_observed.connect(self.on_write)
        self.service.owner.rejected.connect(self.on_rejected)
        self.service.owner.device_lost.connect(self.on_device_lost)
        self.service.thread.finished.connect(self.app.quit)
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        threading.Thread(target=self.watch_stdin, daemon=True).start()
        self.service.fence(prepared.token.generation)

    def watch_stdin(self) -> None:
        pending = b""
        while True:
            chunk = os.read(sys.stdin.fileno(), 32)
            if not chunk:
                return
            pending = (pending + chunk)[-64:]
            if b"STOP\n" in pending:
                self.stop_requested.set()
                return

    def _admit_next(self) -> None:
        if self.ending or self.stop_requested.is_set():
            return
        unit = self.prepared.units[self.index]
        submission = AudioSubmission(self.prepared.state, self.prepared.ledger,
                                     self.prepared.token, unit,
                                     source=self.prepared.source, unit_index=self.index)
        self.service.admit(submission)
        emit("UNIT_STARTED", index=self.index + 1, total=len(self.prepared.units))

    @Slot(int, int)
    def on_fence(self, generation: int, _epoch: int) -> None:
        if generation == self.prepared.token.generation and not self.ending:
            emit("READY", total=len(self.prepared.units))
            self._admit_next()
        elif generation == self.prepared.token.generation + 1 and self.ending:
            self.service.close()

    @Slot(str, int, int)
    def on_write(self, _request: str, _frames: int, _epoch: int) -> None:
        self.last_progress = time.monotonic()

    @Slot(str, str, int)
    def on_drained(self, _request: str, _unit: str, _epoch: int) -> None:
        if self.ending:
            return
        emit("UNIT_DONE", index=self.index + 1, total=len(self.prepared.units))
        self.index += 1
        self.last_progress = time.monotonic()
        if self.index == len(self.prepared.units):
            self.stop("COMPLETED")
        else:
            self._admit_next()

    @Slot(str)
    def on_rejected(self, _code: str) -> None:
        self.stop("AUDIO_REJECTED")

    @Slot(int)
    def on_device_lost(self, _generation: int) -> None:
        self.stop("DEVICE_LOST")

    @Slot()
    def tick(self) -> None:
        if self.stop_requested.is_set():
            self.stop("STOPPED")
        elif not self.ending and time.monotonic() - self.last_progress > 15:
            self.stop("AUDIO_STALLED")

    def stop(self, reason: str) -> None:
        if self.ending:
            return
        self.ending = True
        self.outcome = reason
        self.timer.stop()
        self.service.fence(self.prepared.token.generation + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--silent", action="store_true")
    args = parser.parse_args()
    app = QCoreApplication([])
    if args.list_devices:
        print(json.dumps({"devices": available_devices()}, sort_keys=True))
        return 0
    line = sys.stdin.buffer.readline(MAX_COMMAND_BYTES + 1)
    if len(line) > MAX_COMMAND_BYTES:
        emit("ERROR", code="AUDIO_COMMAND_TOO_LARGE")
        return 2
    try:
        command = json.loads(line)
        if not isinstance(command, dict):
            raise TypeError("AUDIO_COMMAND_INVALID")
        prepared = prepare(command)
        if not args.silent and {"id": prepared.device_id,
                               "description": prepared.device_description} not in available_devices():
            raise ValueError("SELECTED_DEVICE_UNAVAILABLE")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        emit("ERROR", code=str(exc) if str(exc).isupper() else "AUDIO_PREP_INVALID")
        return 2
    session = AudioSession(prepared, silent=args.silent)
    app.exec()
    if not session.service.thread.wait(1500):
        emit("ERROR", code="AUDIO_OWNER_DID_NOT_STOP")
        return 3
    emit(session.outcome)
    return 0 if session.outcome in {"COMPLETED", "STOPPED"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
