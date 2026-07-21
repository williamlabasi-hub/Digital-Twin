import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from common.telemetry_validation import (  # noqa: E402
    load_contracts,
    validate_telemetry_batch,
    validate_telemetry_record,
)


class TelemetryValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema, cls.dictionary = load_contracts()
        cls.example = json.loads(
            (
                REPOSITORY_ROOT
                / "tests"
                / "fixtures"
                / "telemetry"
                / "housekeeping-telemetry.example.json"
            ).read_text(encoding="utf-8")
        )
        cls.example_time = datetime(2026, 7, 21, 18, 30, tzinfo=timezone.utc)

    def validate(self, record, reference_time=None):
        return validate_telemetry_record(
            record,
            schema=self.schema,
            dictionary=self.dictionary,
            reference_time=reference_time or self.example_time,
        )

    def test_example_is_valid_and_complete(self) -> None:
        result = self.validate(self.example)
        self.assertTrue(result.valid)
        self.assertEqual(result.data_quality, "complete")
        self.assertEqual(result.issues, [])

    def test_impossible_physical_value_is_rejected(self) -> None:
        record = copy.deepcopy(self.example)
        record["telemetry"]["battery_voltage_v"] = 900
        result = self.validate(record)
        self.assertFalse(result.valid)
        self.assertIn(
            "physical_range_violation", {issue.code for issue in result.issues}
        )

    def test_required_parameter_may_not_be_missing(self) -> None:
        record = copy.deepcopy(self.example)
        del record["telemetry"]["gyro_x_rate_deg_s"]
        result = self.validate(record)
        self.assertFalse(result.valid)
        self.assertIn(
            "required_parameter_missing", {issue.code for issue in result.issues}
        )

    def test_old_record_is_valid_but_degraded(self) -> None:
        result = self.validate(
            self.example,
            reference_time=self.example_time + timedelta(minutes=10),
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.data_quality, "degraded")
        self.assertIn("stale_parameter", {issue.code for issue in result.issues})

    def test_future_timestamp_is_rejected(self) -> None:
        result = self.validate(
            self.example,
            reference_time=self.example_time - timedelta(minutes=10),
        )
        self.assertFalse(result.valid)
        self.assertIn("future_timestamp", {issue.code for issue in result.issues})

    def test_duplicate_record_is_rejected(self) -> None:
        results = validate_telemetry_batch(
            [self.example, copy.deepcopy(self.example)],
            schema=self.schema,
            dictionary=self.dictionary,
            reference_time=self.example_time,
        )
        self.assertTrue(results[0].valid)
        self.assertFalse(results[1].valid)
        self.assertIn("duplicate_record", {issue.code for issue in results[1].issues})


if __name__ == "__main__":
    unittest.main()

