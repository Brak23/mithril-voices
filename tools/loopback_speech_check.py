"""One bounded output-only loopback check of the local generic speech probe."""
# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from time import perf_counter_ns

import numpy as np
import soundcard as sc

ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = ROOT.parent
QT_PYTHON = TASK_ROOT / "qt-dev-venv" / "Scripts" / "python.exe"
DEVICE_ID = "{0.0.0.00000000}.{a1d419f2-e6af-4a0e-8c3e-e5395c018f6d}"
DEVICE_NAME = "Speakers (Realtek(R) Audio)"
SAMPLE_RATE = 48_000
BLOCK_FRAMES = 480
MAX_CAPTURE_NS = 5_000_000_000
POST_CHILD_NS = 250_000_000


def run_once() -> tuple[dict[str, object], int]:
    receipt_path = TASK_ROOT / "wp04-loopback-speech.json"
    marker_path = TASK_ROOT / "wp04-loopback-speech-attempt.txt"
    if receipt_path.exists() or marker_path.exists():
        raise RuntimeError("Speech check already attempted; refusing duplicate playback")
    if not QT_PYTHON.is_file():
        raise RuntimeError("Isolated Qt interpreter is missing")
    source = sc.get_microphone(DEVICE_ID, include_loopback=True)
    if (source.id != DEVICE_ID or source.name != DEVICE_NAME
            or not source.isloopback or source.channels < 2):
        raise RuntimeError("Exact Realtek stereo loopback source is unavailable")
    command = [str(QT_PYTHON), str(ROOT / "tools" / "physical_speech_probe.py"),
               "--device-id", DEVICE_ID, "--expected-description", DEVICE_NAME,
               "--execute-speech-check"]
    levels: list[float] = []
    child: subprocess.Popen[str] | None = None
    marker_path.write_text("One approved Realtek speech attempt started; no automatic retry.\n",
                           encoding="utf-8")
    try:
        with source.recorder(samplerate=SAMPLE_RATE, channels=[0, 1],
                             blocksize=BLOCK_FRAMES * 10) as recorder:
            for _ in range(10):
                block = recorder.record(numframes=BLOCK_FRAMES)
                levels.append(float(np.sqrt(np.mean(np.square(block)))))
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            launch_ns = perf_counter_ns()
            child_exit_ns: int | None = None
            while perf_counter_ns() - launch_ns < MAX_CAPTURE_NS:
                block = recorder.record(numframes=BLOCK_FRAMES)
                levels.append(float(np.sqrt(np.mean(np.square(block)))))
                if child.poll() is not None and child_exit_ns is None:
                    child_exit_ns = perf_counter_ns()
                if child_exit_ns is not None and perf_counter_ns() - child_exit_ns >= POST_CHILD_NS:
                    break
        if child.poll() is None:
            child.terminate()
        stdout, stderr = child.communicate(timeout=2)
        probe = json.loads(stdout) if stdout.strip().startswith("{") else None
        baseline_peak = max(levels[:10])
        peak = max(levels)
        threshold = max(0.0001, baseline_peak * 5, peak * 0.05)
        active = [i for i, level in enumerate(levels) if level >= threshold]
        quiet_tail = len(levels) - active[-1] - 1 if active else 0
        report: dict[str, object] = {
            "scope": "BOUNDED_REALTEK_STEREO_OUTPUT_LOOPBACK_GENERIC_SPEECH",
            "status": "INCONCLUSIVE",
            "capture_device_id": source.id,
            "capture_device_name": source.name,
            "capture_is_loopback": source.isloopback,
            "microphone_opened": False,
            "sample_rate": SAMPLE_RATE,
            "channels": 2,
            "block_frames": BLOCK_FRAMES,
            "capture_blocks": len(levels),
            "captured_frames": len(levels) * BLOCK_FRAMES,
            "raw_audio_saved": False,
            "baseline_rms_peak": baseline_peak,
            "capture_rms_peak": peak,
            "detection_threshold": threshold,
            "active_blocks": len(active),
            "quiet_blocks_after_last_activity": quiet_tail,
            "child_exit_code": child.returncode,
            "child_stderr": stderr[:500],
            "probe": probe,
            "physical_acoustic_output_measured": False,
        }
        passed = (child.returncode == 0 and probe is not None
                  and probe.get("status") == "PASSED"
                  and len(active) >= 20 and quiet_tail >= 5
                  and peak >= threshold and baseline_peak < threshold)
        report["status"] = "PASSED" if passed else "INCONCLUSIVE"
        receipt_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report, 0 if passed else 1
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-once", action="store_true", required=True)
    parser.parse_args()
    report, code = run_once()
    probe = report.get("probe")
    print(json.dumps({"status": report["status"],
                      "receipt": str(TASK_ROOT / "wp04-loopback-speech.json"),
                      "active_blocks": report["active_blocks"],
                      "child_status": probe.get("status") if isinstance(probe, dict) else None}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
