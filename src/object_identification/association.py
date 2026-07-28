"""Transparent prototype catalog-association scoring.

The score is an uncalibrated similarity value, not a probability. Operational
scales and thresholds require evaluation on representative labeled data.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .input_pipeline import (
    ObjectIdentificationInputError,
    REPOSITORY_ROOT,
    prepare_identification_input_from_files,
)


DEFAULT_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "object-identification-association.json"
)
PREDICTION_SCHEMA_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "requirements"
    / "object_identification"
    / "object-identification-prediction.schema.json"
)


@dataclass(frozen=True)
class AssociationConfig:
    version: str
    validation_status: str
    position_scale_km: float
    velocity_scale_km_s: float
    match_threshold: float


def load_association_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> AssociationConfig:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectIdentificationInputError(
            f"unable to load association config: {source}"
        ) from exc
    required = {
        "version",
        "validation_status",
        "position_scale_km",
        "velocity_scale_km_s",
        "match_threshold",
    }
    missing = sorted(required - set(value)) if isinstance(value, dict) else []
    if not isinstance(value, dict) or missing:
        raise ObjectIdentificationInputError(
            f"association config missing fields: {missing or sorted(required)}"
        )
    if set(value) != required:
        raise ObjectIdentificationInputError(
            "association config contains unexpected fields"
        )
    if value["validation_status"] not in {
        "prototype_unvalidated",
        "operationally_validated",
    }:
        raise ObjectIdentificationInputError(
            "association config has unsupported validation_status"
        )
    for field in ("position_scale_km", "velocity_scale_km_s"):
        if not isinstance(value[field], (int, float)) or value[field] <= 0:
            raise ObjectIdentificationInputError(
                f"association config {field} must be greater than zero"
            )
    threshold = value["match_threshold"]
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ObjectIdentificationInputError(
            "association config match_threshold must be between zero and one"
        )
    if not isinstance(value["version"], str) or not value["version"]:
        raise ObjectIdentificationInputError(
            "association config version must be a non-empty string"
        )
    return AssociationConfig(
        version=value["version"],
        validation_status=value["validation_status"],
        position_scale_km=float(value["position_scale_km"]),
        velocity_scale_km_s=float(value["velocity_scale_km_s"]),
        match_threshold=float(threshold),
    )


def vector_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def calculate_association_score(
    prepared: dict[str, Any],
    config: AssociationConfig,
) -> dict[str, float]:
    """Calculate residuals and an uncalibrated similarity score."""
    observation = prepared["observation"]
    orbital = prepared["orbital_state"]
    position_residual = vector_distance(
        observation["position_km"], orbital["position_km"]
    )
    velocity_residual = vector_distance(
        observation["velocity_km_s"], orbital["velocity_km_s"]
    )
    normalized_distance_squared = (
        position_residual / config.position_scale_km
    ) ** 2 + (
        velocity_residual / config.velocity_scale_km_s
    ) ** 2
    geometric_similarity = math.exp(-0.5 * normalized_distance_squared)
    score = geometric_similarity * observation["measurement_quality"]
    return {
        "position_residual_km": position_residual,
        "velocity_residual_km_s": velocity_residual,
        "geometric_similarity": geometric_similarity,
        "measurement_quality": observation["measurement_quality"],
        "match_score": max(0.0, min(1.0, score)),
    }


def build_prediction(
    prepared: dict[str, Any],
    config: AssociationConfig,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Score one candidate and build a schema-valid prediction record."""
    metrics = calculate_association_score(prepared, config)
    candidate = prepared["candidate"]
    observation = prepared["observation"]
    is_known = metrics["match_score"] >= config.match_threshold
    affiliation = candidate["affiliation"] if is_known else "unknown"
    classification = f"known_{affiliation}" if is_known else "unknown"

    created = generated_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        raise ObjectIdentificationInputError(
            "generated_at must be timezone-aware"
        )

    prediction = {
        "schema_version": "0.1.0",
        "contract_version": "0.1.0",
        "record_id": f"OID-{observation['observation_id']}",
        "generated_at": created.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "observation_id": observation["observation_id"],
        "observation_timestamp": observation["timestamp"],
        "canonical_object_id": (
            candidate["canonical_object_id"] if is_known else None
        ),
        "identity_status": "known" if is_known else "unknown",
        "affiliation": affiliation,
        "classification": classification,
        "match_score": metrics["match_score"],
        "match_score_interpretation": (
            "uncalibrated_position_velocity_similarity_times_measurement_quality"
        ),
        "threshold": {
            "value": config.match_threshold,
            "version": config.version,
            "validation_status": config.validation_status,
        },
        "catalog_provenance": (
            {
                "catalog_source": candidate["catalog_source"],
                "catalog_record_id": candidate["catalog_record_id"],
                "catalog_record_valid_at": observation["timestamp"],
            }
            if is_known
            else None
        ),
        "affiliation_provenance": (
            {
                "affiliation_authority": candidate["affiliation_authority"],
                "affiliation_source_record_id": candidate[
                    "affiliation_source_record_id"
                ],
                "affiliation_effective_at": candidate[
                    "affiliation_effective_at"
                ],
                "affiliation_expires_at": candidate[
                    "affiliation_expires_at"
                ],
            }
            if is_known
            else None
        ),
        "matching_method": {
            "name": "position-velocity-gaussian-similarity",
            "version": config.version,
            "method_type": "similarity",
        },
        "data_quality": {
            "status": "complete",
            "issues": [],
        },
        "rationale": [
            (
                f"Position residual: {metrics['position_residual_km']:.6f} km."
            ),
            (
                "Velocity residual: "
                f"{metrics['velocity_residual_km_s']:.6f} km/s."
            ),
            (
                f"Match score {metrics['match_score']:.6f} "
                f"{'>=' if is_known else '<'} prototype threshold "
                f"{config.match_threshold:.6f}."
            ),
        ],
        "artifact_metadata": {
            "name": "prototype-catalog-association-rule",
            "version": config.version,
            "training_data_designation": "not_applicable",
        },
        "use_designation": "prototype_non_operational",
    }
    validate_prediction(prediction)
    return prediction


def validate_prediction(prediction: dict[str, Any]) -> None:
    schema = json.loads(PREDICTION_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    errors = list(validator.iter_errors(prediction))
    if errors:
        details = " | ".join(error.message for error in errors)
        raise ObjectIdentificationInputError(
            f"generated prediction failed schema validation: {details}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run prototype object-to-catalog association."
    )
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--orbital", type=Path, required=True)
    parser.add_argument("--affiliation", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output", type=Path)
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
        prediction = build_prediction(
            prepared,
            load_association_config(args.config),
        )
    except ObjectIdentificationInputError as exc:
        print(f"Object-identification association error: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(prediction, indent=2)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Prediction written to: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
