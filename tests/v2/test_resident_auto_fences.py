"""Stop at resident worker/audio handoff boundaries without launching children."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from lvc.core import PageIdentity, RequestToken
from lvc.platform.windows import resident_auto_read as module
from lvc.platform.windows.manual_read import OutputDevice


def request() -> tuple[RequestToken, OutputDevice]:
    page = PageIdentity(uuid4(), 1, "quest_body", "a" * 64)
    return (RequestToken(uuid4(), uuid4(), 1, 1, "auto", page),
            OutputDevice("synthetic", "Synthetic"))


def test_stopped_before_worker_thread_runs_sends_no_render(monkeypatch, tmp_path: Path) -> None:
    reader = module.ResidentAutoReader()
    reader._worker = object()  # type: ignore[assignment]
    reader._spool = tmp_path
    reader._generation = 2
    reader._cancel.set()
    monkeypatch.setattr(reader, "_remove_spool", lambda _path: None)

    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("canceled request reached worker")

    monkeypatch.setattr(module, "_send", forbidden)
    token, device = request()
    reader._run(1, "A quest line", token, device, True)
    assert list(reader.events.queue) == [("STOPPED", "")]


def test_stopped_before_audio_handoff_spawns_no_child(monkeypatch, tmp_path: Path) -> None:
    reader = module.ResidentAutoReader()
    reader._generation = 2
    reader._cancel.set()

    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("canceled request launched audio")

    monkeypatch.setattr(module, "_owned_process", forbidden)
    token, device = request()
    reader._play([], "A quest line", token, device, 1, True, tmp_path)


def test_stop_during_audio_spawn_closes_child_without_payload(monkeypatch,
                                                              tmp_path: Path) -> None:
    reader = module.ResidentAutoReader()
    reader._generation = 1
    child = object()
    terminated: list[object] = []

    def spawn(*_args, **_kwargs):
        reader._generation += 1
        reader._cancel.set()
        return child, None

    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("canceled request sent audio payload")

    monkeypatch.setattr(module, "_owned_process", spawn)
    monkeypatch.setattr(module, "_send", forbidden)
    monkeypatch.setattr(module, "_terminate", lambda process, _job: terminated.append(process))
    token, device = request()
    reader._play([], "A quest line", token, device, 1, True, tmp_path)
    assert terminated == [child]
    assert reader._audio is None
