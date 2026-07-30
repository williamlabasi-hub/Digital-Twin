"""Deterministic prototype closest-approach geometry using linear motion."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .probability import (
    RISK_THRESHOLD_VERSION,
    ProbabilityUnavailable,
    compute_collision_probability,
)
from .validation import (
    ConjunctionInputError,
    OUTPUT_SCHEMA_PATH,
    parse_timestamp,
    validate_conjunction_input,
    validate_schema,
)


ARTIFACT_NAME = "prototype-collision-risk-assessor"
ARTIFACT_VERSION = "prototype-0.1"


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _vector_subtract(left: list[float], right: list[float]) -> list[float]:
    return [float(a) - float(b) for a, b in zip(left, right)]


def _vector_add_scaled(
    position: list[float],
    velocity: list[float],
    seconds: float,
) -> list[float]:
    return [
        float(position[index]) + float(velocity[index]) * seconds
        for index in range(3)
    ]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _norm(vector: list[float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _combined_hard_body_radius(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
) -> float | None:
    first = primary.get("hard_body_radius_m")
    second = secondary.get("hard_body_radius_m")
    if first is None or second is None:
        return None
    return float(first) + float(second)


def _uncertainty_status(record: Mapping[str, Any]) -> tuple[str, str | None]:
    primary = record["primary"]
    secondary = record["secondary"]
    if (
        primary.get("state_covariance") is not None
        and secondary.get("state_covariance") is not None
    ):
        return "covariance_available", primary["coordinate_frame"]
    return "missing_covariance", None


def _abstained_assessment(
    record: Mapping[str, Any],
    error: ConjunctionInputError,
    generated_at: datetime,
) -> dict[str, Any]:
    uncertainty_status, covariance_frame = _uncertainty_status(record)
    if error.code.startswith("COVARIANCE_"):
        uncertainty_status = "invalid_covariance"
        covariance_frame = None
    result = {
        "schema_version": "0.1.0",
        "contract_version": "0.1.0",
        "assessment_id": f"CRA-{record['request_id']}",
        "request_id": record["request_id"],
        "generated_at": _iso_utc(generated_at),
        "assessment_status": "abstained",
        "primary_object_id": record["primary"]["object_id"],
        "secondary_object_id": record["secondary"]["object_id"],
        "closest_approach": None,
        "probability": {
            "status": "unavailable",
            "collision_probability": None,
            "method": None,
            "hard_body_radius_m": _combined_hard_body_radius(
                record["primary"], record["secondary"]
            ),
            "interpretation": (
                "Unavailable because the conjunction input was not accepted."
            ),
        },
        "risk": {
            "level": "undetermined",
            "basis": "Closest-approach assessment abstained.",
            "threshold_version": None,
        },
        "uncertainty_assurance": {
            "status": uncertainty_status,
            "covariance_frame": covariance_frame,
            "assumptions": [],
        },
        "data_quality": {
            "status": "invalid",
            "issues": [
                {
                    "code": error.code,
                    "severity": "error",
                    "message": str(error),
                }
            ],
        },
        "abstention_reason": error.code.lower(),
        "rationale": [
            "No collision-risk claim was produced from rejected inputs."
        ],
        "artifact_metadata": {
            "name": ARTIFACT_NAME,
            "version": ARTIFACT_VERSION,
            "validation_status": "prototype_unvalidated",
        },
        "use_designation": "prototype_non_operational",
    }
    validate_schema(result, OUTPUT_SCHEMA_PATH)
    return result


def assess_closest_approach(
    record: Mapping[str, Any],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return geometry-only evidence or an explicit semantic abstention."""

    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ConjunctionInputError(
            "GENERATED_AT_TIMEZONE_MISSING",
            "generated_at requires a timezone.",
        )
    try:
        validate_conjunction_input(record)
    except ConjunctionInputError as error:
        if error.code == "SCHEMA_VALIDATION_FAILED":
            raise
        return _abstained_assessment(record, error, generated_at)

    primary = record["primary"]
    secondary = record["secondary"]
    epoch = parse_timestamp(primary["epoch"], "primary.epoch")
    window_start = parse_timestamp(
        record["analysis_window"]["start"], "analysis_window.start"
    )
    window_end = parse_timestamp(
        record["analysis_window"]["end"], "analysis_window.end"
    )
    lower_seconds = (window_start - epoch).total_seconds()
    upper_seconds = (window_end - epoch).total_seconds()

    relative_position = _vector_subtract(
        secondary["position_km"], primary["position_km"]
    )
    relative_velocity = _vector_subtract(
        secondary["velocity_km_s"], primary["velocity_km_s"]
    )
    speed_squared = _dot(relative_velocity, relative_velocity)
    if speed_squared <= 1e-24:
        tca_seconds = lower_seconds
        tca_was_clamped = False
    else:
        unconstrained_tca = -_dot(
            relative_position, relative_velocity
        ) / speed_squared
        tca_was_clamped = (
            unconstrained_tca < lower_seconds
            or unconstrained_tca > upper_seconds
        )
        tca_seconds = min(max(unconstrained_tca, lower_seconds), upper_seconds)

    relative_at_tca = _vector_add_scaled(
        relative_position, relative_velocity, tca_seconds
    )
    miss_distance = _norm(relative_at_tca)
    relative_speed = _norm(relative_velocity)
    tca = epoch + timedelta(seconds=tca_seconds)

    uncertainty_status, covariance_frame = _uncertainty_status(record)
    issues = []
    try:
        if tca_was_clamped:
            raise ProbabilityUnavailable(
                "ENCOUNTER_OUTSIDE_ANALYSIS_WINDOW",
                (
                    "Collision probability is withheld because unconstrained "
                    "closest approach lies outside the analysis window."
                ),
            )
        probability_evidence = compute_collision_probability(
            primary,
            secondary,
            relative_at_tca,
            relative_velocity,
            tca_seconds,
        )
    except ProbabilityUnavailable as error:
        probability_evidence = None
        issues.append(
            {
                "code": error.code,
                "severity": "warning",
                "message": str(error),
            }
        )

    if probability_evidence is None:
        assessment_status = "geometric_only"
        probability = {
            "status": "unavailable",
            "collision_probability": None,
            "method": None,
            "hard_body_radius_m": _combined_hard_body_radius(
                primary, secondary
            ),
            "interpretation": (
                "Not computed because required encounter evidence was "
                "unavailable."
            ),
        }
        risk = {
            "level": "undetermined",
            "basis": "Collision probability is unavailable.",
            "threshold_version": None,
        }
        data_quality_status = "degraded"
        probability_rationale = (
            "Collision probability and risk level were intentionally withheld."
        )
    else:
        assessment_status = "complete"
        probability_value = probability_evidence["collision_probability"]
        probability = {
            "status": "computed",
            "collision_probability": probability_value,
            "method": probability_evidence["method"],
            "hard_body_radius_m": probability_evidence[
                "hard_body_radius_m"
            ],
            "interpretation": (
                "Prototype uncalibrated encounter-plane collision probability."
            ),
        }
        risk = {
            "level": probability_evidence["risk_level"],
            "basis": "Prototype collision-probability threshold.",
            "threshold_version": RISK_THRESHOLD_VERSION,
        }
        uncertainty_status = "combined_covariance"
        covariance_frame = "encounter_plane"
        data_quality_status = "complete"
        probability_rationale = (
            f"Prototype collision probability is {probability_value:.12g}; "
            f"risk level is {probability_evidence['risk_level']}."
        )

    result = {
        "schema_version": "0.1.0",
        "contract_version": "0.1.0",
        "assessment_id": f"CRA-{record['request_id']}",
        "request_id": record["request_id"],
        "generated_at": _iso_utc(generated_at),
        "assessment_status": assessment_status,
        "primary_object_id": primary["object_id"],
        "secondary_object_id": secondary["object_id"],
        "closest_approach": {
            "time_of_closest_approach": _iso_utc(tca),
            "miss_distance_km": miss_distance,
            "relative_velocity_km_s": relative_speed,
            "relative_position_km": relative_at_tca,
            "relative_velocity_vector_km_s": relative_velocity,
            "method": {
                "name": "linear-relative-motion",
                "version": ARTIFACT_VERSION,
            },
        },
        "probability": probability,
        "risk": risk,
        "uncertainty_assurance": {
            "status": uncertainty_status,
            "covariance_frame": covariance_frame,
            "assumptions": [
                "Object motion is linear over the bounded analysis window.",
                "Both state vectors share one epoch and coordinate frame.",
                "Primary and secondary state errors are independent.",
                (
                    "Cartesian covariance is propagated to closest approach "
                    "with a constant-velocity transition."
                ),
            ],
        },
        "data_quality": {
            "status": data_quality_status,
            "issues": issues,
        },
        "abstention_reason": None,
        "rationale": [
            f"Closest approach occurs {tca_seconds:.6f} seconds after the state epoch.",
            f"Prototype miss distance is {miss_distance:.9f} km.",
            probability_rationale,
        ],
        "artifact_metadata": {
            "name": ARTIFACT_NAME,
            "version": ARTIFACT_VERSION,
            "validation_status": "prototype_unvalidated",
        },
        "use_designation": "prototype_non_operational",
    }
    validate_schema(result, OUTPUT_SCHEMA_PATH)
    return result
