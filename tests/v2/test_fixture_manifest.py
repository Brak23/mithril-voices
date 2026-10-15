"""Check original synthetic fixture provenance and independent oracle labels."""
import hashlib
from pathlib import Path

from tools.validate_contracts import load_json

FIXTURES = Path(__file__).with_name("fixtures")


def test_fixture_hash_and_split_are_recorded_before_candidate_code():
    manifest = load_json(FIXTURES / "manifest.json")
    assert manifest["schema_version"] == 1
    assert len(manifest["fixtures"]) == 1
    row = manifest["fixtures"][0]
    assert row["path"] == "desired-outcomes.json"
    assert row["provenance"] == "ORIGINAL_SYNTHETIC"
    assert row["split"] == "development"
    assert row["candidate_output_used_for_labels"] is False
    assert hashlib.sha256((FIXTURES / row["path"]).read_bytes()).hexdigest() == row["sha256"]


def test_expected_outcomes_are_separate_from_future_product_results():
    fixture = load_json(FIXTURES / "desired-outcomes.json")
    assert fixture["provenance"] == "ORIGINAL_SYNTHETIC"
    cases = {row["id"]: row for row in fixture["cases"]}
    assert set(cases) == {"stop-late-a", "stop-before-ocr", "same-npc-new-page"}
    assert {row["acceptance_case"] for row in cases.values()} == {"AT-001", "AT-002", "AT-010"}
    assert len({row["family"] for row in cases.values()}) == len(cases)
    assert cases["stop-late-a"]["expected"]["post_fence_audio_from_A"] == 0
    assert cases["stop-late-a"]["expected"]["admitted_request_ids"] == ["B"]
    assert cases["stop-before-ocr"]["expected"]["automatic_synthesis_count"] == 0
    assert cases["stop-before-ocr"]["expected"]["auto_held_unknown"] is True
    assert cases["same-npc-new-page"]["expected"]["new_page_B_observed_while_A_playing"] is True
