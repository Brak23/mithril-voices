"""The audition parent must not accept work after Stop or timeout."""
import subprocess
import sys
from uuid import uuid4

import pytest

from lvc.tts.kokoro_cpu import GenerationCanceled
from lvc.tts.kokoro_worker import wait_worker


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.killed = 0
        self.waited = 0

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed += 1
        self.exit_code = -1

    def wait(self):
        self.waited += 1
        return self.exit_code


def test_canceled_generation_kills_worker_before_result_admission():
    expected = uuid4()
    process = FakeProcess()
    with pytest.raises(GenerationCanceled):
        wait_worker(process, expected, lambda: uuid4(), now=lambda: 0.0,
                    pause=lambda _seconds: None, timeout_s=10)
    assert (process.killed, process.waited) == (1, 1)


def test_timeout_kills_and_reaps_worker():
    generation = uuid4()
    process = FakeProcess()
    with pytest.raises(TimeoutError):
        wait_worker(process, generation, lambda: generation, now=lambda: 11.0,
                    pause=lambda _seconds: None, timeout_s=10, started_at=0.0)
    assert (process.killed, process.waited) == (1, 1)


def test_exited_worker_reports_actual_status_without_kill():
    generation = uuid4()
    process = FakeProcess(7)
    assert wait_worker(process, generation, lambda: generation, now=lambda: 0.0,
                       pause=lambda _seconds: None, timeout_s=10) == 7
    assert process.killed == 0


def test_windows_child_is_reaped_after_generation_replacement():
    generation = uuid4()
    seen = 0

    def current():
        nonlocal seen
        seen += 1
        return generation if seen < 3 else uuid4()

    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        with pytest.raises(GenerationCanceled):
            wait_worker(process, generation, current, timeout_s=2)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
