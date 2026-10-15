"""Explicit-device QAudioSink backend for a guarded local speaker probe.

Create and call this object only on the Qt audio owner's thread. It never
chooses the system default or changes master endpoint volume.
"""
# pyright: reportMissingImports=false
from __future__ import annotations

from time import perf_counter_ns

from PySide6.QtCore import QIODevice, QThread
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

SAMPLE_RATE = 48_000
FRAME_BYTES = 2
REQUESTED_BUFFER_BYTES = SAMPLE_RATE * FRAME_BYTES * 50 // 1000


class QtSinkBackend:
    synthetic = False

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.creator_thread = QThread.currentThread()
        matches = [device for device in QMediaDevices.audioOutputs()
                   if bytes(device.id()).decode("utf-8", "replace") == device_id]
        if len(matches) != 1:
            raise ValueError("Selected output device is absent or ambiguous")
        device = matches[0]
        self.device_description = device.description()
        self.was_default_at_selection = device.isDefault()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(SAMPLE_RATE)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            raise ValueError("Selected output device does not support 48 kHz mono Int16")
        self.sink = QAudioSink(device, audio_format)
        self.sink.setBufferSize(REQUESTED_BUFFER_BYTES)
        self.io: QIODevice | None = None
        self.actual_buffer_bytes: int | None = None
        self.actual_sample_rate: int | None = None
        self.actual_channel_count: int | None = None
        self.actual_sample_format: str | None = None
        self.first_write_ns: int | None = None
        self.last_write_ns: int | None = None
        self.last_reset_ns: int | None = None
        self.accepted_bytes = 0
        self.reported_drained_bytes = 0
        self.reset_count = 0
        self.error_names: list[str] = []

    def _on_owner_thread(self) -> None:
        if QThread.currentThread() != self.creator_thread:
            raise RuntimeError("QAudioSink accessed outside its owner thread")

    def write(self, pcm: bytes) -> int:
        self._on_owner_thread()
        if self.io is None:
            self.io = self.sink.start()
            if self.io is None:
                self.error_names.append(f"START_RETURNED_NO_DEVICE:{self.sink.error()}")
                raise RuntimeError("Selected QAudioSink returned no write device")
            if self.sink.error() != QtAudio.Error.NoError:
                self.error_names.append(str(self.sink.error()))
                raise RuntimeError("Selected QAudioSink reported a start error")
            actual_format = self.sink.format()
            self.actual_buffer_bytes = self.sink.bufferSize()
            self.actual_sample_rate = actual_format.sampleRate()
            self.actual_channel_count = actual_format.channelCount()
            self.actual_sample_format = str(actual_format.sampleFormat())
            if (self.actual_sample_rate != SAMPLE_RATE
                    or self.actual_channel_count != 1
                    or actual_format.sampleFormat() != QAudioFormat.SampleFormat.Int16):
                raise RuntimeError("QAudioSink format changed after validation")
        if self.sink.error() not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self.error_names.append(str(self.sink.error()))
            raise RuntimeError("Selected QAudioSink reported an error")
        free_bytes = self.sink.bytesFree() & ~1
        if free_bytes <= 0:
            return 0
        count = self.io.write(pcm[:free_bytes])
        if count > 0:
            now = perf_counter_ns()
            self.first_write_ns = self.first_write_ns or now
            self.last_write_ns = now
            self.accepted_bytes += count
        return count

    def reset(self) -> None:
        self._on_owner_thread()
        self.sink.reset()
        self.last_reset_ns = perf_counter_ns()
        self.reset_count += 1
        self.io = None
        self.reported_drained_bytes = self.accepted_bytes

    def poll_drain(self) -> tuple[int, bool]:
        self._on_owner_thread()
        if self.io is None:
            return 0, False
        error = self.sink.error()
        if error not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self.error_names.append(str(error))
            raise RuntimeError("Selected QAudioSink reported an error while draining")
        capacity = self.sink.bufferSize()
        free = self.sink.bytesFree()
        if capacity <= 0 or not 0 <= free <= capacity:
            raise RuntimeError("Selected QAudioSink reported invalid buffer accounting")
        queued = capacity - free
        consumed = max(self.reported_drained_bytes, self.accepted_bytes - queued)
        delta = consumed - self.reported_drained_bytes
        if delta % FRAME_BYTES:
            raise RuntimeError("Selected QAudioSink reported a partial frame")
        self.reported_drained_bytes = consumed
        return delta // FRAME_BYTES, self.sink.state() == QtAudio.State.IdleState

    def report(self) -> dict[str, object]:
        """Read after the owner thread has stopped."""
        return {
            "selected_device_id": self.device_id,
            "device_description": self.device_description,
            "was_default_at_selection": self.was_default_at_selection,
            "requested_buffer_bytes": REQUESTED_BUFFER_BYTES,
            "actual_buffer_bytes": self.actual_buffer_bytes,
            "actual_sample_rate": self.actual_sample_rate,
            "actual_channel_count": self.actual_channel_count,
            "actual_sample_format": self.actual_sample_format,
            "accepted_bytes": self.accepted_bytes,
            "reset_count": self.reset_count,
            "errors": self.error_names,
            "first_to_last_backend_write_ms":
                ((self.last_write_ns - self.first_write_ns) / 1e6
                 if self.first_write_ns and self.last_write_ns else None),
        }
