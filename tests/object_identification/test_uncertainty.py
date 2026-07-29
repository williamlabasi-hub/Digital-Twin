import unittest
from copy import deepcopy

from src.object_identification.uncertainty import (
    apply_uncertainty_model,
    estimate_candidate_covariance,
    estimate_observation_covariance,
    load_uncertainty_config,
)


def propagation(catalog: int, hour: int = 12) -> dict:
    return {
        "name": f"OBJECT {catalog}",
        "catalog": catalog,
        "coordinate_frame": "ECI",
        "position_km": [6628.1, 1045.2, -421.7],
        "cartesian_velocity_km_s": [-1.08, 7.31, 1.42],
        "time": {
            "year": 2026,
            "month": 7,
            "day": 29,
            "hour": hour,
            "minute": 0,
            "second": 0,
        },
    }


def candidate_record(catalog: int, hour: int = 12) -> dict:
    return {
        "propagation": propagation(catalog, hour),
        "catalog_source": "TEST",
        "object_type": "payload",
        "affiliation": "other",
        "affiliation_authority": "TEST",
        "affiliation_source_record_id": f"AFF-{catalog}",
    }


class ObjectIdentificationUncertaintyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_uncertainty_config()

    def test_sensor_sigma_scales_with_measurement_quality(self) -> None:
        covariance = estimate_observation_covariance(
            sensor_type="radar",
            measurement_quality=0.5,
            config=self.config,
        )

        self.assertEqual(
            covariance["position_covariance_km2"][0][0],
            4.0,
        )
        self.assertEqual(
            covariance["velocity_covariance_km2_s2"][0][0],
            0.0004,
        )

    def test_catalog_sigma_grows_with_propagation_age(self) -> None:
        covariance, age_hours = estimate_candidate_covariance(
            observation_propagation=propagation(90001, 12),
            candidate_propagation=propagation(25544, 10),
            config=self.config,
        )

        self.assertEqual(age_hours, 2.0)
        self.assertAlmostEqual(
            covariance["position_covariance_km2"][0][0],
            0.49,
        )
        self.assertAlmostEqual(
            covariance["velocity_covariance_km2_s2"][0][0],
            0.000049,
        )

    def test_model_fills_only_missing_covariance(self) -> None:
        observation = propagation(90001)
        supplied_position = [
            [9.0, 0.0, 0.0],
            [0.0, 9.0, 0.0],
            [0.0, 0.0, 9.0],
        ]
        observation["position_covariance_km2"] = supplied_position
        candidates = [candidate_record(25544)]

        modeled_observation, modeled_candidates, assurance = (
            apply_uncertainty_model(
                observation,
                candidates,
                sensor_type="other",
                measurement_quality=0.8,
                config=self.config,
            )
        )

        self.assertEqual(assurance["mode"], "mixed")
        self.assertEqual(
            modeled_observation["position_covariance_km2"],
            supplied_position,
        )
        self.assertIn(
            "velocity_covariance_km2_s2",
            modeled_observation,
        )
        self.assertIn(
            "position_covariance_km2",
            modeled_candidates[0]["propagation"],
        )
        self.assertNotIn(
            "velocity_covariance_km2_s2",
            observation,
        )
        self.assertNotIn(
            "position_covariance_km2",
            candidates[0]["propagation"],
        )

    def test_complete_supplied_covariance_is_not_replaced(self) -> None:
        observation = propagation(90001)
        candidates = [candidate_record(25544)]
        supplied = [
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 2.0],
        ]
        for value in (
            observation,
            candidates[0]["propagation"],
        ):
            value["position_covariance_km2"] = deepcopy(supplied)
            value["velocity_covariance_km2_s2"] = deepcopy(supplied)

        modeled_observation, modeled_candidates, assurance = (
            apply_uncertainty_model(
                observation,
                candidates,
                sensor_type="other",
                measurement_quality=0.8,
                config=self.config,
            )
        )

        self.assertEqual(assurance["mode"], "supplied")
        self.assertEqual(
            modeled_observation["position_covariance_km2"],
            supplied,
        )
        self.assertEqual(
            modeled_candidates[0]["propagation"][
                "velocity_covariance_km2_s2"
            ],
            supplied,
        )


if __name__ == "__main__":
    unittest.main()
