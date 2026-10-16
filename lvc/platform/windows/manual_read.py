"""Manual, confirmed-text orchestration across the existing guarded components.

Tk never loads Kokoro or opens an audio device. Workers exchange only bounded
control JSON and private complete WAV paths. Private text stays out of logs/Git.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from lvc.tts.manual_providers import (
    LocalKokoroProvider,
    provider_for_voice,
    voice_options,
)
from lvc.vision.comparison import ReviewState
from lvc.voice.cache import (
    CompletedAudioCache,
    cache_key,
    validate_complete_wav,
)
from lvc.voice.text_plan import chunk_speech, load_lexicon, prepare_text
from tools.windows_job_probe import OwnedJob, kernel32

ROOT = Path(__file__).resolve().parents[3]
TASK_ROOT = ROOT.parent
TTS_PYTHON = ROOT / ".audition-venv" / "Scripts" / "python.exe"
AUDIO_PYTHON = TASK_ROOT / "qt-dev-venv" / "Scripts" / "python.exe"
PRIVATE_ROOT = ROOT / ".audition"
SPOOL_ROOT = PRIVATE_ROOT / "tmp" / "manual-read"
CACHE_ROOT = PRIVATE_ROOT / "manual-cache"
LEXICON = ROOT / "lvc" / "voice" / "lexicon.en.json"
MAX_TEXT_CHARS = 3_000
MAX_UNITS = 32
TTS_TIMEOUT_S = 180.0

PROVIDERS = (LocalKokoroProvider(TTS_PYTHON),)
VOICE_OPTIONS = voice_options(PROVIDERS)


class ManualReadError(RuntimeError):
    """A sanitized user-visible failure code, without source text or paths."""


class ReadCanceled(ManualReadError):
    pass


@dataclass(frozen=True)
class OutputDevice:
    id: str
    description: str


def list_output_devices() -> tuple[OutputDevice, ...]:
    if not AUDIO_PYTHON.is_file():
        raise ManualReadError("QT_AUDIO_RUNTIME_UNAVAILABLE")
    completed = subprocess.run(
        [str(AUDIO_PYTHON), "-m", "lvc.platform.windows.manual_audio_child",
         "--list-devices"], cwd=ROOT, capture_output=True, timeout=8, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode or len(completed.stdout) > 16_384:
        raise ManualReadError("AUDIO_DEVICE_LIST_FAILED")
    try:
        rows = json.loads(completed.stdout)["devices"]
        if not isinstance(rows, list) or len(rows) > 64:
            raise ValueError("Invalid devices")
        devices = tuple(OutputDevice(row["id"], row["description"]) for row in rows)
        if any(not device.id or not device.description for device in devices):
            raise ValueError("Invalid device")
        return devices
    except (TypeError, KeyError, ValueError, UnicodeError) as exc:
        raise ManualReadError("AUDIO_DEVICE_LIST_INVALID") from exc


def validated_rows(rows: object, directory: Path,
                   expected_count: int) -> list[dict[str, object]]:
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ManualReadError("TTS_RESULT_INCOMPLETE")
    result: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "frames"}:
            raise ManualReadError("TTS_RESULT_INVALID")
        expected = directory / f"{index:02d}.wav"
        if row["path"] != str(expected) or not expected.is_file():
            raise ManualReadError("TTS_RESULT_PATH_INVALID")
        data = expected.read_bytes()
        if (row["sha256"] != hashlib.sha256(data).hexdigest()
                or type(row["frames"]) is not int
                or row["frames"] != validate_complete_wav(data)):
            raise ManualReadError("TTS_RESULT_INVALID")
        result.append(row)
    return result


def _read_lines(process: subprocess.Popen[bytes],
                received: queue.Queue[dict[str, object]]) -> None:
    if process.stdout is None:
        return
    while True:
        line = process.stdout.readline(32_769)
        if not line:
            return
        if len(line) > 32_768:
            received.put({"event": "ERROR", "code": "CHILD_MESSAGE_TOO_LARGE"})
            return
        try:
            message = json.loads(line)
        except (UnicodeError, ValueError):
            received.put({"event": "ERROR", "code": "CHILD_MESSAGE_INVALID"})
            return
        if not isinstance(message, dict):
            received.put({"event": "ERROR", "code": "CHILD_MESSAGE_INVALID"})
            return
        received.put(message)


class ManualReadController:
    """One read at a time; Stop revokes its generation before child cleanup."""

    def __init__(self) -> None:
        self.session_id = uuid4()
        self.generation = 0
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_process: subprocess.Popen[bytes] | None = None
        self._active_job: OwnedJob | None = None
        self.busy = False
        self.closed = False

    def _current(self, generation: int) -> bool:
        with self._lock:
            return (not self.closed and self.generation == generation
                    and not self._cancel.is_set())

    def read(self, review: ReviewState, voice: str, device: OutputDevice,
             *, keep_local_cache: bool = False, silent: bool = False) -> bool:
        if (not review.confirmed or not review.can_confirm
                or len(review.draft) > MAX_TEXT_CHARS or not device.id
                or not device.description):
            self.events.put(("ERROR", "REVIEW_OR_DEVICE_NOT_READY"))
            return False
        try:
            provider_for_voice(voice, PROVIDERS)
        except LookupError:
            self.events.put(("ERROR", "VOICE_UNAVAILABLE"))
            return False
        with self._lock:
            if self.busy or self.closed:
                return False
            self.busy = True
            self.generation += 1
            generation = self.generation
            self._cancel = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(generation, review, voice, device,
                                    keep_local_cache, silent), daemon=True)
        self._thread.start()
        return True

    def stop(self, *, wait: bool = False) -> None:
        with self._lock:
            thread = self._thread
            if self.busy and not self._cancel.is_set():
                self.generation += 1
                self._cancel.set()
                self.events.put(("STOPPING", ""))
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=4)
            if thread.is_alive():
                with self._lock:
                    process, job = self._active_process, self._active_job
                if process is not None and process.poll() is None:
                    if job is not None and job.assigned_pid is not None:
                        job.terminate_owned_tree()
                    else:
                        process.kill()
                    process.wait(timeout=3)
                thread.join(timeout=3)
            if thread.is_alive():
                raise ManualReadError("READ_SHUTDOWN_INCOMPLETE")

    def close(self) -> None:
        self.stop(wait=True)
        with self._lock:
            self.closed = True

    def _run_child(self, command: list[str], payload: dict[str, object],
                   generation: int, timeout_s: float, *, audio: bool,
                   temp: Path) -> list[dict[str, object]]:
        env = os.environ.copy()
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1", "TMP": str(temp),
                    "TEMP": str(temp)})
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job: OwnedJob | None = None
        try:
            job = OwnedJob(kernel32())
            handle = getattr(process, "_handle", None)
            if handle is None:
                raise ManualReadError("CHILD_HANDLE_UNAVAILABLE")
            job.assign_owned_handle(process.pid, handle)
            with self._lock:
                self._active_process = process
                self._active_job = job
            if not self._current(generation):
                raise ReadCanceled("READ_CANCELED")
            assert process.stdin is not None
            data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            if len(data) > 32_768:
                raise ManualReadError("CHILD_COMMAND_TOO_LARGE")
            process.stdin.write(data)
            process.stdin.flush()
            if not audio:
                process.stdin.close()
            received: queue.Queue[dict[str, object]] = queue.Queue()
            reader = threading.Thread(target=_read_lines, args=(process, received), daemon=True)
            reader.start()
            messages: list[dict[str, object]] = []
            deadline = time.monotonic() + timeout_s
            while True:
                if not self._current(generation):
                    if audio and process.poll() is None and process.stdin is not None:
                        try:
                            process.stdin.write(b"STOP\n")
                            process.stdin.flush()
                            process.wait(timeout=1)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                    raise ReadCanceled("READ_CANCELED")
                if time.monotonic() >= deadline:
                    raise ManualReadError("AUDIO_TIMEOUT" if audio else "TTS_TIMEOUT")
                try:
                    message = received.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None and not reader.is_alive() and received.empty():
                        break
                    continue
                event = message.get("event")
                if event == "ERROR":
                    code = message.get("code")
                    raise ManualReadError(code if isinstance(code, str) and code.isupper()
                                          and len(code) < 80 else "CHILD_FAILED")
                if event in {"UNIT_RENDERED", "UNIT_STARTED", "UNIT_DONE", "READY"}:
                    index = message.get("index", 0)
                    total = message.get("total", 0)
                    self.events.put((str(event), f"{index}/{total}"))
                elif event in {"DONE", "COMPLETED", "STOPPED"}:
                    messages.append(message)
                elif event in {"AUDIO_REJECTED", "DEVICE_LOST", "AUDIO_STALLED",
                               "INCOMPLETE"}:
                    raise ManualReadError(str(event))
                else:
                    raise ManualReadError("CHILD_MESSAGE_INVALID")
            if process.wait(timeout=1) != 0:
                raise ManualReadError("AUDIO_FAILED" if audio else "TTS_FAILED")
            return messages
        finally:
            try:
                if process.poll() is None:
                    if job is not None and job.assigned_pid is not None:
                        job.terminate_owned_tree()
                    else:
                        process.kill()
                    process.wait(timeout=3)
            finally:
                with self._lock:
                    if self._active_process is process:
                        self._active_process = None
                        self._active_job = None
                if job is not None:
                    job.close()
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()

    def _run(self, generation: int, review: ReviewState, voice: str,
             device: OutputDevice, keep_cache: bool, silent: bool) -> None:
        spool: Path | None = None
        try:
            if not AUDIO_PYTHON.is_file():
                raise ManualReadError("QT_AUDIO_RUNTIME_UNAVAILABLE")
            lexicon = load_lexicon(LEXICON)
            provider = provider_for_voice(voice, PROVIDERS)
            source = review.windows_source or review.tesseract_source or ""
            plan = prepare_text(source, review.draft, lexicon,
                                locale="en-GB", engine="kokoro")
            chunks = chunk_speech(plan.speech_text, max_codepoints=180)
            if not 1 <= len(chunks) <= MAX_UNITS:
                raise ManualReadError("TEXT_TOO_LONG")
            SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
            spool = SPOOL_ROOT / str(uuid4())
            spool.mkdir(exist_ok=False)
            cache = CompletedAudioCache(CACHE_ROOT)
            identities = [provider.identity(unit, voice, plan.lexicon_version,
                                            plan.lexicon_sha256) for unit in chunks]
            rows: list[dict[str, object]] = []
            cache_hit = False
            if keep_cache:
                cached = [cache.get(identity, lambda: self._current(generation))
                          for identity in identities]
                if all(item is not None for item in cached):
                    cache_hit = True
                    for identity, data in zip(identities, cached, strict=True):
                        assert data is not None
                        key = cache_key(identity)
                        rows.append({"path": str(CACHE_ROOT / f"{key}.wav"),
                                     "sha256": hashlib.sha256(data).hexdigest(),
                                     "frames": validate_complete_wav(data)})
                    self.events.put(("CACHE_HIT", ""))
            if not cache_hit:
                self.events.put(("SYNTHESIZING", ""))
                command, payload = provider.render_command(spool, voice, plan.speech_text)
                if not command or not Path(command[0]).is_file():
                    raise ManualReadError("VOICE_RUNTIME_UNAVAILABLE")
                messages = self._run_child(command, payload, generation,
                                           TTS_TIMEOUT_S, audio=False, temp=spool)
                done = [item for item in messages if item.get("event") == "DONE"]
                if len(done) != 1:
                    raise ManualReadError("TTS_RESULT_INCOMPLETE")
                rows = validated_rows(done[0].get("units"), spool, len(chunks))
                if keep_cache:
                    for identity, row in zip(identities, rows, strict=True):
                        cache.put(identity, Path(str(row["path"])).read_bytes(),
                                  lambda: self._current(generation))
            if not self._current(generation):
                raise ReadCanceled("READ_CANCELED")
            self.events.put(("PREPARING_AUDIO", ""))
            request = uuid4()
            command = {"session_id": str(self.session_id), "request_id": str(request),
                       "generation": generation,
                       "page_digest": hashlib.sha256(review.draft.encode("utf-8")).hexdigest(),
                       "source": "cache" if cache_hit else "worker",
                       "device_id": device.id, "device_description": device.description,
                       "units": rows}
            audio_command = [str(AUDIO_PYTHON), "-u", "-m",
                             "lvc.platform.windows.manual_audio_child"]
            if silent:
                audio_command.append("--silent")
            if any(type(row["frames"]) is not int for row in rows):
                raise ManualReadError("AUDIO_FRAMES_INVALID")
            seconds = sum(cast(int, row["frames"]) for row in rows) / 48_000
            messages = self._run_child(audio_command, command, generation,
                                       seconds + 30, audio=True, temp=spool)
            if not self._current(generation):
                raise ReadCanceled("READ_CANCELED")
            if not any(item.get("event") == "COMPLETED" for item in messages):
                raise ManualReadError("AUDIO_INCOMPLETE")
            self.events.put(("COMPLETED", ""))
        except ReadCanceled:
            self.events.put(("STOPPED", ""))
        except Exception as exc:  # noqa: BLE001 - text and local paths must not enter UI/logs
            if not self._current(generation):
                self.events.put(("STOPPED", ""))
            else:
                code = str(exc) if isinstance(exc, ManualReadError) else "READ_FAILED"
                self.events.put(("ERROR", code))
        finally:
            try:
                if spool is not None and spool.exists():
                    resolved = spool.resolve()
                    if (resolved.parent == SPOOL_ROOT.resolve()
                            and resolved.name == spool.name):
                        shutil.rmtree(resolved)
            except OSError:
                self.events.put(("ERROR", "PRIVATE_SPOOL_CLEANUP_FAILED"))
            finally:
                with self._lock:
                    self.busy = False
