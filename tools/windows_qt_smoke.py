"""Bounded Windows Qt binary/process probe; never captures or plays content.

Checks a real QApplication event loop and asynchronous QProcess signal path.
Importing multimedia classes does not qualify capture or an audio endpoint.
"""
from __future__ import annotations

import json
import platform
import sys

from PySide6.QtCore import QProcess, QTimer, qVersion
from PySide6.QtMultimedia import QAudioSink, QWindowCapture  # noqa: F401
from PySide6.QtWidgets import QApplication


def main() -> int:
    if sys.platform != "win32":
        print(json.dumps({"status": "BLOCKED", "reason": "Windows runner required"}))
        return 2

    app = QApplication([])
    child = QProcess(app)
    child.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
    timer = QTimer(app)
    timer.setSingleShot(True)
    observed = {"started": False, "timed_out": False, "exit_code": None,
                "exit_status": None, "error": None, "stdout": bytearray(), "stderr": bytearray()}

    def drain() -> None:
        observed["stdout"].extend(child.readAllStandardOutput().data())
        observed["stderr"].extend(child.readAllStandardError().data())

    def finished(code: int, status: QProcess.ExitStatus) -> None:
        drain()
        observed["exit_code"] = code
        observed["exit_status"] = status.name
        timer.stop()
        app.quit()

    def failed(error: QProcess.ProcessError) -> None:
        observed["error"] = error.name
        if error == QProcess.ProcessError.FailedToStart:
            timer.stop()
            app.quit()

    def timeout() -> None:
        observed["timed_out"] = True
        child.kill()
        # A failed-to-start child has no finished signal.
        QTimer.singleShot(100, app.quit)

    child.started.connect(lambda: observed.__setitem__("started", True))
    child.readyReadStandardOutput.connect(drain)
    child.readyReadStandardError.connect(drain)
    child.finished.connect(finished)
    child.errorOccurred.connect(failed)
    timer.timeout.connect(timeout)
    timer.start(5000)
    child.start(sys.executable, ["-c", "import sys; sys.stdout.buffer.write(b'READY\\n')"])
    app.exec()

    ok = (observed["started"] and not observed["timed_out"]
          and observed["exit_code"] == 0 and observed["exit_status"] == "NormalExit"
          and observed["error"] is None and observed["stdout"] == b"READY\n"
          and not observed["stderr"])
    report = {"status": "PASSED" if ok else "FAILED", "platform": platform.system(),
              "python": platform.python_version(), "architecture": platform.architecture()[0],
              "qt": qVersion(), "assertions": {
                  "widgets_event_loop": True,
                  "asynchronous_child_started": observed["started"],
                  "child_exited_normally": observed["exit_code"] == 0 and observed["exit_status"] == "NormalExit",
                  "stdout_exact": observed["stdout"] == b"READY\n",
                  "no_timeout_or_process_error": not observed["timed_out"] and observed["error"] is None,
              },
              "limits": "No window capture, audio playback, game process, model or process-tree containment tested"}
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
