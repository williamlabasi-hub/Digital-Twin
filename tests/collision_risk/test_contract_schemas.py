import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from src.collision_risk.validation import INPUT_SCHEMA_PATH, OUTPUT_SCHEMA_PATH


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "collision_risk"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CollisionRiskContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.input_schema = load_json(
            INPUT_SCHEMA_PATH
        )
        cls.output_schema = load_json(
            OUTPUT_SCHEMA_PATH
        )
        cls.input_example = load_json(
            FIXTURES_DIR / "conjunction-assessment-input.example.json"
        )
        cls.high_risk_example = load_json(
            FIXTURES_DIR / "high-risk-assessment.example.json"
        )
        cls.abstained_example = load_json(
            FIXTURES_DIR / "abstained-assessment.example.json"
        )
        cls.input_validator = Draft202012Validator(
            cls.input_schema,
            format_checker=FormatChecker(),
        )
        cls.output_validator = Draft202012Validator(
            cls.output_schema,
            format_checker=FormatChecker(),
        )

    def input_errors(self, record: dict) -> list:
        return list(self.input_validator.iter_errors(record))

    def output_errors(self, record: dict) -> list:
        return list(self.output_validator.iter_errors(record))

    def test_schemas_are_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.output_schema)

    def test_installed_style_import_can_load_packaged_schemas(self) -> None:
        script = (
            "from collision_risk.validation import "
            "INPUT_SCHEMA_PATH, OUTPUT_SCHEMA_PATH, load_schema; "
            "assert load_schema(INPUT_SCHEMA_PATH)['title'] "
            "== 'Conjunction Assessment Input'; "
            "assert load_schema(OUTPUT_SCHEMA_PATH)['title'] "
            "== 'Collision Risk Assessment'"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
            },
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_complete_input_example_is_valid(self) -> None:
        self.assertEqual(self.input_errors(self.input_example), [])

    def test_input_requires_covariance_metadata_with_covariance(self) -> None:
        record = copy.deepcopy(self.input_example)
        del record["primary"]["covariance_metadata"]

        self.assertTrue(self.input_errors(record))

    def test_input_rejects_non_six_by_six_covariance(self) -> None:
        record = copy.deepcopy(self.input_example)
        record["secondary"]["state_covariance"] = [
            row[:3] for row in record["secondary"]["state_covariance"][:3]
        ]

        self.assertTrue(self.input_errors(record))

    def test_input_rejects_unsupported_coordinate_frame(self) -> None:
        record = copy.deepcopy(self.input_example)
        record["primary"]["coordinate_frame"] = "ECEF"

        self.assertTrue(self.input_errors(record))

    def test_high_risk_complete_example_is_valid(self) -> None:
        self.assertEqual(self.output_errors(self.high_risk_example), [])

    def test_abstained_example_is_valid(self) -> None:
        self.assertEqual(self.output_errors(self.abstained_example), [])

    def test_complete_assessment_requires_computed_probability(self) -> None:
        record = copy.deepcopy(self.high_risk_example)
        record["probability"] = copy.deepcopy(
            self.abstained_example["probability"]
        )

        self.assertTrue(self.output_errors(record))

    def test_abstained_assessment_requires_reason_and_null_geometry(self) -> None:
        record = copy.deepcopy(self.abstained_example)
        record["abstention_reason"] = None
        record["closest_approach"] = copy.deepcopy(
            self.high_risk_example["closest_approach"]
        )

        self.assertTrue(self.output_errors(record))

    def test_geometric_only_withholds_probability_and_risk_level(self) -> None:
        record = copy.deepcopy(self.high_risk_example)
        record["assessment_id"] = "CRA-CONJ-2026-GEOMETRY"
        record["assessment_status"] = "geometric_only"
        record["probability"] = {
            "status": "unavailable",
            "collision_probability": None,
            "method": None,
            "hard_body_radius_m": 20.0,
            "interpretation": "Covariance was unavailable.",
        }
        record["risk"] = {
            "level": "undetermined",
            "basis": "Collision probability was unavailable.",
            "threshold_version": None,
        }
        record["uncertainty_assurance"] = {
            "status": "missing_covariance",
            "covariance_frame": None,
            "assumptions": [],
        }
        record["data_quality"] = {
            "status": "degraded",
            "issues": [
                {
                    "code": "COVARIANCE_MISSING",
                    "severity": "warning",
                    "message": "Only closest-approach geometry is available.",
                }
            ],
        }

        self.assertEqual(self.output_errors(record), [])

    def test_probability_cannot_exceed_one(self) -> None:
        record = copy.deepcopy(self.high_risk_example)
        record["probability"]["collision_probability"] = 1.01

        self.assertTrue(self.output_errors(record))


if __name__ == "__main__":
    unittest.main()
