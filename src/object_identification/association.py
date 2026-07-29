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
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .input_pipeline import (
    ObjectIdentificationInputError,
    prepare_identification_input_from_files,
)


PACKAGE_ROOT = files(__package__)
DEFAULT_CONFIG_PATH = PACKAGE_ROOT.joinpath(
    "config", "object-identification-association.json"
)
PREDICTION_SCHEMA_PATH = PACKAGE_ROOT.joinpath(
    "schemas", "object-identification-prediction.schema.json"
)


@dataclass(frozen=True)
class AssociationConfig:
    version: str
    validation_status: str
    position_scale_km: float
    velocity_scale_km_s: float
    match_threshold: float
    ambiguity_margin: float
    max_ranked_candidates: int


def load_association_config(
    path: Any = DEFAULT_CONFIG_PATH,
) -> AssociationConfig:
    source = path if hasattr(path, "read_text") else Path(path)
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
        "ambiguity_margin",
        "max_ranked_candidates",
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
    ambiguity_margin = value["ambiguity_margin"]
    if (
        not isinstance(ambiguity_margin, (int, float))
        or not 0 <= ambiguity_margin <= 1
    ):
        raise ObjectIdentificationInputError(
            "association config ambiguity_margin must be between zero and one"
        )
    max_ranked_candidates = value["max_ranked_candidates"]
    if (
        not isinstance(max_ranked_candidates, int)
        or isinstance(max_ranked_candidates, bool)
        or max_ranked_candidates < 1
    ):
        raise ObjectIdentificationInputError(
            "association config max_ranked_candidates must be a positive integer"
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
        ambiguity_margin=float(ambiguity_margin),
        max_ranked_candidates=max_ranked_candidates,
    )


def vector_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _combined_covariance(
    left: list[list[float]],
    right: list[list[float]],
) -> list[list[float]]:
    return [
        [left[row][column] + right[row][column] for column in range(3)]
        for row in range(3)
    ]


def _mahalanobis_squared(
    residual: list[float],
    covariance: list[list[float]],
) -> float:
    """Calculate r.T @ covariance^-1 @ r using Cholesky decomposition."""
    lower = [[0.0] * 3 for _ in range(3)]
    for row in range(3):
        for column in range(row + 1):
            value = covariance[row][column] - sum(
                lower[row][index] * lower[column][index]
                for index in range(column)
            )
            if row == column:
                if value <= 0:
                    raise ObjectIdentificationInputError(
                        "combined covariance must be positive definite"
                    )
                lower[row][column] = math.sqrt(value)
            else:
                lower[row][column] = value / lower[column][column]
    whitened = [0.0] * 3
    for row in range(3):
        whitened[row] = (
            residual[row]
            - sum(
                lower[row][column] * whitened[column]
                for column in range(row)
            )
        ) / lower[row][row]
    return sum(value * value for value in whitened)


def calculate_association_score(
    prepared: dict[str, Any],
    config: AssociationConfig,
) -> dict[str, Any]:
    """Calculate residuals and an uncalibrated similarity score."""
    observation = prepared["observation"]
    orbital = prepared["orbital_state"]
    position_residual = vector_distance(
        observation["position_km"], orbital["position_km"]
    )
    velocity_residual = vector_distance(
        observation["velocity_km_s"], orbital["velocity_km_s"]
    )
    position_delta = [
        observed - expected
        for observed, expected in zip(
            observation["position_km"],
            orbital["position_km"],
            strict=True,
        )
    ]
    velocity_delta = [
        observed - expected
        for observed, expected in zip(
            observation["velocity_km_s"],
            orbital["velocity_km_s"],
            strict=True,
        )
    ]
    covariance_fields = (
        observation.get("position_covariance_km2"),
        observation.get("velocity_covariance_km2_s2"),
        orbital.get("position_covariance_km2"),
        orbital.get("velocity_covariance_km2_s2"),
    )
    if all(matrix is not None for matrix in covariance_fields):
        (
            observation_position_covariance,
            observation_velocity_covariance,
            orbital_position_covariance,
            orbital_velocity_covariance,
        ) = covariance_fields
        normalized_distance_squared = _mahalanobis_squared(
            position_delta,
            _combined_covariance(
                observation_position_covariance,
                orbital_position_covariance,
            ),
        ) + _mahalanobis_squared(
            velocity_delta,
            _combined_covariance(
                observation_velocity_covariance,
                orbital_velocity_covariance,
            ),
        )
        scoring_method = "combined-covariance-mahalanobis-similarity"
        uncertainty_status = "combined_covariance"
    else:
        normalized_distance_squared = (
            position_residual / config.position_scale_km
        ) ** 2 + (
            velocity_residual / config.velocity_scale_km_s
        ) ** 2
        scoring_method = "position-velocity-gaussian-similarity"
        uncertainty_status = "scale_fallback"
    geometric_similarity = math.exp(-0.5 * normalized_distance_squared)
    score = geometric_similarity * observation["measurement_quality"]
    return {
        "position_residual_km": position_residual,
        "velocity_residual_km_s": velocity_residual,
        "geometric_similarity": geometric_similarity,
        "measurement_quality": observation["measurement_quality"],
        "match_score": max(0.0, min(1.0, score)),
        "normalized_distance_squared": normalized_distance_squared,
        "scoring_method": scoring_method,
        "uncertainty_status": uncertainty_status,
    }


def build_prediction(
    prepared: dict[str, Any],
    config: AssociationConfig,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Score one candidate and build a schema-valid prediction record."""
    return build_ranked_prediction(
        [prepared],
        config,
        generated_at=generated_at,
    )


def build_ranked_prediction(
    prepared_candidates: list[dict[str, Any]],
    config: AssociationConfig,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Rank candidates and build a prediction with an ambiguity-safe decision."""
    if not prepared_candidates:
        raise ObjectIdentificationInputError(
            "at least one prepared candidate is required"
        )

    observation = prepared_candidates[0]["observation"]
    observation_id = observation["observation_id"]
    observation_timestamp = observation["timestamp"]
    scored: list[tuple[dict[str, Any], dict[str, float]]] = []
    seen_candidate_ids: set[str] = set()
    for prepared in prepared_candidates:
        current_observation = prepared["observation"]
        if (
            current_observation["observation_id"] != observation_id
            or current_observation["timestamp"] != observation_timestamp
        ):
            raise ObjectIdentificationInputError(
                "all candidates must be prepared for the same observation"
            )
        candidate_id = prepared["candidate"]["canonical_object_id"]
        if candidate_id in seen_candidate_ids:
            raise ObjectIdentificationInputError(
                f"duplicate candidate canonical_object_id: {candidate_id}"
            )
        seen_candidate_ids.add(candidate_id)
        scored.append(
            (prepared, calculate_association_score(prepared, config))
        )

    scored.sort(
        key=lambda item: (
            -item[1]["match_score"],
            item[0]["candidate"]["canonical_object_id"],
        )
    )
    best_prepared, best_metrics = scored[0]
    best_candidate = best_prepared["candidate"]
    second_score = scored[1][1]["match_score"] if len(scored) > 1 else None
    score_gap = (
        best_metrics["match_score"] - second_score
        if second_score is not None
        else None
    )
    above_threshold = best_metrics["match_score"] >= config.match_threshold
    ambiguous = bool(
        above_threshold
        and len(scored) > 1
        and second_score is not None
        and second_score >= config.match_threshold
        and score_gap is not None
        and score_gap <= config.ambiguity_margin
    )
    is_known = above_threshold and not ambiguous
    if ambiguous:
        decision_basis = "ambiguous"
    elif is_known:
        decision_basis = "clear_match"
    else:
        decision_basis = "no_candidate_above_threshold"
    affiliation = best_candidate["affiliation"] if is_known else "unknown"
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
            best_candidate["canonical_object_id"] if is_known else None
        ),
        "identity_status": "known" if is_known else "unknown",
        "affiliation": affiliation,
        "classification": classification,
        "match_score": best_metrics["match_score"],
        "match_score_interpretation": (
            "uncalibrated_"
            f"{best_metrics['scoring_method'].replace('-', '_')}"
            "_times_measurement_quality"
        ),
        "threshold": {
            "value": config.match_threshold,
            "version": config.version,
            "validation_status": config.validation_status,
        },
        "catalog_provenance": (
            {
                "catalog_source": best_candidate["catalog_source"],
                "catalog_record_id": best_candidate["catalog_record_id"],
                "catalog_record_valid_at": observation["timestamp"],
            }
            if is_known
            else None
        ),
        "affiliation_provenance": (
            {
                "affiliation_authority": best_candidate[
                    "affiliation_authority"
                ],
                "affiliation_source_record_id": best_candidate[
                    "affiliation_source_record_id"
                ],
                "affiliation_effective_at": best_candidate[
                    "affiliation_effective_at"
                ],
                "affiliation_expires_at": best_candidate[
                    "affiliation_expires_at"
                ],
            }
            if is_known
            else None
        ),
        "matching_method": {
            "name": best_metrics["scoring_method"],
            "version": config.version,
            "method_type": "similarity",
        },
        "candidate_selection": {
            "decision_basis": decision_basis,
            "candidate_count": len(scored),
            "ambiguity_margin": config.ambiguity_margin,
            "best_to_second_score_gap": score_gap,
        },
        "candidate_rankings": [
            {
                "rank": rank,
                "canonical_object_id": prepared["candidate"][
                    "canonical_object_id"
                ],
                "affiliation": prepared["candidate"]["affiliation"],
                "match_score": metrics["match_score"],
                "meets_threshold": (
                    metrics["match_score"] >= config.match_threshold
                ),
                "position_residual_km": metrics["position_residual_km"],
                "velocity_residual_km_s": metrics[
                    "velocity_residual_km_s"
                ],
                "normalized_distance_squared": metrics[
                    "normalized_distance_squared"
                ],
                "scoring_method": metrics["scoring_method"],
                "uncertainty_status": metrics["uncertainty_status"],
                "catalog_provenance": {
                    "catalog_source": prepared["candidate"]["catalog_source"],
                    "catalog_record_id": prepared["candidate"][
                        "catalog_record_id"
                    ],
                    "catalog_record_valid_at": observation["timestamp"],
                },
            }
            for rank, (prepared, metrics) in enumerate(
                scored[: config.max_ranked_candidates],
                start=1,
            )
        ],
        "data_quality": {
            "status": "complete",
            "issues": [],
        },
        "rationale": [
            (
                "Best-candidate position residual: "
                f"{best_metrics['position_residual_km']:.6f} km."
            ),
            (
                "Velocity residual: "
                f"{best_metrics['velocity_residual_km_s']:.6f} km/s."
            ),
            (
                f"Scoring method: {best_metrics['scoring_method']} "
                f"({best_metrics['uncertainty_status']})."
            ),
            (
                f"Best match score {best_metrics['match_score']:.6f} "
                f"{'>=' if above_threshold else '<'} prototype threshold "
                f"{config.match_threshold:.6f}."
            ),
            (
                "Identity withheld because multiple candidates are within the "
                f"{config.ambiguity_margin:.6f} ambiguity margin."
                if ambiguous
                else f"Candidate-selection decision: {decision_basis}."
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
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--orbital", type=Path)
    parser.add_argument("--affiliation", type=Path)
    parser.add_argument(
        "--candidate",
        nargs=3,
        action="append",
        metavar=("CATALOG", "ORBITAL", "AFFILIATION"),
        type=Path,
        help=(
            "Candidate evidence triplet; repeat to rank multiple candidates. "
            "Cannot be combined with the legacy single-candidate flags."
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        legacy_paths = (args.catalog, args.orbital, args.affiliation)
        if args.candidate and any(path is not None for path in legacy_paths):
            raise ObjectIdentificationInputError(
                "--candidate cannot be combined with --catalog, --orbital, "
                "or --affiliation"
            )
        if args.candidate:
            candidate_paths = args.candidate
        elif all(path is not None for path in legacy_paths):
            candidate_paths = [legacy_paths]
        else:
            raise ObjectIdentificationInputError(
                "provide either repeated --candidate groups or all of "
                "--catalog, --orbital, and --affiliation"
            )
        prepared_candidates = [
            prepare_identification_input_from_files(
                args.observation,
                catalog_path,
                orbital_path,
                affiliation_path,
            )
            for catalog_path, orbital_path, affiliation_path in candidate_paths
        ]
        prediction = build_ranked_prediction(
            prepared_candidates,
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
