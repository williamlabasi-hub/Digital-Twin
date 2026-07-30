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
