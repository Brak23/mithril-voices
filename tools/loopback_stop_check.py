"""Capture one bounded Realtek output-only loopback Stop check in memory."""
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
MAX_CAPTURE_NS = 2_500_000_000
POST_CHILD_NS = 250_000_000


def tone_amplitude(block: np.ndarray) -> float:
    """Return the strongest channel's 440 Hz projection for one short block."""
    if len(block) == 0:
        return 0.0
    phase = np.exp(-2j * np.pi * 440 * np.arange(len(block)) / SAMPLE_RATE)
    projected = np.abs(2 * np.einsum("fc,f->c", block, phase) / len(block))
    return float(np.max(projected))


def run_once() -> tuple[dict[str, object], int]:
    receipt_path = TASK_ROOT / "wp04-loopback-stop.json"
    marker_path = TASK_ROOT / "wp04-loopback-stop-attempt.txt"
    if receipt_path.exists() or marker_path.exists():
        raise RuntimeError("Stop check already attempted; refusing a duplicate tone")
    if not QT_PYTHON.is_file():
        raise RuntimeError("Isolated Qt interpreter is missing")
    source = sc.get_microphone(DEVICE_ID, include_loopback=True)
    if (source.id != DEVICE_ID or source.name != DEVICE_NAME
            or not source.isloopback or source.channels < 2):
        raise RuntimeError("Exact Realtek stereo loopback source is unavailable")
    command = [str(QT_PYTHON), str(ROOT / "tools" / "physical_stop_probe.py"),
               "--device-id", DEVICE_ID, "--expected-description", DEVICE_NAME,
               "--execute-stop-check"]
    blocks: list[tuple[int, int, np.ndarray]] = []
    child: subprocess.Popen[str] | None = None
    marker_path.write_text("One approved Realtek loopback Stop attempt started; no automatic retry.\n",
                           encoding="utf-8")
    try:
        with source.recorder(samplerate=SAMPLE_RATE, channels=[0, 1],
                             blocksize=BLOCK_FRAMES * 10) as recorder:
            for _ in range(10):
                before = perf_counter_ns()
                data = recorder.record(numframes=BLOCK_FRAMES)
                blocks.append((before, perf_counter_ns(), data.copy()))
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            launch_ns = perf_counter_ns()
            child_exit_ns: int | None = None
            while perf_counter_ns() - launch_ns < MAX_CAPTURE_NS:
                before = perf_counter_ns()
                data = recorder.record(numframes=BLOCK_FRAMES)
                blocks.append((before, perf_counter_ns(), data.copy()))
                if child.poll() is not None and child_exit_ns is None:
                    child_exit_ns = perf_counter_ns()
                if child_exit_ns is not None and perf_counter_ns() - child_exit_ns >= POST_CHILD_NS:
                    break
        if child.poll() is None:
            child.terminate()
        stdout, stderr = child.communicate(timeout=2)
        probe = json.loads(stdout) if stdout.strip().startswith("{") else None
        baseline = np.array([tone_amplitude(data) for _, _, data in blocks[:10]])
        amplitudes = np.array([tone_amplitude(data) for _, _, data in blocks])
        peak = float(np.max(amplitudes))
        threshold = max(0.0001, float(np.max(baseline)) * 5, peak * 0.05)
        active = [i for i, amplitude in enumerate(amplitudes)
                  if amplitude >= threshold]
        stop_ns = probe.get("stop_request_perf_ns") if probe else None
        first_write_ns = probe.get("first_backend_write_perf_ns") if probe else None
        last_active_ns = blocks[active[-1]][1] if active else None
        first_active_ns = blocks[active[0]][1] if active else None
        observed_tail_ms = ((last_active_ns - stop_ns) / 1e6
                            if last_active_ns and isinstance(stop_ns, int) else None)
        report: dict[str, object] = {
            "scope": "BOUNDED_REALTEK_STEREO_OUTPUT_LOOPBACK_STOP",
            "status": "INCONCLUSIVE",
            "capture_device_id": source.id,
            "capture_device_name": source.name,
            "capture_is_loopback": source.isloopback,
            "microphone_opened": False,
            "sample_rate": SAMPLE_RATE,
            "channels": 2,
            "block_frames": BLOCK_FRAMES,
            "captured_frames": sum(len(data) for _, _, data in blocks),
            "raw_audio_saved": False,
            "capture_blocks": len(blocks),
            "baseline_440hz_peak": float(np.max(baseline)),
            "capture_440hz_peak": peak,
            "detection_threshold": threshold,
            "active_blocks": len(active),
            "first_active_return_perf_ns": first_active_ns,
            "last_active_return_perf_ns": last_active_ns,
            "observed_last_tone_block_after_stop_ms": observed_tail_ms,
            "first_tone_block_after_backend_write_ms":
                ((first_active_ns - first_write_ns) / 1e6
                 if first_active_ns and isinstance(first_write_ns, int) else None),
            "quiet_blocks_after_last_tone": len(blocks) - active[-1] - 1 if active else None,
            "capture_timestamp_uncertainty_ms_at_least":
                BLOCK_FRAMES / SAMPLE_RATE * 1000,
            "additional_wasapi_buffering_uncertainty": "UNMEASURED",
            "physical_acoustic_silence_measured": False,
            "child_exit_code": child.returncode,
            "child_stderr": stderr[:500],
            "probe": probe,
        }
        signal_detected = (len(active) >= 3 and peak >= threshold
                           and first_active_ns is not None and last_active_ns is not None)
        quiet_tail = (len(blocks) - active[-1] - 1 >= 5) if active else False
        passed = (child.returncode == 0 and probe is not None
                  and probe.get("status") == "PASSED" and signal_detected
                  and quiet_tail and isinstance(stop_ns, int)
                  and observed_tail_ms is not None)
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
                      "receipt": str(TASK_ROOT / "wp04-loopback-stop.json"),
                      "observed_tail_ms": report["observed_last_tone_block_after_stop_ms"],
                      "child_status": probe.get("status") if isinstance(probe, dict) else None}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
