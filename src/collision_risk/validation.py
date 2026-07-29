"""Structural and semantic validation for conjunction assessment inputs."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_ROOT = files(__package__).joinpath("schemas")
INPUT_SCHEMA_PATH = SCHEMA_ROOT.joinpath(
    "conjunction-assessment-input.schema.json"
)
OUTPUT_SCHEMA_PATH = SCHEMA_ROOT.joinpath("collision-risk-assessment.schema.json")
MAX_LINEAR_WINDOW_SECONDS = 15 * 60


class ConjunctionInputError(ValueError):
    """A conjunction request is structurally or semantically unusable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_conjunction_input(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ConjunctionInputError(
            "INPUT_FILE_NOT_FOUND",
            f"Conjunction input does not exist: {source}",
        )
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConjunctionInputError(
            "INPUT_JSON_INVALID",
            f"Conjunction input is not valid JSON: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise ConjunctionInputError(
            "INPUT_NOT_OBJECT",
            "Conjunction input must contain one JSON object.",
        )
    return value


def load_schema(path: Any) -> dict[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load collision-risk schema: {path}") from exc
    Draft202012Validator.check_schema(schema)
    return schema


def validate_schema(record: Mapping[str, Any], schema_path: Any) -> None:
    validator = Draft202012Validator(
        load_schema(schema_path),
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(record),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    details = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        details.append(f"{location}: {error.message}")
    raise ConjunctionInputError(
        "SCHEMA_VALIDATION_FAILED",
        "Conjunction input schema validation failed: " + " | ".join(details),
    )


def parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConjunctionInputError(
            "TIMESTAMP_INVALID",
            f"{field_name} is not a valid date-time.",
        ) from exc
    if parsed.tzinfo is None:
        raise ConjunctionInputError(
            "TIMESTAMP_TIMEZONE_MISSING",
            f"{field_name} requires a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _validate_finite_vector(values: list[float], field_name: str) -> None:
    if not all(math.isfinite(float(value)) for value in values):
        raise ConjunctionInputError(
            "STATE_VECTOR_NONFINITE",
            f"{field_name} must contain only finite values.",
        )


def _validate_covariance(
    matrix: list[list[float]],
    field_name: str,
) -> None:
    values = np.asarray(matrix, dtype=float)
    if not np.isfinite(values).all():
        raise ConjunctionInputError(
            "COVARIANCE_NONFINITE",
            f"{field_name} must contain only finite values.",
        )
    if not np.allclose(values, values.T, rtol=1e-9, atol=1e-12):
        raise ConjunctionInputError(
            "COVARIANCE_NOT_SYMMETRIC",
            f"{field_name} must be symmetric.",
        )
    try:
        np.linalg.cholesky(values)
    except np.linalg.LinAlgError as exc:
        raise ConjunctionInputError(
            "COVARIANCE_NOT_POSITIVE_DEFINITE",
            f"{field_name} must be positive definite.",
        ) from exc


def validate_conjunction_input(record: Mapping[str, Any]) -> None:
    """Validate structure and the semantics supported by linear propagation."""

    validate_schema(record, INPUT_SCHEMA_PATH)
    primary = record["primary"]
    secondary = record["secondary"]
    window = record["analysis_window"]

    if primary["object_id"] == secondary["object_id"]:
        raise ConjunctionInputError(
            "OBJECT_IDENTIFIERS_NOT_DISTINCT",
            "Primary and secondary object identifiers must be different.",
        )
    if primary["coordinate_frame"] != secondary["coordinate_frame"]:
        raise ConjunctionInputError(
            "INCOMPATIBLE_COORDINATE_FRAMES",
            "Primary and secondary states must use the same coordinate frame.",
        )

    primary_epoch = parse_timestamp(primary["epoch"], "primary.epoch")
    secondary_epoch = parse_timestamp(secondary["epoch"], "secondary.epoch")
    if primary_epoch != secondary_epoch:
        raise ConjunctionInputError(
            "MISMATCHED_STATE_EPOCHS",
            "Linear closest-approach assessment requires a common state epoch.",
        )

    window_start = parse_timestamp(window["start"], "analysis_window.start")
    window_end = parse_timestamp(window["end"], "analysis_window.end")
    if window_end <= window_start:
        raise ConjunctionInputError(
            "ANALYSIS_WINDOW_INVALID",
            "Analysis-window end must be later than its start.",
        )
    if window_start < primary_epoch:
        raise ConjunctionInputError(
            "ANALYSIS_WINDOW_PRECEDES_STATE",
            "Analysis-window start cannot precede the common state epoch.",
        )
    if (window_end - window_start).total_seconds() > MAX_LINEAR_WINDOW_SECONDS:
        raise ConjunctionInputError(
            "ANALYSIS_WINDOW_TOO_LONG",
            "Prototype linear assessment supports windows no longer than 15 minutes.",
        )

    for name, state in (("primary", primary), ("secondary", secondary)):
        _validate_finite_vector(state["position_km"], f"{name}.position_km")
        _validate_finite_vector(state["velocity_km_s"], f"{name}.velocity_km_s")
        covariance = state.get("state_covariance")
        metadata = state.get("covariance_metadata")
        if covariance is not None:
            _validate_covariance(covariance, f"{name}.state_covariance")
            if metadata["frame"] != state["coordinate_frame"]:
                raise ConjunctionInputError(
                    "COVARIANCE_FRAME_UNSUPPORTED",
                    f"{name} covariance must already use the state-vector frame.",
                )
