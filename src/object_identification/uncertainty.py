"""Transparent prototype uncertainty estimates for generated orbital data."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from .input_pipeline import ObjectIdentificationInputError


DEFAULT_UNCERTAINTY_CONFIG_PATH = files(__package__).joinpath(
    "config", "object-identification-uncertainty.json"
)
COVARIANCE_FIELDS = (
    "position_covariance_km2",
    "velocity_covariance_km2_s2",
)


def _positive_number(value: Any, field: str) -> float:
    try:
        rendered = float(value)
    except (TypeError, ValueError) as exc:
        raise ObjectIdentificationInputError(
            f"uncertainty config {field} must be a positive number"
        ) from exc
    if not math.isfinite(rendered) or rendered <= 0:
        raise ObjectIdentificationInputError(
            f"uncertainty config {field} must be a positive number"
        )
    return rendered


def load_uncertainty_config(
    path: Any = DEFAULT_UNCERTAINTY_CONFIG_PATH,
) -> dict[str, Any]:
    source = path if hasattr(path, "read_text") else Path(path)
    try:
        config = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectIdentificationInputError(
            f"unable to load uncertainty config: {source}"
        ) from exc
    if not isinstance(config, dict):
        raise ObjectIdentificationInputError(
            "uncertainty config must contain one object"
        )
    if config.get("validation_status") != "prototype_unvalidated":
        raise ObjectIdentificationInputError(
            "uncertainty config must be designated prototype_unvalidated"
        )
    if not isinstance(config.get("version"), str) or not config["version"]:
        raise ObjectIdentificationInputError(
            "uncertainty config version is required"
        )
    profiles = config.get("sensor_profiles")
    required_profiles = {
        "radar",
        "optical",
        "space_based",
        "fused",
        "other",
    }
    if not isinstance(profiles, dict) or set(profiles) != required_profiles:
        raise ObjectIdentificationInputError(
            "uncertainty config must define every supported sensor profile"
        )
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ObjectIdentificationInputError(
                f"uncertainty config sensor profile {name} must be an object"
            )
        _positive_number(
            profile.get("position_sigma_km"),
            f"sensor_profiles.{name}.position_sigma_km",
        )
        _positive_number(
            profile.get("velocity_sigma_km_s"),
            f"sensor_profiles.{name}.velocity_sigma_km_s",
        )
    quality_floor = _positive_number(
        config.get("measurement_quality_floor"),
        "measurement_quality_floor",
    )
    if quality_floor > 1:
        raise ObjectIdentificationInputError(
            "uncertainty config measurement_quality_floor must be <= 1"
        )
    catalog = config.get("sgp4_catalog_profile")
    if not isinstance(catalog, dict):
        raise ObjectIdentificationInputError(
            "uncertainty config sgp4_catalog_profile must be an object"
        )
    for field in (
        "base_position_sigma_km",
        "base_velocity_sigma_km_s",
        "position_sigma_growth_km_per_hour",
        "velocity_sigma_growth_km_s_per_hour",
    ):
        _positive_number(catalog.get(field), f"sgp4_catalog_profile.{field}")
    return config


def _diagonal_covariance(sigma: float) -> list[list[float]]:
    variance = sigma**2
    return [
        [variance, 0.0, 0.0],
        [0.0, variance, 0.0],
        [0.0, 0.0, variance],
    ]


def _propagation_datetime(propagation: dict[str, Any]) -> datetime:
    try:
        value = propagation["time"]
        seconds = float(value["second"])
        if not math.isfinite(seconds) or not 0 <= seconds < 60:
            raise ValueError("seconds outside supported range")
        return datetime(
            int(value["year"]),
            int(value["month"]),
            int(value["day"]),
            int(value["hour"]),
            int(value["minute"]),
            tzinfo=timezone.utc,
        ) + timedelta(seconds=seconds)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ObjectIdentificationInputError(
            "propagation.time must contain a valid UTC date and time"
        ) from exc


def estimate_observation_covariance(
    *,
    sensor_type: str,
    measurement_quality: float,
    config: dict[str, Any],
) -> dict[str, list[list[float]]]:
    """Estimate diagonal sensor covariance from a configured profile."""
    try:
        profile = config["sensor_profiles"][sensor_type]
    except KeyError as exc:
        raise ObjectIdentificationInputError(
            f"no uncertainty profile for sensor type: {sensor_type}"
        ) from exc
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
    quality_floor = float(config["measurement_quality_floor"])
    effective_quality = max(quality, quality_floor)
    position_sigma = float(profile["position_sigma_km"]) / effective_quality
    velocity_sigma = (
        float(profile["velocity_sigma_km_s"]) / effective_quality
    )
    return {
        "position_covariance_km2": _diagonal_covariance(position_sigma),
        "velocity_covariance_km2_s2": _diagonal_covariance(velocity_sigma),
    }


def estimate_candidate_covariance(
    *,
    observation_propagation: dict[str, Any],
    candidate_propagation: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, list[list[float]]], float]:
    """Estimate diagonal SGP4 covariance with linear sigma growth by age."""
    observed_at = _propagation_datetime(observation_propagation)
    candidate_at = _propagation_datetime(candidate_propagation)
    age_hours = max(0.0, (observed_at - candidate_at).total_seconds() / 3600)
    profile = config["sgp4_catalog_profile"]
    position_sigma = float(
        profile["base_position_sigma_km"]
    ) + age_hours * float(
        profile["position_sigma_growth_km_per_hour"]
    )
    velocity_sigma = float(
        profile["base_velocity_sigma_km_s"]
    ) + age_hours * float(
        profile["velocity_sigma_growth_km_s_per_hour"]
    )
    return (
        {
            "position_covariance_km2": _diagonal_covariance(
                position_sigma
            ),
            "velocity_covariance_km2_s2": _diagonal_covariance(
                velocity_sigma
            ),
        },
        age_hours,
    )


def apply_uncertainty_model(
    observation_propagation: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    sensor_type: str,
    measurement_quality: float,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Fill only missing covariance and return explicit provenance."""
    observation = deepcopy(observation_propagation)
    modeled_observation = estimate_observation_covariance(
        sensor_type=sensor_type,
        measurement_quality=measurement_quality,
        config=config,
    )
    observation_sources: dict[str, str] = {}
    for field in COVARIANCE_FIELDS:
        if field in observation:
            observation_sources[field] = "supplied"
        else:
            observation[field] = modeled_observation[field]
            observation_sources[field] = "modeled"

    modeled_candidates: list[dict[str, Any]] = []
    candidate_assurance: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_copy = deepcopy(candidate)
        propagation = candidate_copy.get("propagation")
        if not isinstance(propagation, dict):
            raise ObjectIdentificationInputError(
                f"candidate {index}.propagation must be an object"
            )
        estimates, age_hours = estimate_candidate_covariance(
            observation_propagation=observation,
            candidate_propagation=propagation,
            config=config,
        )
        sources: dict[str, str] = {}
        for field in COVARIANCE_FIELDS:
            if field in propagation:
                sources[field] = "supplied"
            else:
                propagation[field] = estimates[field]
                sources[field] = "modeled"
        modeled_candidates.append(candidate_copy)
        candidate_assurance.append(
            {
                "candidate_index": index,
                "catalog": propagation.get("catalog"),
                "propagation_age_hours": age_hours,
                "covariance_sources": sources,
            }
        )

    all_sources = list(observation_sources.values())
    for item in candidate_assurance:
        all_sources.extend(item["covariance_sources"].values())
    if all(source == "supplied" for source in all_sources):
        mode = "supplied"
    elif all(source == "modeled" for source in all_sources):
        mode = "modeled"
    else:
        mode = "mixed"

    assurance = {
        "mode": mode,
        "model_name": "configured-diagonal-prototype-uncertainty",
        "model_version": config["version"],
        "validation_status": config["validation_status"],
        "observation_covariance_sources": observation_sources,
        "candidate_covariance": candidate_assurance,
        "assumptions": [
            "Sensor covariance is diagonal and scaled inversely by "
            "measurement quality.",
            "SGP4 catalog sigma grows linearly with propagation age.",
            "Configured values are prototype assumptions, not calibrated "
            "operational uncertainty.",
        ],
    }
    return observation, modeled_candidates, assurance
