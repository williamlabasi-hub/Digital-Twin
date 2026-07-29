"""Adapt propagated orbital data to object-identification input contracts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .input_pipeline import (
    ObjectIdentificationInputError,
    prepare_identification_input,
)


ADAPTER_VERSION = "0.1.0"


def _timestamp_from_propagation(value: dict[str, Any]) -> str:
    try:
        time = value["time"]
        second_value = float(time["second"])
        if not math.isfinite(second_value) or not 0 <= second_value < 60:
            raise ValueError("second must be in [0, 60)")
        timestamp = datetime(
            int(time["year"]),
            int(time["month"]),
            int(time["day"]),
            int(time["hour"]),
            int(time["minute"]),
            tzinfo=timezone.utc,
        ) + timedelta(seconds=second_value)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ObjectIdentificationInputError(
            "propagation.time must contain a valid UTC date and time"
        ) from exc
    return timestamp.isoformat().replace("+00:00", "Z")


def _vector(
    propagation: dict[str, Any],
    field: str,
) -> list[float]:
    value = propagation.get(field)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ObjectIdentificationInputError(
            f"propagation.{field} must be a three-component Cartesian vector"
        )
    try:
        vector = [float(component) for component in value]
    except (TypeError, ValueError) as exc:
        raise ObjectIdentificationInputError(
            f"propagation.{field} must contain numeric components"
        ) from exc
    if not all(math.isfinite(component) for component in vector):
        raise ObjectIdentificationInputError(
            f"propagation.{field} components must be finite"
        )
    return vector


def _coordinate_frame(propagation: dict[str, Any]) -> str:
    frame = propagation.get("coordinate_frame")
    if frame not in {"ECI", "ECEF", "TEME"}:
        raise ObjectIdentificationInputError(
            "propagation.coordinate_frame must be ECI, ECEF, or TEME"
        )
    return frame


def _catalog_identifier(propagation: dict[str, Any]) -> str:
    catalog = propagation.get("catalog")
    if isinstance(catalog, bool) or not isinstance(catalog, (str, int)):
        raise ObjectIdentificationInputError(
            "propagation.catalog must be a catalog identifier"
        )
    rendered = str(catalog).strip()
    if not rendered:
        raise ObjectIdentificationInputError(
            "propagation.catalog must be a catalog identifier"
        )
    return rendered


def _covariance(
    propagation: dict[str, Any],
    field: str,
    override: list[list[float]] | None,
) -> list[list[float]] | None:
    """Use an explicit covariance override or the propagated record value."""
    if override is not None:
        return override
    value = propagation.get(field)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ObjectIdentificationInputError(
            f"propagation.{field} must be a 3x3 covariance matrix"
        )
    return value


def propagation_to_tracking_observation(
    propagation: dict[str, Any],
    *,
    observation_id: str,
    track_id: str,
    sensor_id: str,
    sensor_type: str,
    data_source: str,
    measurement_quality: float,
    position_covariance_km2: list[list[float]] | None = None,
    velocity_covariance_km2_s2: list[list[float]] | None = None,
) -> dict[str, Any]:
    """Build one sensor-observation record from Cartesian propagation output."""
    try:
        quality = float(measurement_quality)
    except (TypeError, ValueError) as exc:
        raise ObjectIdentificationInputError(
            "measurement_quality must be a finite number from zero to one"
        ) from exc
    if not math.isfinite(quality) or not 0 <= quality <= 1:
        raise ObjectIdentificationInputError(
            "measurement_quality must be a finite number from zero to one"
        )
    observation: dict[str, Any] = {
        "schema_version": "0.1.0",
        "observation_id": observation_id,
        "track_id": track_id,
        "timestamp": _timestamp_from_propagation(propagation),
        "sensor": {
            "sensor_id": sensor_id,
            "sensor_type": sensor_type,
        },
        "data_source": data_source,
        "coordinate_frame": _coordinate_frame(propagation),
        "position_km": _vector(propagation, "position_km"),
        "velocity_km_s": _vector(
            propagation,
            "cartesian_velocity_km_s",
        ),
        "measurement_quality": quality,
    }
    position_covariance = _covariance(
        propagation,
        "position_covariance_km2",
        position_covariance_km2,
    )
    velocity_covariance = _covariance(
        propagation,
        "velocity_covariance_km2_s2",
        velocity_covariance_km2_s2,
    )
    if position_covariance is not None:
        observation["position_covariance_km2"] = position_covariance
    if velocity_covariance is not None:
        observation["velocity_covariance_km2_s2"] = velocity_covariance
    return observation


def propagation_to_candidate_records(
    propagation: dict[str, Any],
    *,
    catalog_source: str,
    object_type: str,
    affiliation: str,
    affiliation_authority: str,
    affiliation_source_record_id: str,
    designation_status: str = "prototype_unvalidated",
    canonical_object_id: str | None = None,
    position_covariance_km2: list[list[float]] | None = None,
    velocity_covariance_km2_s2: list[list[float]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build catalog, orbital-state, and affiliation candidate records."""
    catalog_identifier = _catalog_identifier(propagation)
    canonical_id = canonical_object_id or f"CAT-{catalog_identifier}"
    timestamp = _timestamp_from_propagation(propagation)
    orbital_record_id = f"ORB-{catalog_identifier}-{timestamp}"

    orbital: dict[str, Any] = {
        "schema_version": "0.1.0",
        "orbital_record_id": orbital_record_id,
        "subject_id": canonical_id,
        "subject_id_type": "canonical_object_id",
        "timestamp": timestamp,
        "coordinate_frame": _coordinate_frame(propagation),
        "position_km": _vector(propagation, "position_km"),
        "velocity_km_s": _vector(
            propagation,
            "cartesian_velocity_km_s",
        ),
        "source": catalog_source,
        "derivation": {
            "method": "sgp4",
            "version": f"data-gen-adapter-{ADAPTER_VERSION}",
        },
    }
    position_covariance = _covariance(
        propagation,
        "position_covariance_km2",
        position_covariance_km2,
    )
    velocity_covariance = _covariance(
        propagation,
        "velocity_covariance_km2_s2",
        velocity_covariance_km2_s2,
    )
    if position_covariance is not None:
        orbital["position_covariance_km2"] = position_covariance
    if velocity_covariance is not None:
        orbital["velocity_covariance_km2_s2"] = velocity_covariance

    catalog = {
        "schema_version": "0.1.0",
        "canonical_object_id": canonical_id,
        "catalog_source": catalog_source,
        "catalog_record_id": f"{catalog_source}-{catalog_identifier}",
        "valid_from": timestamp,
        "valid_to": None,
        "object_name": propagation.get("name"),
        "object_type": object_type,
        "orbital_record_id": orbital_record_id,
    }
    affiliation_record = {
        "schema_version": "0.1.0",
        "canonical_object_id": canonical_id,
        "affiliation": affiliation,
        "affiliation_authority": affiliation_authority,
        "affiliation_source_record_id": affiliation_source_record_id,
        "affiliation_effective_at": timestamp,
        "affiliation_expires_at": None,
        "designation_status": designation_status,
        "review_notes": (
            "Affiliation was supplied to the adapter; it was not inferred "
            "from orbital data."
        ),
    }
    return catalog, orbital, affiliation_record


def build_identification_records(
    observation_propagation: dict[str, Any],
    candidate_propagation: dict[str, Any],
    *,
    observation_id: str,
    track_id: str,
    sensor_id: str,
    sensor_type: str,
    data_source: str,
    measurement_quality: float,
    catalog_source: str,
    object_type: str,
    affiliation: str,
    affiliation_authority: str,
    affiliation_source_record_id: str,
    designation_status: str = "prototype_unvalidated",
    canonical_object_id: str | None = None,
    observation_position_covariance_km2: (
        list[list[float]] | None
    ) = None,
    observation_velocity_covariance_km2_s2: (
        list[list[float]] | None
    ) = None,
    candidate_position_covariance_km2: (
        list[list[float]] | None
    ) = None,
    candidate_velocity_covariance_km2_s2: (
        list[list[float]] | None
    ) = None,
) -> dict[str, dict[str, Any]]:
    """Adapt and validate a generated observation/candidate pair."""
    observation = propagation_to_tracking_observation(
        observation_propagation,
        observation_id=observation_id,
        track_id=track_id,
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        data_source=data_source,
        measurement_quality=measurement_quality,
        position_covariance_km2=observation_position_covariance_km2,
        velocity_covariance_km2_s2=(
            observation_velocity_covariance_km2_s2
        ),
    )
    catalog, orbital, affiliation_record = (
        propagation_to_candidate_records(
            candidate_propagation,
            catalog_source=catalog_source,
            object_type=object_type,
            affiliation=affiliation,
            affiliation_authority=affiliation_authority,
            affiliation_source_record_id=affiliation_source_record_id,
            designation_status=designation_status,
            canonical_object_id=canonical_object_id,
            position_covariance_km2=candidate_position_covariance_km2,
            velocity_covariance_km2_s2=(
                candidate_velocity_covariance_km2_s2
            ),
        )
    )
    prepared = prepare_identification_input(
        observation,
        catalog,
        orbital,
        affiliation_record,
    )
    return {
        "observation": observation,
        "catalog": catalog,
        "orbital": orbital,
        "affiliation": affiliation_record,
        "prepared": prepared,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectIdentificationInputError(
            f"unable to read propagation JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ObjectIdentificationInputError(
            f"propagation JSON must contain one object: {path}"
        )
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert data_gen propagation JSON into validated "
            "object-identification records."
        )
    )
    parser.add_argument("--observation-input", type=Path, required=True)
    parser.add_argument("--candidate-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--track-id", required=True)
    parser.add_argument("--sensor-id", required=True)
    parser.add_argument(
        "--sensor-type",
        choices=["radar", "optical", "space_based", "fused", "other"],
        required=True,
    )
    parser.add_argument("--data-source", required=True)
    parser.add_argument(
        "--measurement-quality",
        type=float,
        required=True,
    )
    parser.add_argument("--catalog-source", required=True)
    parser.add_argument(
        "--object-type",
        choices=["payload", "rocket_body", "debris", "unknown"],
        required=True,
    )
    parser.add_argument(
        "--affiliation",
        choices=["blue", "red", "other"],
        required=True,
    )
    parser.add_argument("--affiliation-authority", required=True)
    parser.add_argument("--affiliation-source-record-id", required=True)
    parser.add_argument("--canonical-object-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        records = build_identification_records(
            _load_json(args.observation_input),
            _load_json(args.candidate_input),
            observation_id=args.observation_id,
            track_id=args.track_id,
            sensor_id=args.sensor_id,
            sensor_type=args.sensor_type,
            data_source=args.data_source,
            measurement_quality=args.measurement_quality,
            catalog_source=args.catalog_source,
            object_type=args.object_type,
            affiliation=args.affiliation,
            affiliation_authority=args.affiliation_authority,
            affiliation_source_record_id=(
                args.affiliation_source_record_id
            ),
            canonical_object_id=args.canonical_object_id,
        )
    except ObjectIdentificationInputError as exc:
        print(f"Data-generation adapter error: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Identification records written to: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
