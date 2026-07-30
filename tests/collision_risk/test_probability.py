import math
import unittest

import numpy as np

from src.collision_risk.probability import (
    ProbabilityUnavailable,
    classify_risk,
    compute_collision_probability,
)


def covariance(position_variance: float) -> list[list[float]]:
    matrix = np.eye(6) * 1e-12
    matrix[:3, :3] = np.eye(3) * position_variance
    return matrix.tolist()


def state(position_variance: float, radius_m: float = 10.0) -> dict:
    return {
        "state_covariance": covariance(position_variance),
        "hard_body_radius_m": radius_m,
    }


class CollisionProbabilityTests(unittest.TestCase):
    def test_centered_isotropic_case_matches_closed_form(self) -> None:
        # Each object contributes 0.5 km^2, so encounter variance is 1 km^2.
        result = compute_collision_probability(
            state(0.5, 500.0),
            state(0.5, 500.0),
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            0.0,
        )

        expected = 1.0 - np.exp(-0.5)
        self.assertAlmostEqual(
            result["collision_probability"],
            expected,
            places=10,
        )
        self.assertEqual(result["method"]["version"], "prototype-0.2")

    def test_extreme_radius_to_sigma_ratio_remains_stable(self) -> None:
        primary = state(0.5e-12, 5.0)
        secondary = state(0.5e-12, 5.0)

        result = compute_collision_probability(
            primary,
            secondary,
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            0.0,
        )

        self.assertAlmostEqual(result["collision_probability"], 1.0)

    def test_probability_decreases_for_larger_miss_distance(self) -> None:
        primary = state(0.0001)
        secondary = state(0.0001)
        close = compute_collision_probability(
            primary,
            secondary,
            [0.0, 0.005, 0.0],
            [1.0, 0.0, 0.0],
            0.0,
        )
        far = compute_collision_probability(
            primary,
            secondary,
            [0.0, 0.1, 0.0],
            [1.0, 0.0, 0.0],
            0.0,
        )

        self.assertGreater(
            close["collision_probability"],
            far["collision_probability"],
        )

    def test_probability_is_invariant_under_coordinate_rotation(self) -> None:
        angle = 0.731
        rotation = np.array(
            [
                [math.cos(angle), -math.sin(angle), 0.0],
                [math.sin(angle), math.cos(angle), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        relative_position = np.array([0.0, 0.012, -0.007])
        relative_velocity = np.array([1.0, 0.0, 0.0])
        covariance_matrix = np.eye(6) * 1e-12
        covariance_matrix[1:3, 1:3] = np.array(
            [[0.0002, 0.00006], [0.00006, 0.00045]]
        )
        primary = {
            "state_covariance": covariance_matrix.tolist(),
            "hard_body_radius_m": 12.5,
        }
        secondary = {
            "state_covariance": covariance_matrix.tolist(),
            "hard_body_radius_m": 12.5,
        }
        original = compute_collision_probability(
            primary,
            secondary,
            relative_position.tolist(),
            relative_velocity.tolist(),
            0.0,
        )

        transform = np.zeros((6, 6))
        transform[:3, :3] = rotation
        transform[3:, 3:] = rotation
        rotated_covariance = transform @ covariance_matrix @ transform.T
        rotated_primary = {
            **primary,
            "state_covariance": rotated_covariance.tolist(),
        }
        rotated_secondary = {
            **secondary,
            "state_covariance": rotated_covariance.tolist(),
        }
        rotated = compute_collision_probability(
            rotated_primary,
            rotated_secondary,
            (rotation @ relative_position).tolist(),
            (rotation @ relative_velocity).tolist(),
            0.0,
        )

        self.assertAlmostEqual(
            original["collision_probability"],
            rotated["collision_probability"],
            places=12,
        )

    def test_velocity_covariance_is_propagated_to_tca(self) -> None:
        primary = state(1e-6)
        secondary = state(1e-6)
        primary["state_covariance"][4][4] = 1e-4
        at_epoch = compute_collision_probability(
            primary,
            secondary,
            [0.0, 0.01, 0.0],
            [1.0, 0.0, 0.0],
            0.0,
        )
        propagated = compute_collision_probability(
            primary,
            secondary,
            [0.0, 0.01, 0.0],
            [1.0, 0.0, 0.0],
            10.0,
        )

        self.assertNotEqual(
            at_epoch["collision_probability"],
            propagated["collision_probability"],
        )

    def test_missing_radius_withholds_probability(self) -> None:
        primary = state(0.1)
        del primary["hard_body_radius_m"]

        with self.assertRaises(ProbabilityUnavailable) as context:
            compute_collision_probability(
                primary,
                state(0.1),
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                0.0,
            )

        self.assertEqual(context.exception.code, "HARD_BODY_RADIUS_MISSING")

    def test_risk_threshold_boundaries_are_inclusive(self) -> None:
        self.assertEqual(classify_risk(0.01), "critical")
        self.assertEqual(classify_risk(0.001), "high")
        self.assertEqual(classify_risk(0.0001), "moderate")
        self.assertEqual(classify_risk(0.000001), "low")
        self.assertEqual(classify_risk(0.0000009), "negligible")


if __name__ == "__main__":
    unittest.main()
