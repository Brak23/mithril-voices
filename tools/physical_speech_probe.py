"""Play one private, attenuated local Windows voice sample through the guarded owner."""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lvc.qt_audio_owner import QtAudioService
from lvc.qt_physical_backend import QtSinkBackend
from tools.qt_audio_owner_probe import SESSION, validated_submission

SAMPLE_RATE = 48_000
PEAK_LIMIT = round(32767 * 10 ** (-36 / 20))
MAX_SOURCE_FRAMES = SAMPLE_RATE * 2
SOURCE = ROOT.parent / "test-tmp" / "speech-prep" / "generic-speech.wav"


def attenuated_pcm() -> tuple[bytes, int, int]:
    source = SOURCE.resolve()
    approved_root = (ROOT.parent / "test-tmp" / "speech-prep").resolve()
    if source.parent != approved_root or source.name != "generic-speech.wav":
        raise ValueError("Speech source must be the prepared local sample")
    with wave.open(str(source), "rb") as input_wave:
        frames = input_wave.getnframes()
        if (input_wave.getnchannels() != 1 or input_wave.getsampwidth() != 2
                or input_wave.getframerate() != SAMPLE_RATE
                or not 0 < frames <= MAX_SOURCE_FRAMES):
            raise ValueError("Speech sample is outside the approved PCM bounds")
        raw = input_wave.readframes(frames)
    if len(raw) != frames * 2:
        raise ValueError("Speech sample is truncated")
    samples = struct.unpack(f"<{frames}h", raw)
    original_peak = max(abs(value) for value in samples)
    if original_peak == 0:
        raise ValueError("Speech sample is silent")
    fade_frames = 960
    scale = PEAK_LIMIT / original_peak
    output = [round(value * scale * min(1.0, i / fade_frames,
                                         (frames - 1 - i) / fade_frames))
              for i, value in enumerate(samples)]
    peak = max(abs(value) for value in output)
    if peak > PEAK_LIMIT:
        raise ValueError("Speech level exceeded the digital peak cap")
    return struct.pack(f"<{frames}h", *output), frames, peak


class SpeechProbe(QObject):
    def __init__(self, device_id: str, expected_description: str):
        super().__init__()
        self.app = QCoreApplication.instance()
        self.backend: QtSinkBackend | None = None
        self.reason = "INCOMPLETE"
        self.written_frames = 0
        self.completed_units = 0
        self.rejections: list[str] = []
        self.device_losses = 0
        self.ending = False
        self.pcm, self.frames, self.peak = attenuated_pcm()
        base = ROOT.parent / "test-tmp"
        self.isolated = Path(tempfile.mkdtemp(prefix="mithril-speech-", dir=base))
        spool = self.isolated / str(SESSION)
        spool.mkdir()
        self.submission = validated_submission(spool, self.pcm)

        def factory(selected: str) -> QtSinkBackend:
            backend = QtSinkBackend(selected)
            if backend.device_description != expected_description:
                raise ValueError("Selected output description changed")
            self.backend = backend
            return backend

        self.service = QtAudioService(SESSION, device_id, factory, allow_physical=True)
        self.service.owner.fence_ack.connect(self.on_fence_ack)
        self.service.owner.write_observed.connect(self.on_write)
        self.service.owner.unit_drained.connect(self.on_completed)
        self.service.owner.rejected.connect(self.on_rejected)
        self.service.owner.device_lost.connect(self.on_device_lost)
        self.service.thread.finished.connect(self.app.quit)
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(lambda: self.stop("WATCHDOG"))
        self.watchdog.start(4000)
        self.service.fence(1)

    @Slot(int, int)
    def on_fence_ack(self, generation: int, _epoch: int) -> None:
        if generation == 1:
            self.service.admit(self.submission)
        elif generation == 2:
            self.service.close()

    @Slot(str, int, int)
    def on_write(self, _request_id: str, frames: int, _epoch: int) -> None:
        self.written_frames += frames

    @Slot(str, str, int)
    def on_completed(self, _request_id: str, _unit_id: str, _epoch: int) -> None:
        self.completed_units += 1
        self.stop("RENDERER_DRAINED")

    @Slot(str)
    def on_rejected(self, code: str) -> None:
        self.rejections.append(code)
        self.stop("REJECTED")

    @Slot(int)
    def on_device_lost(self, _generation: int) -> None:
        self.device_losses += 1
        self.stop("DEVICE_LOST")

    def stop(self, reason: str) -> None:
        if self.ending:
            return
        self.ending = True
        self.reason = reason
        self.watchdog.stop()
        self.service.fence(2)

    def report(self) -> tuple[dict[str, object], int]:
        self.app.exec()
        if not self.service.thread.wait(1500):
            raise RuntimeError("Qt audio owner did not stop")
        safe_base = (ROOT.parent / "test-tmp").resolve()
        isolated = self.isolated.resolve()
        if not isolated.is_relative_to(safe_base) or not isolated.name.startswith("mithril-speech-"):
            raise RuntimeError("Refusing cleanup outside owned test directory")
        shutil.rmtree(isolated)
        backend = self.backend
        report: dict[str, object] = {
            "scope": "ONE_BOUNDED_LOCAL_WINDOWS_VOICE_SAMPLE_ON_REALTEK",
            "status": "FAILED",
            "reason": self.reason,
            "source_kind": "BUILT_IN_WINDOWS_SYSTEM_SPEECH_LOCAL_PRIVATE_TEST",
            "source_text": "The road is clear.",
            "source_frames": self.frames,
            "digital_peak_dbfs": 20 * math.log10(self.peak / 32767),
            "written_frames": self.written_frames,
            "renderer_completed_units": self.completed_units,
            "rejections": self.rejections,
            "device_losses": self.device_losses,
            "backend": backend.report() if backend else None,
            "acoustic_output_measured": False,
            "game_capture_or_model_tested": False,
        }
        ok = (backend is not None and self.reason == "RENDERER_DRAINED"
              and self.written_frames == self.frames
              and backend.accepted_bytes == self.frames * 2
              and self.completed_units == 1 and not self.rejections
              and self.device_losses == 0 and backend.reset_count >= 2)
        report["status"] = "PASSED" if ok else "FAILED"
        return report, 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--expected-description", required=True)
    parser.add_argument("--execute-speech-check", action="store_true", required=True)
    args = parser.parse_args()
    app = QCoreApplication([])
    report, code = SpeechProbe(args.device_id, args.expected_description).report()
    print(json.dumps(report, sort_keys=True))
    _ = app
    return code


if __name__ == "__main__":
    raise SystemExit(main())
