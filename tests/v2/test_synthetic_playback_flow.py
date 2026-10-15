"""Desired synthetic text -> worker -> renderer-controller outcomes."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from lvc.core import PageIdentity, RequestToken
from lvc.synthetic_flow import AcceptedUnit, SyntheticFlow
from tests.v2.support import RecordingSink
from tools.validate_contracts import load_json, validate_ipc

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = load_json(ROOT / "docs/design-v2/contracts/ipc.examples.json")["examples"][4]
SESSION = UUID(EXAMPLE["session_id"])
WORKER = UUID(EXAMPLE["worker_instance_id"])
WORKER_B = UUID("00000000-0000-4000-8000-000000000012")
REQUEST_A = UUID(EXAMPLE["payload"]["request_id"])
REQUEST_B = UUID("00000000-0000-4000-8000-000000000013")
BINDING = UUID(EXAMPLE["payload"]["context"]["binding_id"])
PAGE = PageIdentity(UUID(EXAMPLE["payload"]["context"]["interaction_id"]),
                    1, "quest_body", "synthetic-content")


@dataclass
class FakeWorker:
    submitted: list[tuple[RequestToken, str]] = field(default_factory=list)
    canceled: list[RequestToken] = field(default_factory=list)

    def submit(self, token: RequestToken, text: str) -> None:
        self.submitted.append((token, text))

    def cancel(self, token: RequestToken) -> None:
        self.canceled.append(token)


@dataclass
class FakeVerifier:
    calls: int = 0
    reject: bool = False

    def __call__(self, token: RequestToken, result: dict, text: str,
                 current) -> AcceptedUnit:
        assert token.request_id and text and current()
        self.calls += 1
        if self.reject:
            raise ValueError("fake invalid audio")
        return AcceptedUnit("original-synthetic-unit", result["unit_id"], 5)


def flow() -> tuple[SyntheticFlow, FakeWorker, RecordingSink, FakeVerifier]:
    worker, sink, verifier = FakeWorker(), RecordingSink(), FakeVerifier()
    return SyntheticFlow(SESSION, WORKER, BINDING, 1, worker, sink, verifier,
                         validate_ipc), worker, sink, verifier


def submit(controller: SyntheticFlow, request_id: UUID, now_ms: int) -> RequestToken:
    controller.read_current(request_id, now_ms)
    controller.text_accepted(request_id, PAGE, "Original synthetic speech.", now_ms + 1)
    token = controller.state.synthesis
    assert token is not None
    return token


def completed(controller: SyntheticFlow, token: RequestToken) -> dict:
    message = deepcopy(EXAMPLE)
    message["payload"]["request_id"] = str(token.request_id)
    message["worker_instance_id"] = str(controller.worker_id)
    message["payload"]["context"] = controller._context(token)
    message["payload"]["result"]["filename"] = f"{token.request_id}.wav"
    validate_ipc(message)
    return message


def failed(token: RequestToken, code: str) -> dict:
    message = {"protocol": {"major": 1, "minor": 0}, "type": "failed",
               "session_id": str(SESSION), "worker_instance_id": str(WORKER), "seq": 3,
               "payload": {"request_id": str(token.request_id), "code": code,
                           "detail_safe": "synthetic failure", "retryable": False}}
    validate_ipc(message)
    return message


def test_one_unit_requires_fence_ack_and_renderer_drain_before_completion():
    controller, worker, sink, verifier = flow()
    token = submit(controller, REQUEST_A, 0)
    assert worker.submitted == [(token, "Original synthetic speech.")]
    assert controller.receive_terminal(completed(controller, token), 2)
    assert verifier.calls == 1 and controller.state.playback == "PREPARING"
    assert not controller.pump(5) and sink.calls[-1].kind == "fence"
    controller.acknowledge_fence(token.generation, 1)
    assert controller.pump(3) and controller.state.playback == "PLAYING"
    assert not controller.sink_idle()  # Source and ring are not drained.
    controller.drain(3)
    assert not controller.sink_idle()  # More source frames remain.
    assert controller.pump(2)
    assert not controller.sink_idle()  # Last write is not physical drain.
    controller.drain(2)
    assert controller.sink_idle() and controller.state.playback == "COMPLETED"
    assert [call.kind for call in sink.calls] == ["fence", "fence_ack", "write", "write"]


def test_stop_fences_a_late_completion_and_b_can_play_without_a_writes():
    controller, worker, sink, verifier = flow()
    a = submit(controller, REQUEST_A, 0)
    controller.acknowledge_fence(a.generation, 1)
    controller.stop(2)
    assert worker.canceled == [a]
    assert not controller.receive_terminal(completed(controller, a), 3)
    assert verifier.calls == 0 and not controller.pump(1)
    controller.worker_tree_exited(WORKER_B, 4)
    b = submit(controller, REQUEST_B, 4)
    controller.acknowledge_fence(b.generation, 2)
    retired = completed(controller, a)
    retired["worker_instance_id"] = str(WORKER)
    assert not controller.receive_terminal(retired, 5)
    assert controller.state.synthesis == b
    assert controller.receive_terminal(completed(controller, b), 6)
    assert controller.pump(5)
    controller.drain(5)
    assert controller.sink_idle()
    assert [call.request_id for call in sink.calls if call.kind == "write"] == [str(b.request_id)]
    assert controller.state.stale_results >= 1


def test_worker_failure_fences_without_silently_completing_or_playing():
    controller, _, sink, verifier = flow()
    token = submit(controller, REQUEST_A, 0)
    controller.acknowledge_fence(token.generation, 1)
    assert not controller.receive_terminal(failed(token, "MODEL_TIMEOUT"), 2)
    assert controller.state.playback == "FAILED" and controller.state.failure_code == "MODEL_TIMEOUT"
    assert controller.gate.minimum_generation > token.generation
    assert not controller.pump(1) and verifier.calls == 0
    assert not [call for call in sink.calls if call.kind == "write"]


def test_invalid_audio_verifier_fails_closed():
    controller, _, sink, verifier = flow()
    verifier.reject = True
    token = submit(controller, REQUEST_A, 0)
    controller.acknowledge_fence(token.generation, 1)
    assert not controller.receive_terminal(completed(controller, token), 2)
    assert controller.state.playback == "FAILED" and controller.state.failure_code == "AUDIO_INVALID"
    assert controller.ledger.outcome(token.request_id) == "failed"
    assert not controller.pump(1)
    assert not [call for call in sink.calls if call.kind == "write"]


def test_mismatched_completed_context_fails_protocol_without_verification():
    controller, _, sink, verifier = flow()
    token = submit(controller, REQUEST_A, 0)
    message = completed(controller, token)
    message["payload"]["context"]["generation"] += 1
    assert not controller.receive_terminal(message, 2)
    assert controller.state.playback == "FAILED" and controller.state.failure_code == "PROTOCOL_INVALID"
    assert verifier.calls == 0 and not [call for call in sink.calls if call.kind == "write"]


def test_duplicate_terminal_cannot_verify_or_prepare_twice():
    controller, _, sink, verifier = flow()
    token = submit(controller, REQUEST_A, 0)
    controller.acknowledge_fence(token.generation, 1)
    message = completed(controller, token)
    assert controller.receive_terminal(message, 2)
    assert not controller.receive_terminal(message, 3)
    assert verifier.calls == 1
    assert controller.pump(5)
    assert len([call for call in sink.calls if call.kind == "write"]) == 1


def test_stop_after_partial_write_blocks_late_pump_and_idle():
    controller, _, sink, _ = flow()
    token = submit(controller, REQUEST_A, 0)
    controller.acknowledge_fence(token.generation, 1)
    assert controller.receive_terminal(completed(controller, token), 2)
    assert controller.pump(2)
    controller.stop(3)
    assert not controller.pump(3)
    controller.drain(2)
    assert not controller.sink_idle()
    assert controller.state.playback == "STOPPED"
    assert len([call for call in sink.calls if call.kind == "write"]) == 1
