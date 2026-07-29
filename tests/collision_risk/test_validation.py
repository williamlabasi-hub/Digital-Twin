import copy
import json
import unittest
from pathlib import Path

from src.collision_risk.validation import (
    ConjunctionInputError,
    validate_conjunction_input,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "collision_risk"
    / "conjunction-assessment-input.example.json"
)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class ConjunctionSemanticValidationTests(unittest.TestCase):
    def test_complete_fixture_is_semantically_valid(self) -> None:
        validate_conjunction_input(fixture())

    def test_objects_must_be_distinct(self) -> None:
        record = fixture()
        record["secondary"]["object_id"] = record["primary"]["object_id"]

        with self.assertRaisesRegex(
            ConjunctionInputError, "must be different"
        ) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "OBJECT_IDENTIFIERS_NOT_DISTINCT")

    def test_coordinate_frames_must_match(self) -> None:
        record = fixture()
        record["secondary"]["coordinate_frame"] = "TEME"
        record["secondary"]["covariance_metadata"]["frame"] = "TEME"

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "INCOMPATIBLE_COORDINATE_FRAMES")

    def test_state_epochs_must_match(self) -> None:
        record = fixture()
        record["secondary"]["epoch"] = "2026-07-29T20:00:01Z"

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "MISMATCHED_STATE_EPOCHS")

    def test_analysis_window_must_be_forward(self) -> None:
        record = fixture()
        record["analysis_window"]["end"] = record["analysis_window"]["start"]

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "ANALYSIS_WINDOW_INVALID")

    def test_linear_window_is_limited_to_fifteen_minutes(self) -> None:
        record = fixture()
        record["analysis_window"]["end"] = "2026-07-29T20:15:01Z"

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "ANALYSIS_WINDOW_TOO_LONG")

    def test_covariance_must_be_symmetric(self) -> None:
        record = fixture()
        record["primary"]["state_covariance"][0][1] = 0.01

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "COVARIANCE_NOT_SYMMETRIC")

    def test_covariance_must_be_positive_definite(self) -> None:
        record = fixture()
        record["primary"]["state_covariance"][0][0] = 0.0

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(
            context.exception.code,
            "COVARIANCE_NOT_POSITIVE_DEFINITE",
        )

    def test_covariance_frame_must_already_match_state_frame(self) -> None:
        record = fixture()
        record["primary"]["covariance_metadata"]["frame"] = "RTN"

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "COVARIANCE_FRAME_UNSUPPORTED")

    def test_structural_failure_is_identified_separately(self) -> None:
        record = fixture()
        del record["primary"]["position_km"]

        with self.assertRaises(ConjunctionInputError) as context:
            validate_conjunction_input(record)

        self.assertEqual(context.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_validation_does_not_mutate_input(self) -> None:
        record = fixture()
        original = copy.deepcopy(record)

        validate_conjunction_input(record)

        self.assertEqual(record, original)


if __name__ == "__main__":
    unittest.main()
