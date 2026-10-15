"""Independent boundaries for the first user-editable settings delta."""
import copy

import pytest

from tools.validate_contracts import (
    ContractError,
    validate_defaults,
    validate_runtime_preferences,
)


@pytest.mark.parametrize("value", [
    {"schema_version": 1},
    {"schema_version": 1, "audio": {"follow_system_default": True}},
    {"schema_version": 1, "privacy": {"history_enabled": False}},
    {"schema_version": 1, "audio": {"follow_system_default": False},
     "privacy": {"history_enabled": True}},
])
def test_explicitly_permitted_preferences(value):
    before = copy.deepcopy(value)
    validate_runtime_preferences(value)
    assert value == before


@pytest.mark.parametrize("value", [
    {"schema_version": 2},
    {"schema_version": 1, "scope": {"capture": "desktop"}},
    {"schema_version": 1, "speech": {"premium_enabled": True}},
    {"schema_version": 1, "corpus": {"full_section_expansion": True}},
    {"schema_version": 1, "audio": {"device_id": "unverified"}},
    {"schema_version": 1, "audio": {"follow_system_default": 1}},
    {"schema_version": 1, "privacy": {"history_enabled": "false"}},
    {"schema_version": 1, "privacy": {}},
    {"schema_version": 1, "command": "run shell"},
])
def test_unlisted_or_invalid_settings_rejected(value):
    with pytest.raises(ContractError):
        validate_runtime_preferences(value)


def test_shipped_defaults_remain_fixed_when_runtime_setting_changes():
    from pathlib import Path

    from tools.validate_contracts import load_json

    path = Path(__file__).resolve().parents[2] / "docs/design-v2/contracts/defaults.json"
    defaults = load_json(path)
    defaults["privacy"]["history_enabled"] = False
    with pytest.raises(ContractError):
        validate_defaults(defaults)
