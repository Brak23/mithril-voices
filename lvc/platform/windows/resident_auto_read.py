"""Owned warm Kokoro worker and generation-fenced automatic Qt audio child."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import cast
from uuid import uuid4

from lvc.core import RequestToken
from lvc.platform.windows.manual_read import (
    AUDIO_PYTHON,
    ROOT,
    TTS_PYTHON,
    OutputDevice,
)
from lvc.tts.resident_kokoro_worker import SPOOL_ROOT
from lvc.voice.cache import validate_complete_wav
from tools.windows_job_probe import OwnedJob, kernel32

MAX_LINE = 32_768
MAX_WAV = 16 * 1024 * 1024


class AutoVoiceError(RuntimeError):
    """Sanitized error code; child exceptions and text never enter status."""


def _receive(stream, events: queue.Queue[dict[str, object]]) -> None:
    while True:
        try:
            line = stream.readline(MAX_LINE + 1)
        except (OSError, ValueError):
            events.put({"event": "EOF"})
            return
        if not line:
            events.put({"event": "EOF"})
            return
        if len(line) > MAX_LINE:
            events.put({"event": "INVALID"})
            return
        try:
            value = json.loads(line)
        except (UnicodeError, ValueError):
            events.put({"event": "INVALID"})
            return
        if not isinstance(value, dict):
            events.put({"event": "INVALID"})
            return
        events.put(value)


def _send(process: subprocess.Popen[bytes], command: dict[str, object]) -> None:
    line = (json.dumps(command, ensure_ascii=False) + "\n").encode("utf-8")
    if len(line) > 16_384 or process.stdin is None:
        raise AutoVoiceError("VOICE_COMMAND_INVALID")
    process.stdin.write(line)
    process.stdin.flush()


def _owned_process(command: list[str], *, temp: Path) -> tuple[subprocess.Popen[bytes], OwnedJob]:
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "HF_HUB_DISABLE_TELEMETRY": "1", "TMP": str(temp), "TEMP": str(temp)}
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    job: OwnedJob | None = None
    try:
        job = OwnedJob(kernel32())
        handle = getattr(process, "_handle", None)
        if handle is None:
            raise AutoVoiceError("CHILD_HANDLE_UNAVAILABLE")
        job.assign_owned_handle(process.pid, handle)
        return process, job
    except Exception:
        process.kill()
        process.wait(timeout=3)
        if job is not None:
            job.close()
        raise


def _terminate(process: subprocess.Popen[bytes] | None, job: OwnedJob | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            if job is not None and job.assigned_pid is not None and job.handle:
                job.terminate_owned_tree()
            else:
                process.kill()
            process.wait(timeout=3)
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.stdout is not None and not process.stdout.closed:
            process.stdout.close()
        if job is not None:
            job.close()


class ResidentAutoReader:
    """One warm voice and one current request, with no page queue."""

    def __init__(self) -> None:
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: subprocess.Popen[bytes] | None = None
        self._worker_job: OwnedJob | None = None
        self._audio: subprocess.Popen[bytes] | None = None
        self._audio_job: OwnedJob | None = None
        self._spool: Path | None = None
        self._replies: queue.Queue[dict[str, object]] = queue.Queue()
        self._load_thread: threading.Thread | None = None
        self._request_thread: threading.Thread | None = None
        self._voice: str | None = None
        self._generation = 0
        self._cancel = threading.Event()
        self.ready = False
        self.preparing = False
        self.busy = False
        self.closed = False

    @property
    def voice(self) -> str | None:
        return self._voice

    def prepare(self, voice: str) -> bool:
        if voice not in {"bf_emma", "bm_fable"} or not TTS_PYTHON.is_file():
            self.events.put(("ERROR", "VOICE_RUNTIME_UNAVAILABLE"))
            return False
        with self._lock:
            if self.closed or self.busy or self.preparing:
                return False
            if self.ready and self._voice == voice:
                return True
            if self._worker is not None:
                return False  # Change voice after reopening this bounded session.
            self._voice = voice
            self.preparing = True
        self._load_thread = threading.Thread(target=self._load, args=(voice,), daemon=True)
        self._load_thread.start()
        return True

    def _load(self, voice: str) -> None:
        spool: Path | None = None
        try:
            SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
            spool = SPOOL_ROOT / str(uuid4())
            spool.mkdir(exist_ok=False)
            nonce = str(uuid4())
            worker, job = _owned_process([
                str(TTS_PYTHON), "-u", "-m", "lvc.tts.resident_kokoro_worker",
                "--voice", voice, "--spool", str(spool), "--nonce", nonce], temp=spool)
            with self._lock:
                self._worker, self._worker_job, self._spool = worker, job, spool
            assert worker.stdout is not None
            threading.Thread(target=_receive, args=(worker.stdout, self._replies),
                             daemon=True).start()
            reply = self._replies.get(timeout=45)
            if reply != {"event": "READY", "nonce": nonce, "voice": voice}:
                raise AutoVoiceError("VOICE_READY_INVALID")
            with self._lock:
                if self.closed:
                    raise AutoVoiceError("VOICE_CLOSED")
                self.ready = True
                self.preparing = False
            self.events.put(("VOICE_READY", ""))
        except Exception:  # noqa: BLE001 - never expose child/model details
            with self._lock:
                self.ready = False
                self.preparing = False
                worker, job = self._worker, self._worker_job
                self._worker = self._worker_job = self._spool = None
            _terminate(worker, job)
            if spool is not None:
                self._remove_spool(spool)
            if not self.closed:
                self.events.put(("ERROR", "VOICE_PREPARE_FAILED"))

    def _current(self, generation: int) -> bool:
        with self._lock:
            return not self.closed and generation == self._generation and not self._cancel.is_set()

    def read_auto(self, text: str, token: RequestToken, voice: str,
                  device: OutputDevice, *, silent: bool = False) -> bool:
        if (token.origin != "auto" or token.page is None or not text.strip()
                or len(text) > 3_000 or not device.id or not device.description
                or not AUDIO_PYTHON.is_file()):
            self.events.put(("ERROR", "AUTO_SPEECH_INVALID"))
            return False
        with self._lock:
            if (self.closed or self.busy or not self.ready or self._voice != voice
                    or self._worker is None or self._spool is None):
                return False
            self.busy = True
            self._generation += 1
            generation = self._generation
            self._cancel = threading.Event()
        self._request_thread = threading.Thread(
            target=self._run, args=(generation, text, token, device, silent), daemon=True)
        self._request_thread.start()
        return True

    def _reply(self, timeout: float) -> dict[str, object]:
        try:
            result = self._replies.get(timeout=timeout)
        except queue.Empty as exc:
            raise AutoVoiceError("VOICE_TIMEOUT") from exc
        if result.get("event") in {"EOF", "INVALID", "ERROR"}:
            raise AutoVoiceError("VOICE_REPLY_INVALID")
        return result

    def _run(self, generation: int, text: str, token: RequestToken,
             device: OutputDevice, silent: bool) -> None:
        worker = self._worker
        spool = self._spool
        assert worker is not None and spool is not None
        request = str(token.request_id)
        directory = spool / request
        rows: list[dict[str, object]] = []
        try:
            self.events.put(("SYNTHESIZING", ""))
            _send(worker, {"action": "render", "request_id": request,
                           "generation": generation, "voice": self._voice, "text": text})
            expected_total: int | None = None
            while True:
                reply = self._reply(45)
                event = reply.get("event")
                if event in {"DONE", "CANCELED"}:
                    if (reply != {"event": event, "request_id": request,
                                  "generation": generation,
                                  **({"total": expected_total} if event == "DONE" else {})}):
                        raise AutoVoiceError("VOICE_REPLY_INVALID")
                    if event == "CANCELED" or not self._current(generation):
                        return
                    break
                index = len(rows)
                total = reply.get("total")
                reply_index = reply.get("index")
                if (event != "UNIT_READY" or reply.get("request_id") != request
                        or reply.get("generation") != generation
                        or type(reply_index) is not int or reply_index != index
                        or type(total) is not int or not 1 <= total <= 32
                        or (expected_total is not None and total != expected_total)
                        or set(reply) != {"event", "request_id", "generation", "index",
                                          "total", "path", "sha256", "frames"}):
                    raise AutoVoiceError("VOICE_REPLY_INVALID")
                assert isinstance(total, int)
                expected_total = total
                path = directory / f"{index:02d}.wav"
                if reply["path"] != str(path) or not path.is_file() or path.stat().st_size > MAX_WAV:
                    raise AutoVoiceError("VOICE_ARTIFACT_INVALID")
                data = path.read_bytes()
                if (reply["sha256"] != hashlib.sha256(data).hexdigest()
                        or type(reply["frames"]) is not int
                        or reply["frames"] != validate_complete_wav(data)):
                    raise AutoVoiceError("VOICE_ARTIFACT_INVALID")
                rows.append({"path": str(path), "sha256": reply["sha256"],
                             "frames": reply["frames"]})
                if index + 1 < expected_total:
                    action = ("next" if self._current(generation) else "cancel")
                    command: dict[str, object] = {"action": action,
                                                  "request_id": request,
                                                  "generation": generation}
                    if action == "next":
                        command["after_index"] = index
                    _send(worker, command)
            if not self._current(generation):
                return
            if expected_total is None or len(rows) != expected_total:
                raise AutoVoiceError("VOICE_RESULT_INCOMPLETE")
            self.events.put(("PREPARING_AUDIO", ""))
            self._play(rows, text, token, device, generation, silent, spool)
            if self._current(generation):
                self.events.put(("COMPLETED", ""))
        except Exception:  # noqa: BLE001 - no child text or private path in event
            if self._current(generation):
                self.events.put(("ERROR", "AUTO_SPEECH_FAILED"))
        finally:
            self._remove_spool(directory)
            with self._lock:
                self.busy = False
            if not self._current(generation):
                self.events.put(("STOPPED", ""))

    def _play(self, rows: list[dict[str, object]], text: str, token: RequestToken,
              device: OutputDevice, generation: int, silent: bool, temp: Path) -> None:
        payload = {"session_id": str(token.session_id), "request_id": str(token.request_id),
                   "generation": generation,
                   "page_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   "source": "worker", "device_id": device.id,
                   "device_description": device.description, "units": rows}
        command = [str(AUDIO_PYTHON), "-u", "-m", "lvc.platform.windows.manual_audio_child"]
        if silent:
            command.append("--silent")
        audio, job = _owned_process(command, temp=temp)
        with self._lock:
            self._audio, self._audio_job = audio, job
        replies: queue.Queue[dict[str, object]] = queue.Queue()
        assert audio.stdout is not None
        threading.Thread(target=_receive, args=(audio.stdout, replies), daemon=True).start()
        try:
            _send(audio, payload)
            deadline = time.monotonic() + sum(cast(int, row["frames"]) for row in rows) / 48_000 + 30
            stopping_at: float | None = None
            completed = False
            while time.monotonic() < deadline:
                if not self._current(generation) and stopping_at is None:
                    stopping_at = time.monotonic()
                    if audio.stdin is not None and audio.poll() is None:
                        audio.stdin.write(b"STOP\n")
                        audio.stdin.flush()
                if stopping_at is not None and time.monotonic() - stopping_at > 0.3:
                    return
                try:
                    reply = replies.get(timeout=0.05)
                except queue.Empty:
                    if audio.poll() is not None:
                        break
                    continue
                event = reply.get("event")
                if event in {"READY", "UNIT_STARTED", "UNIT_DONE"}:
                    self.events.put((str(event), ""))
                elif event == "COMPLETED":
                    completed = True
                    break
                elif event == "STOPPED" and not self._current(generation):
                    return
                else:
                    raise AutoVoiceError("AUDIO_REPLY_INVALID")
            if not completed or audio.wait(timeout=3) != 0:
                raise AutoVoiceError("AUDIO_INCOMPLETE")
        finally:
            _terminate(audio, job)
            with self._lock:
                if self._audio is audio:
                    self._audio = self._audio_job = None

    def stop(self, *, wait: bool = False) -> None:
        with self._lock:
            thread = self._request_thread
            if self.busy:
                self._generation += 1
                self._cancel.set()
                self.events.put(("STOPPING", ""))
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=4)
            if thread.is_alive():
                with self._lock:
                    worker, worker_job = self._worker, self._worker_job
                    self.ready = False
                _terminate(worker, worker_job)
                thread.join(timeout=2)
            if thread.is_alive():
                raise AutoVoiceError("AUTO_SHUTDOWN_INCOMPLETE")

    @staticmethod
    def _remove_spool(path: Path) -> None:
        try:
            resolved = path.resolve()
            root = SPOOL_ROOT.resolve()
            if (resolved == root or root not in resolved.parents
                    or path.is_symlink()):
                raise AutoVoiceError("SPOOL_OWNERSHIP_INVALID")
            if resolved.exists():
                shutil.rmtree(resolved)
        except OSError:
            pass

    def close(self) -> None:
        self.stop(wait=True)
        with self._lock:
            self.closed = True
            worker, job, spool = self._worker, self._worker_job, self._spool
            self._worker = self._worker_job = self._spool = None
            audio, audio_job = self._audio, self._audio_job
            self._audio = self._audio_job = None
        _terminate(audio, audio_job)
        _terminate(worker, job)
        if self._load_thread is not None:
            self._load_thread.join(timeout=3)
        if spool is not None:
            self._remove_spool(spool)
