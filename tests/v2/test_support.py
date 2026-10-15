"""The doubles must expose unsafe order instead of silently correcting it."""
import pytest

from tests.v2.support import HeldProcess, ManualClock, RecordingSink, post_fence_writes


def test_manual_clock_has_no_wall_time_or_negative_advance():
    clock = ManualClock()
    assert clock.advance(60_000) == 60_000
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        clock.advance(True)
    assert clock.now_ms == 60_000


def test_process_releases_late_reply_after_newer_one_without_rewriting_it():
    child = HeldProcess()
    child.submit({"request": "A"})
    child.hold("A", {"request": "A", "terminal": "completed"})
    child.submit({"request": "B"})
    child.hold("B", {"request": "B", "terminal": "completed"})
    assert child.release("B")["request"] == "B"
    assert child.release("A")["request"] == "A"
    child.crash()
    with pytest.raises(RuntimeError):
        child.submit({"request": "C"})


def test_sink_records_stale_write_so_a_missing_product_fence_can_fail():
    sink = RecordingSink()
    sink.fence(2)
    sink.acknowledge_fence(2)
    sink.write(1, "A", "old")
    sink.write(3, "B", "new")
    assert [(call.request_id, call.generation) for call in post_fence_writes(sink.calls)] == [
        ("A", 1), ("B", 3)
    ]
