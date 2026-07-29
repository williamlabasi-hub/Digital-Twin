"""Validate and integrate object-identification input records.

This module prepares evidence for later catalog association. It does not decide
identity, affiliation, or public classification.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_ROOT = (
    REPOSITORY_ROOT / "docs" / "requirements" / "object_identification"
)

SCHEMA_PATHS = {
    "observation": REQUIREMENTS_ROOT / "tracking-observation.schema.json",
    "catalog": REQUIREMENTS_ROOT / "object-catalog-record.schema.json",
    "orbital": REQUIREMENTS_ROOT / "orbital-state-record.schema.json",
    "affiliation": REQUIREMENTS_ROOT / "affiliation-record.schema.json",
}


class ObjectIdentificationInputError(ValueError):
    """Raised when identification evidence violates its contract."""


def load_json_object(path: str | Path, record_type: str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ObjectIdentificationInputError(
            f"{record_type}: file does not exist: {source}"
        )
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ObjectIdentificationInputError(
            f"{record_type}: invalid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ObjectIdentificationInputError(
            f"{record_type}: expected one JSON object"
        )
    return value


def load_schema(record_type: str) -> dict[str, Any]:
    try:
        schema_path = SCHEMA_PATHS[record_type]
    except KeyError as exc:
        raise ObjectIdentificationInputError(
            f"unsupported record type: {record_type}"
        ) from exc
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectIdentificationInputError(
            f"{record_type}: unable to load schema: {schema_path}"
        ) from exc
    Draft202012Validator.check_schema(schema)
    return schema


def validate_record(record: dict[str, Any], record_type: str) -> None:
    validator = Draft202012Validator(
        load_schema(record_type),
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
    raise ObjectIdentificationInputError(
        f"{record_type}: schema validation failed: " + " | ".join(details)
    )


def parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObjectIdentificationInputError(
            f"{field_name}: invalid date-time"
        ) from exc
    if parsed.tzinfo is None:
        raise ObjectIdentificationInputError(
            f"{field_name}: timezone is required"
        )
    return parsed.astimezone(timezone.utc)


def validate_covariance_matrix(
    matrix: list[list[float]],
    field_name: str,
) -> None:
    """Require a finite, symmetric, positive-definite 3x3 covariance."""
    values = [[float(value) for value in row] for row in matrix]
    if not all(math.isfinite(value) for row in values for value in row):
        raise ObjectIdentificationInputError(
            f"{field_name}: covariance values must be finite"
        )
    tolerance = 1e-12
    for row in range(3):
        for column in range(row + 1, 3):
            if not math.isclose(
                values[row][column],
                values[column][row],
                rel_tol=1e-9,
                abs_tol=tolerance,
            ):
                raise ObjectIdentificationInputError(
                    f"{field_name}: covariance must be symmetric"
                )
    minor_1 = values[0][0]
    minor_2 = (
        values[0][0] * values[1][1]
        - values[0][1] * values[1][0]
    )
    determinant = (
        values[0][0]
        * (values[1][1] * values[2][2] - values[1][2] * values[2][1])
        - values[0][1]
        * (values[1][0] * values[2][2] - values[1][2] * values[2][0])
        + values[0][2]
        * (values[1][0] * values[2][1] - values[1][1] * values[2][0])
    )
    if minor_1 <= 0 or minor_2 <= 0 or determinant <= 0:
        raise ObjectIdentificationInputError(
            f"{field_name}: covariance must be positive definite"
        )


def _validate_cross_record_consistency(
    observation: dict[str, Any],
    catalog: dict[str, Any],
    orbital: dict[str, Any],
    affiliation: dict[str, Any],
) -> None:
    canonical_id = catalog["canonical_object_id"]
    if affiliation["canonical_object_id"] != canonical_id:
        raise ObjectIdentificationInputError(
            "affiliation canonical_object_id does not match catalog"
        )
    if orbital["subject_id_type"] != "canonical_object_id":
        raise ObjectIdentificationInputError(
            "candidate orbital state must use canonical_object_id"
        )
    if orbital["subject_id"] != canonical_id:
        raise ObjectIdentificationInputError(
            "orbital subject_id does not match catalog canonical_object_id"
        )
    if orbital["orbital_record_id"] != catalog["orbital_record_id"]:
        raise ObjectIdentificationInputError(
            "orbital_record_id does not match catalog reference"
        )
    if orbital["coordinate_frame"] != observation["coordinate_frame"]:
        raise ObjectIdentificationInputError(
            "observation and orbital state coordinate frames do not match"
        )
    for record_name, record in (
        ("observation", observation),
        ("orbital", orbital),
    ):
        for covariance_field in (
            "position_covariance_km2",
            "velocity_covariance_km2_s2",
        ):
            if covariance_field in record:
                validate_covariance_matrix(
                    record[covariance_field],
                    f"{record_name}.{covariance_field}",
                )

    observed_at = parse_timestamp(
        observation["timestamp"], "observation.timestamp"
    )
    orbital_at = parse_timestamp(orbital["timestamp"], "orbital.timestamp")
    if orbital_at > observed_at:
        raise ObjectIdentificationInputError(
            "candidate orbital state is later than the observation"
        )

    catalog_start = parse_timestamp(catalog["valid_from"], "catalog.valid_from")
    catalog_end = (
        parse_timestamp(catalog["valid_to"], "catalog.valid_to")
        if catalog["valid_to"] is not None
        else None
    )
    if observed_at < catalog_start or (
        catalog_end is not None and observed_at > catalog_end
    ):
        raise ObjectIdentificationInputError(
            "catalog record is not valid at the observation timestamp"
        )

    affiliation_start = parse_timestamp(
        affiliation["affiliation_effective_at"],
        "affiliation.affiliation_effective_at",
    )
    affiliation_end = (
        parse_timestamp(
            affiliation["affiliation_expires_at"],
            "affiliation.affiliation_expires_at",
        )
        if affiliation["affiliation_expires_at"] is not None
        else None
    )
    if observed_at < affiliation_start or (
        affiliation_end is not None and observed_at > affiliation_end
    ):
        raise ObjectIdentificationInputError(
            "affiliation record is not effective at the observation timestamp"
        )


def prepare_identification_input(
    observation: dict[str, Any],
    catalog: dict[str, Any],
    orbital: dict[str, Any],
    affiliation: dict[str, Any],
    *,
    prepared_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate and normalize one observation/candidate evidence set."""
    records = {
        "observation": observation,
        "catalog": catalog,
        "orbital": orbital,
        "affiliation": affiliation,
    }
    for record_type, record in records.items():
        validate_record(record, record_type)
    _validate_cross_record_consistency(
        observation, catalog, orbital, affiliation
    )

    generated_at = prepared_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ObjectIdentificationInputError(
            "prepared_at must be timezone-aware"
        )

    return {
        "schema_version": "0.1.0",
        "prepared_at": generated_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "observation": {
            "observation_id": observation["observation_id"],
            "track_id": observation["track_id"],
            "timestamp": observation["timestamp"],
            "sensor_id": observation["sensor"]["sensor_id"],
            "sensor_type": observation["sensor"]["sensor_type"],
            "data_source": observation["data_source"],
            "coordinate_frame": observation["coordinate_frame"],
            "position_km": observation["position_km"],
            "velocity_km_s": observation["velocity_km_s"],
            "position_covariance_km2": observation.get(
                "position_covariance_km2"
            ),
            "velocity_covariance_km2_s2": observation.get(
                "velocity_covariance_km2_s2"
            ),
            "measurement_quality": observation["measurement_quality"],
            "radar_cross_section_m2": observation.get(
                "radar_cross_section_m2"
            ),
            "estimated_size_m": observation.get("estimated_size_m"),
        },
        "candidate": {
            "canonical_object_id": catalog["canonical_object_id"],
            "catalog_source": catalog["catalog_source"],
            "catalog_record_id": catalog["catalog_record_id"],
            "catalog_valid_from": catalog["valid_from"],
            "catalog_valid_to": catalog["valid_to"],
            "object_name": catalog.get("object_name"),
            "object_type": catalog["object_type"],
            "affiliation": affiliation["affiliation"],
            "affiliation_authority": affiliation["affiliation_authority"],
            "affiliation_source_record_id": affiliation[
                "affiliation_source_record_id"
            ],
            "affiliation_effective_at": affiliation[
                "affiliation_effective_at"
            ],
            "affiliation_expires_at": affiliation[
                "affiliation_expires_at"
            ],
            "designation_status": affiliation["designation_status"],
        },
        "orbital_state": {
            "orbital_record_id": orbital["orbital_record_id"],
            "timestamp": orbital["timestamp"],
            "coordinate_frame": orbital["coordinate_frame"],
            "position_km": orbital["position_km"],
            "velocity_km_s": orbital["velocity_km_s"],
            "position_covariance_km2": orbital.get(
                "position_covariance_km2"
            ),
            "velocity_covariance_km2_s2": orbital.get(
                "velocity_covariance_km2_s2"
            ),
            "source": orbital["source"],
            "derivation": orbital["derivation"],
        },
        "preparation_status": {
            "valid": True,
            "classification_performed": False,
            "notes": [
                "Inputs passed schema and cross-record validation.",
                "Candidate association has not been scored or classified.",
            ],
        },
    }


def prepare_identification_input_from_files(
    observation_path: str | Path,
    catalog_path: str | Path,
    orbital_path: str | Path,
    affiliation_path: str | Path,
    *,
    prepared_at: datetime | None = None,
) -> dict[str, Any]:
    return prepare_identification_input(
        load_json_object(observation_path, "observation"),
        load_json_object(catalog_path, "catalog"),
        load_json_object(orbital_path, "orbital"),
        load_json_object(affiliation_path, "affiliation"),
        prepared_at=prepared_at,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and integrate object-identification evidence. "
            "No identity classification is performed."
        )
    )
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--orbital", type=Path, required=True)
    parser.add_argument("--affiliation", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path; stdout is used when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        prepared = prepare_identification_input_from_files(
            args.observation,
            args.catalog,
            args.orbital,
            args.affiliation,
        )
    except ObjectIdentificationInputError as exc:
        print(f"Object-identification input error: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(prepared, indent=2)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Prepared evidence written to: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
