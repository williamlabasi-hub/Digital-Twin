"""Prototype encounter-plane collision probability and risk classification."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr


PROBABILITY_METHOD_NAME = "prototype-2d-encounter-plane-gaussian"
PROBABILITY_METHOD_VERSION = "prototype-0.2"
RISK_THRESHOLD_VERSION = "prototype-0.1"
MIN_RELATIVE_SPEED_KM_S = 1e-12
STANDARD_NORMAL_LIMIT = 12.0

# Ordered from most severe to least severe. These thresholds are transparent
# prototype assumptions and are not operational maneuver criteria.
RISK_THRESHOLDS = (
    ("critical", 1e-2),
    ("high", 1e-3),
    ("moderate", 1e-4),
    ("low", 1e-6),
)


class ProbabilityUnavailable(ValueError):
    """Collision probability cannot be supported by the supplied evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _propagated_position_covariance(
    state_covariance: list[list[float]],
    seconds: float,
) -> np.ndarray:
    covariance = np.asarray(state_covariance, dtype=float)
    position = covariance[:3, :3]
    position_velocity = covariance[:3, 3:]
    velocity_position = covariance[3:, :3]
    velocity = covariance[3:, 3:]
    return (
        position
        + seconds * (position_velocity + velocity_position)
        + seconds**2 * velocity
    )


def _encounter_plane_basis(relative_velocity: np.ndarray) -> np.ndarray:
    speed = float(np.linalg.norm(relative_velocity))
    if speed <= MIN_RELATIVE_SPEED_KM_S:
        raise ProbabilityUnavailable(
            "RELATIVE_VELOCITY_TOO_LOW",
            "Encounter-plane probability requires nonzero relative velocity.",
        )
    normal = relative_velocity / speed
    reference = np.zeros(3)
    reference[int(np.argmin(np.abs(normal)))] = 1.0
    first = np.cross(normal, reference)
    first /= np.linalg.norm(first)
    second = np.cross(normal, first)
    return np.vstack((first, second))


def _integrate_gaussian_over_circle(
    mean: np.ndarray,
    covariance: np.ndarray,
    radius_km: float,
) -> float:
    """Integrate a bivariate Gaussian over a circle in standardized space."""

    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    if (
        not np.isfinite(eigenvalues).all()
        or float(eigenvalues[0]) <= 0
    ):
        raise ProbabilityUnavailable(
            "ENCOUNTER_COVARIANCE_INVALID",
            "Projected encounter-plane covariance must be positive definite.",
        )
    rotated_mean = eigenvectors.T @ mean
    sigma_x, sigma_y = np.sqrt(eigenvalues)
    lower = max(
        (-radius_km - float(rotated_mean[0])) / float(sigma_x),
        -STANDARD_NORMAL_LIMIT,
    )
    upper = min(
        (radius_km - float(rotated_mean[0])) / float(sigma_x),
        STANDARD_NORMAL_LIMIT,
    )
    if lower >= upper:
        return 0.0

    def integrand(standard_x: float) -> float:
        x = float(rotated_mean[0]) + float(sigma_x) * standard_x
        y_limit = math.sqrt(max(0.0, radius_km**2 - x**2))
        upper_y = (
            y_limit - float(rotated_mean[1])
        ) / float(sigma_y)
        lower_y = (
            -y_limit - float(rotated_mean[1])
        ) / float(sigma_y)
        standard_density = (
            math.exp(-0.5 * standard_x**2) / math.sqrt(2.0 * math.pi)
        )
        return standard_density * float(ndtr(upper_y) - ndtr(lower_y))

    probability, _ = quad(
        integrand,
        lower,
        upper,
        epsabs=1e-13,
        epsrel=1e-11,
        limit=200,
    )
    return min(1.0, max(0.0, float(probability)))


def classify_risk(collision_probability: float) -> str:
    """Map a computed probability to transparent prototype risk bands."""

    for level, threshold in RISK_THRESHOLDS:
        if collision_probability >= threshold:
            return level
    return "negligible"


def compute_collision_probability(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
    relative_position_km: list[float],
    relative_velocity_km_s: list[float],
    tca_seconds: float,
) -> dict[str, Any]:
    """Compute prototype probability from compatible Cartesian covariances."""

    primary_covariance = primary.get("state_covariance")
    secondary_covariance = secondary.get("state_covariance")
    if primary_covariance is None or secondary_covariance is None:
        raise ProbabilityUnavailable(
            "COVARIANCE_MISSING",
            "Collision probability requires covariance for both objects.",
        )

    primary_radius = primary.get("hard_body_radius_m")
    secondary_radius = secondary.get("hard_body_radius_m")
    if primary_radius is None or secondary_radius is None:
        raise ProbabilityUnavailable(
            "HARD_BODY_RADIUS_MISSING",
            "Collision probability requires hard-body radius for both objects.",
        )

    combined_covariance = _propagated_position_covariance(
        primary_covariance,
        tca_seconds,
    ) + _propagated_position_covariance(
        secondary_covariance,
        tca_seconds,
    )
    basis = _encounter_plane_basis(
        np.asarray(relative_velocity_km_s, dtype=float)
    )
    encounter_covariance = basis @ combined_covariance @ basis.T
    encounter_mean = basis @ np.asarray(relative_position_km, dtype=float)
    hard_body_radius_m = float(primary_radius) + float(secondary_radius)
    probability = _integrate_gaussian_over_circle(
        encounter_mean,
        encounter_covariance,
        hard_body_radius_m / 1000.0,
    )

    return {
        "collision_probability": probability,
        "hard_body_radius_m": hard_body_radius_m,
        "risk_level": classify_risk(probability),
        "method": {
            "name": PROBABILITY_METHOD_NAME,
            "version": PROBABILITY_METHOD_VERSION,
            "validation_status": "prototype_unvalidated",
        },
    }
