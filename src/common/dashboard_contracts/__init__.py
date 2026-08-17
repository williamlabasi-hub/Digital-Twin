"""Packaged validation for operator-dashboard handoff contracts."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


CONTRACT_VERSION = "1.0.0"
_SCHEMAS = {
    "summary": "golden-path-summary.schema.json",
    "latest": "latest-run.schema.json",
}


class DashboardContractError(ValueError):
    """A dashboard handoff artifact violates its versioned contract."""


def load_dashboard_schema(kind: str) -> dict[str, Any]:
    try:
        filename = _SCHEMAS[kind]
    except KeyError as exc:
        raise DashboardContractError(f"Unknown dashboard contract: {kind}") from exc
    return json.loads(files(__package__).joinpath(filename).read_text(encoding="utf-8"))


def validate_dashboard_contract(record: Mapping[str, Any], kind: str) -> None:
    schema = load_dashboard_schema(kind)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(record),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
            for error in errors
        )
        raise DashboardContractError(f"Invalid dashboard {kind}: {detail}")


__all__ = [
    "CONTRACT_VERSION",
    "DashboardContractError",
    "load_dashboard_schema",
    "validate_dashboard_contract",
]
