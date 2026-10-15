"""Independent original negative cases for the fixed v2 wire/defaults snapshot."""
import copy
import json
from pathlib import Path

import pytest

from tools.validate_contracts import (
    ContractError,
    load_json,
    validate_defaults,
    validate_ipc,
)

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/design-v2"


def defaults():
    return load_json(DESIGN / "contracts/defaults.json")


def synthesize():
    return load_json(DESIGN / "contracts/ipc.examples.json")["examples"][2]


def test_shipped_defaults_are_accepted():
    validate_defaults(defaults())


@pytest.mark.parametrize("section,key,value", [
    ("scope", "capture", "desktop"),
    ("privacy", "cloud_inference", True),
    ("control", "auto_on_launch", True),
    ("speech", "unit_max_codepoints", 281),
    ("worker", "cancel_terminal_ms", 1001),
    ("control", "auto_on_launch", 0),
])
def test_unsafe_or_changed_default_rejected(section, key, value):
    data = defaults()
    data[section][key] = value
    with pytest.raises(ContractError):
        validate_defaults(data)


def test_unknown_and_missing_default_keys_rejected():
    data = defaults()
    data["corpus"]["full_section_expansion"] = True
    with pytest.raises(ContractError):
        validate_defaults(data)
    del data["corpus"]["full_section_expansion"]
    del data["control"]["max_domain_events"]
    with pytest.raises(ContractError):
        validate_defaults(data)


def test_unicode_boundary_counts_codepoints_not_utf8_bytes():
    data = synthesize()
    data["payload"]["speech_text"] = "é" * 280
    validate_ipc(data)
    data["payload"]["speech_text"] += "é"
    with pytest.raises(ContractError):
        validate_ipc(data)


@pytest.mark.parametrize("mutation", ["version", "extra", "empty_text", "unknown_type", "bool_sequence"])
def test_bad_wire_shape_rejected(mutation):
    data = synthesize()
    if mutation == "version":
        data["protocol"]["minor"] = 1
    elif mutation == "extra":
        data["payload"]["command"] = "echo untrusted"
    elif mutation == "empty_text":
        data["payload"]["speech_text"] = ""
    elif mutation == "unknown_type":
        data["type"] = "execute"
    else:
        data["seq"] = True
    with pytest.raises(ContractError):
        validate_ipc(data)


def test_completed_descriptor_rejects_traversal():
    data = load_json(DESIGN / "contracts/ipc.examples.json")["examples"][4]
    data["payload"]["result"]["filename"] = "../escape.wav"
    with pytest.raises(ContractError):
        validate_ipc(data)


def test_validation_does_not_mutate_or_authorize_message():
    data = synthesize()
    before = copy.deepcopy(data)
    validate_ipc(data)
    assert data == before
    # Syntactically valid old context remains valid syntax. This tool cannot admit
    # it for playback: freshness/cancellation/authorization belong to the host.
    data["payload"]["context"]["generation"] = 0
    validate_ipc(data)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff', b'[]'])
def test_strict_json_rejects_ambiguous_or_invalid_input(tmp_path, raw):
    path = tmp_path / "untrusted.json"
    path.write_bytes(raw)
    with pytest.raises(ContractError):
        load_json(path)


def test_size_limit_checked_before_loading(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_text(json.dumps({"text": "x" * 40}))
    with pytest.raises(ContractError, match="size"):
        load_json(path, max_bytes=20)


def test_missing_file_is_typed_error(tmp_path):
    with pytest.raises(ContractError):
        load_json(tmp_path / "missing.json")
