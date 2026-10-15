"""Strict developer validation of the fixed v2 snapshot, never playback authority.

Schema validity cannot establish sender role, current request identity, freshness,
file containment, rights or authorization. Those remain future host checks.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

DESIGN = Path(__file__).resolve().parents[1] / "docs/design-v2"
MAX_JSON_BYTES = 1_048_576


class ContractError(ValueError):
    """Rejected input; message deliberately excludes quest text and file contents."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ContractError("Duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise ContractError("Nonfinite JSON number")


def load_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    if isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ContractError("Invalid JSON size limit")
    try:
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ContractError("JSON size limit exceeded")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
        if not isinstance(value, dict):
            raise ContractError("JSON root must be an object")
        return value
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractError("Unreadable or malformed JSON") from exc


@lru_cache(maxsize=2)
def _validator(name: str) -> Draft202012Validator:
    if name not in {"defaults.schema.json", "ipc.schema.json"}:
        raise ContractError("Schema not allowlisted")
    schema = load_json(DESIGN / "contracts" / name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ContractError("Invalid bundled schema") from exc
    return Draft202012Validator(schema)


def _validate(value: dict[str, Any], name: str) -> None:
    try:
        # jsonschema's number type alone does not reject Python's NaN/Infinity.
        json.dumps(value, allow_nan=False)
        _validator(name).validate(value)
    except (ValidationError, ValueError, TypeError, RecursionError) as exc:
        raise ContractError("Contract validation rejected input") from exc


def validate_defaults(value: dict[str, Any]) -> None:
    """Validate exact shipped defaults, not every future runtime preference."""
    _validate(value, "defaults.schema.json")


def validate_ipc(value: dict[str, Any]) -> None:
    """Validate wire syntax only, without execution or lifecycle admission."""
    _validate(value, "ipc.schema.json")


def validate_snapshot() -> dict[str, int]:
    validate_defaults(load_json(DESIGN / "contracts/defaults.json"))
    examples = load_json(DESIGN / "contracts/ipc.examples.json")["examples"]
    if not isinstance(examples, list) or not examples:
        raise ContractError("Missing example inventory")
    for example in examples:
        validate_ipc(example)
    return {"defaults_snapshots": 1, "ipc_examples": len(examples)}


if __name__ == "__main__":
    print(json.dumps(validate_snapshot()))
