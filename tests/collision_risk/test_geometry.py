import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.collision_risk.geometry import assess_closest_approach
from src.collision_risk.validation import ConjunctionInputError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "collision_risk"
    / "conjunction-assessment-input.example.json"
)
GENERATED_AT = datetime(2026, 7, 29, 20, 1, tzinfo=timezone.utc)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def linear_case() -> dict:
    record = fixture()
    record["analysis_window"] = {
        "start": "2026-07-29T20:00:00Z",
        "end": "2026-07-29T20:00:20Z",
    }
    record["primary"]["position_km"] = [0.0, 0.0, 0.0]
    record["primary"]["velocity_km_s"] = [0.0, 0.0, 0.0]
    record["secondary"]["position_km"] = [10.0, 1.0, 0.0]
    record["secondary"]["velocity_km_s"] = [-1.0, 0.0, 0.0]
    return record


class ClosestApproachGeometryTests(unittest.TestCase):
    def test_known_linear_case_finds_interior_minimum(self) -> None:
        result = assess_closest_approach(
            linear_case(),
            generated_at=GENERATED_AT,
        )

        geometry = result["closest_approach"]
        self.assertEqual(result["assessment_status"], "complete")
        self.assertEqual(
            geometry["time_of_closest_approach"],
            "2026-07-29T20:00:10Z",
        )
        self.assertAlmostEqual(geometry["miss_distance_km"], 1.0)
        self.assertAlmostEqual(geometry["relative_velocity_km_s"], 1.0)
        self.assertEqual(geometry["relative_position_km"], [0.0, 1.0, 0.0])
        self.assertEqual(result["probability"]["status"], "computed")
        self.assertIsNotNone(result["probability"]["collision_probability"])
        self.assertNotEqual(result["risk"]["level"], "undetermined")

    def test_tca_is_clamped_to_window_end(self) -> None:
        record = linear_case()
        record["analysis_window"]["end"] = "2026-07-29T20:00:05Z"

        result = assess_closest_approach(record, generated_at=GENERATED_AT)

        geometry = result["closest_approach"]
        self.assertEqual(
            geometry["time_of_closest_approach"],
            "2026-07-29T20:00:05Z",
        )
        self.assertAlmostEqual(
            geometry["miss_distance_km"],
            (5.0**2 + 1.0**2) ** 0.5,
        )
        self.assertEqual(result["assessment_status"], "geometric_only")
        self.assertEqual(
            result["data_quality"]["issues"][0]["code"],
            "ENCOUNTER_OUTSIDE_ANALYSIS_WINDOW",
        )

    def test_tca_is_clamped_to_delayed_window_start(self) -> None:
        record = linear_case()
        record["analysis_window"]["start"] = "2026-07-29T20:00:05Z"
        record["secondary"]["position_km"] = [1.0, 0.0, 0.0]
        record["secondary"]["velocity_km_s"] = [1.0, 0.0, 0.0]

        result = assess_closest_approach(record, generated_at=GENERATED_AT)

        geometry = result["closest_approach"]
        self.assertEqual(
            geometry["time_of_closest_approach"],
            "2026-07-29T20:00:05Z",
        )
        self.assertAlmostEqual(geometry["miss_distance_km"], 6.0)
        self.assertEqual(result["assessment_status"], "geometric_only")
        self.assertEqual(
            result["data_quality"]["issues"][0]["code"],
            "ENCOUNTER_OUTSIDE_ANALYSIS_WINDOW",
        )

    def test_zero_relative_velocity_uses_window_start(self) -> None:
        record = linear_case()
        record["secondary"]["velocity_km_s"] = [0.0, 0.0, 0.0]

        result = assess_closest_approach(record, generated_at=GENERATED_AT)

        self.assertEqual(
            result["closest_approach"]["time_of_closest_approach"],
            record["analysis_window"]["start"],
        )
        self.assertEqual(
            result["closest_approach"]["relative_velocity_km_s"],
            0.0,
        )
        self.assertEqual(result["assessment_status"], "geometric_only")
        self.assertEqual(
            result["data_quality"]["issues"][0]["code"],
            "RELATIVE_VELOCITY_TOO_LOW",
        )

    def test_missing_covariance_still_returns_geometry(self) -> None:
        record = linear_case()
        for state in (record["primary"], record["secondary"]):
            del state["state_covariance"]
            del state["covariance_metadata"]

        result = assess_closest_approach(record, generated_at=GENERATED_AT)

        self.assertEqual(result["assessment_status"], "geometric_only")
        self.assertEqual(
            result["uncertainty_assurance"]["status"],
            "missing_covariance",
        )
        codes = {
            issue["code"] for issue in result["data_quality"]["issues"]
        }
        self.assertIn("COVARIANCE_MISSING", codes)

    def test_mismatched_frames_produce_explicit_abstention(self) -> None:
        record = linear_case()
        record["secondary"]["coordinate_frame"] = "TEME"
        record["secondary"]["covariance_metadata"]["frame"] = "TEME"

        result = assess_closest_approach(record, generated_at=GENERATED_AT)

        self.assertEqual(result["assessment_status"], "abstained")
        self.assertIsNone(result["closest_approach"])
        self.assertEqual(
            result["abstention_reason"],
            "incompatible_coordinate_frames",
        )

    def test_invalid_covariance_produces_explicit_abstention(self) -> None:
        record = linear_case()
        record["secondary"]["state_covariance"][0][0] = -1.0

        result = assess_closest_approach(record, generated_at=GENERATED_AT)

        self.assertEqual(result["assessment_status"], "abstained")
        self.assertEqual(
            result["uncertainty_assurance"]["status"],
            "invalid_covariance",
        )
        self.assertEqual(
            result["data_quality"]["issues"][0]["code"],
            "COVARIANCE_NOT_POSITIVE_DEFINITE",
        )

    def test_structurally_invalid_input_raises_contract_error(self) -> None:
        record = linear_case()
        del record["request_id"]

        with self.assertRaises(ConjunctionInputError) as context:
            assess_closest_approach(record, generated_at=GENERATED_AT)

        self.assertEqual(context.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_generated_at_requires_timezone(self) -> None:
        with self.assertRaises(ConjunctionInputError) as context:
            assess_closest_approach(
                linear_case(),
                generated_at=datetime(2026, 7, 29, 20, 1),
            )

        self.assertEqual(
            context.exception.code,
            "GENERATED_AT_TIMEZONE_MISSING",
        )

    def test_assessment_does_not_mutate_input(self) -> None:
        record = linear_case()
        original = copy.deepcopy(record)

        assess_closest_approach(record, generated_at=GENERATED_AT)

        self.assertEqual(record, original)


if __name__ == "__main__":
    unittest.main()
