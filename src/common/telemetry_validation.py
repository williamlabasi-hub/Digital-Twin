"""Validate housekeeping telemetry before health-model inference.

Structural rules come from the JSON Schema. Engineering meaning, physical
ranges, nullability, and staleness rules come from the YAML telemetry
dictionary. Operational warning/critical limits are intentionally not applied
until spacecraft-specific limits have been reviewed and approved.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

TELEMETRY_REQUIREMENTS_DIR = (
    REPOSITORY_ROOT
    / "docs"
    / "requirements"
    / "telemetry"
)

DEFAULT_SCHEMA_PATH = (
    TELEMETRY_REQUIREMENTS_DIR
    / "housekeeping-telemetry.schema.json"
)

DEFAULT_DICTIONARY_PATH = (
    TELEMETRY_REQUIREMENTS_DIR
    / "housekeeping-telemetry.yaml"
)


@dataclass(frozen=True)
class ValidationIssue:
    """One validation finding."""

    severity: str
    code: str
    message: str
    path: str
    parameter: str | None = None


@dataclass
class ValidationResult:
    """Validation outcome for one telemetry record."""

    satellite_id: str | None
    timestamp: str | None
    issues: list[ValidationIssue]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def data_quality(self) -> str:
        if not self.valid:
            return "invalid"
        if self.issues:
            return "degraded"
        return "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "data_quality": self.data_quality,
            "satellite_id": self.satellite_id,
            "timestamp": self.timestamp,
            "issues": [asdict(issue) for issue in self.issues],
        }


def load_json(path: Path) -> Any:
    """Load JSON from disk with a useful file-not-found error."""

    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_contracts(
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    dictionary_path: Path = DEFAULT_DICTIONARY_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and perform basic checks on the schema and YAML dictionary."""

    schema = load_json(schema_path)
    if not dictionary_path.exists():
        raise FileNotFoundError(
            f"Telemetry dictionary not found: {dictionary_path}"
        )
    with dictionary_path.open("r", encoding="utf-8") as file:
        dictionary = yaml.safe_load(file)

    if not isinstance(dictionary, dict):
        raise ValueError("Telemetry dictionary must contain a YAML object.")
    if not isinstance(dictionary.get("parameters"), dict):
        raise ValueError("Telemetry dictionary is missing its parameters map.")

    dictionary_version = str(dictionary.get("schema_version"))
    schema_version = schema.get("properties", {}).get("schema_version", {}).get(
        "const"
    )
    if dictionary_version != str(schema_version):
        raise ValueError(
            "Contract version mismatch: dictionary is "
            f"{dictionary_version}, schema is {schema_version}."
        )

    Draft202012Validator.check_schema(schema)
    return schema, dictionary


def _json_path(parts: Iterable[Any]) -> str:
    return "/" + "/".join(str(part) for part in parts)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _range_issues(
    parameter: str,
    value: Any,
    definition: dict[str, Any],
) -> list[ValidationIssue]:
    physical_range = definition.get("physical_range")
    if not isinstance(physical_range, dict):
        return []

    number = _numeric(value)
    if number is None:
        return []

    checks = (
        ("minimum", lambda actual, limit: actual < limit, ">="),
        ("maximum", lambda actual, limit: actual > limit, "<="),
        ("minimum_inclusive", lambda actual, limit: actual < limit, ">="),
        ("maximum_inclusive", lambda actual, limit: actual > limit, "<="),
        ("minimum_exclusive", lambda actual, limit: actual <= limit, ">"),
        ("maximum_exclusive", lambda actual, limit: actual >= limit, "<"),
    )

    issues: list[ValidationIssue] = []
    for key, violates, symbol in checks:
        limit = _numeric(physical_range.get(key))
        if limit is not None and violates(number, limit):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="physical_range_violation",
                    message=(
                        f"{parameter}={number:g} must be {symbol} {limit:g} "
                        f"{definition.get('unit') or ''}".rstrip()
                    ),
                    path=f"/telemetry/{parameter}",
                    parameter=parameter,
                )
            )
    return issues


def _semantic_issues(
    record: dict[str, Any],
    dictionary: dict[str, Any],
    reference_time: datetime,
    future_tolerance_seconds: float,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    definitions = dictionary["parameters"]
    telemetry = record.get("telemetry")
    if not isinstance(telemetry, dict):
        return issues

    timestamp = _parse_datetime(record.get("timestamp"))
    if timestamp is not None:
        reference_time = reference_time.astimezone(timezone.utc)
        age_seconds = (reference_time - timestamp).total_seconds()
        if age_seconds < -future_tolerance_seconds:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="future_timestamp",
                    message=(
                        "Telemetry timestamp is more than "
                        f"{future_tolerance_seconds:g} seconds in the future."
                    ),
                    path="/timestamp",
                )
            )
    else:
        age_seconds = None

    for parameter, definition in definitions.items():
        if parameter not in telemetry:
            if definition.get("nullable") is False:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="required_parameter_missing",
                        message=f"Required telemetry parameter is missing: {parameter}",
                        path=f"/telemetry/{parameter}",
                        parameter=parameter,
                    )
                )
            continue

        value = telemetry[parameter]
        if value is None:
            if definition.get("nullable") is False:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="null_not_allowed",
                        message=f"Telemetry parameter may not be null: {parameter}",
                        path=f"/telemetry/{parameter}",
                        parameter=parameter,
                    )
                )
            continue

        issues.extend(_range_issues(parameter, value, definition))

        stale_after = _numeric(definition.get("stale_after_seconds"))
        if age_seconds is not None and stale_after is not None:
            if age_seconds > stale_after:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="stale_parameter",
                        message=(
                            f"{parameter} is {age_seconds:g} seconds old; "
                            f"limit is {stale_after:g} seconds."
                        ),
                        path=f"/telemetry/{parameter}",
                        parameter=parameter,
                    )
                )

    vector_components = [
        _numeric(telemetry.get(name))
        for name in ("magnetometer_x_ut", "magnetometer_y_ut", "magnetometer_z_ut")
    ]
    reported_magnitude = _numeric(telemetry.get("magnetic_field_magnitude_ut"))
    if all(value is not None for value in vector_components) and reported_magnitude is not None:
        calculated = math.sqrt(sum(value * value for value in vector_components))
        tolerance = max(0.5, calculated * 0.02)
        if abs(reported_magnitude - calculated) > tolerance:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="magnetic_magnitude_mismatch",
                    message=(
                        "Reported magnetic-field magnitude does not match the "
                        f"vector components: reported={reported_magnitude:g} uT, "
                        f"calculated={calculated:.3f} uT."
                    ),
                    path="/telemetry/magnetic_field_magnitude_ut",
                    parameter="magnetic_field_magnitude_ut",
                )
            )

    return issues


def validate_telemetry_record(
    record: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
    dictionary: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    future_tolerance_seconds: float = 300,
) -> ValidationResult:
    """Validate one record and return errors/warnings without raising."""

    if schema is None or dictionary is None:
        loaded_schema, loaded_dictionary = load_contracts()
        schema = schema or loaded_schema
        dictionary = dictionary or loaded_dictionary

    issues: list[ValidationIssue] = []
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(record), key=lambda item: list(item.path)):
        issues.append(
            ValidationIssue(
                severity="error",
                code="schema_validation_error",
                message=error.message,
                path=_json_path(error.absolute_path),
            )
        )

    if isinstance(record, dict):
        issues.extend(
            _semantic_issues(
                record,
                dictionary,
                reference_time or datetime.now(timezone.utc),
                future_tolerance_seconds,
            )
        )

    return ValidationResult(
        satellite_id=(
            str(record.get("satellite_id"))
            if isinstance(record, dict) and record.get("satellite_id") is not None
            else None
        ),
        timestamp=(
            str(record.get("timestamp"))
            if isinstance(record, dict) and record.get("timestamp") is not None
            else None
        ),
        issues=issues,
    )


def validate_telemetry_batch(
    records: list[dict[str, Any]],
    *,
    schema: dict[str, Any] | None = None,
    dictionary: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
) -> list[ValidationResult]:
    """Validate records and flag duplicate satellite/timestamp observations."""

    if schema is None or dictionary is None:
        loaded_schema, loaded_dictionary = load_contracts()
        schema = schema or loaded_schema
        dictionary = dictionary or loaded_dictionary

    results = [
        validate_telemetry_record(
            record,
            schema=schema,
            dictionary=dictionary,
            reference_time=reference_time,
        )
        for record in records
    ]

    seen: dict[tuple[Any, Any], int] = {}
    for index, record in enumerate(records):
        key = (record.get("satellite_id"), record.get("timestamp"))
        if key in seen:
            first_index = seen[key]
            results[index].issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_record",
                    message=(
                        "Duplicate satellite_id/timestamp observation; "
                        f"first occurrence is record {first_index}."
                    ),
                    path=f"/{index}",
                )
            )
        else:
            seen[key] = index

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate satellite housekeeping telemetry JSON."
    )
    parser.add_argument("input", type=Path, help="JSON object or array to validate")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY_PATH)
    parser.add_argument(
        "--reference-time",
        help="ISO-8601 time used for staleness checks; defaults to current UTC.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = load_json(args.input)
    schema, dictionary = load_contracts(args.schema, args.dictionary)
    reference_time = (
        _parse_datetime(args.reference_time)
        if args.reference_time
        else datetime.now(timezone.utc)
    )
    if reference_time is None:
        raise ValueError("--reference-time must be an ISO-8601 timestamp with timezone.")

    records = data if isinstance(data, list) else [data]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Input must be a JSON object or array of JSON objects.")

    results = validate_telemetry_batch(
        records,
        schema=schema,
        dictionary=dictionary,
        reference_time=reference_time,
    )
    output = {
        "valid": all(result.valid for result in results),
        "record_count": len(results),
        "valid_record_count": sum(result.valid for result in results),
        "records": [result.to_dict() for result in results],
    }
    print(json.dumps(output, indent=2))
    return 0 if output["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

