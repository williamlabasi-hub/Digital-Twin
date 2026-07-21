import copy
import json
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from common.telemetry_validation import load_contracts  # noqa: E402
from health.telemetry_adapter import (  # noqa: E402
    TelemetryAdapterError,
    validate_and_adapt_housekeeping_record,
)
from health.health_monitor import prepare_dataset  # noqa: E402


class TelemetryAdapterTests(unittest.TestCase):
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

    def adapt(self, record, reference_time=None):
        return validate_and_adapt_housekeeping_record(
            record,
            schema=self.schema,
            dictionary=self.dictionary,
            reference_time=reference_time or self.example_time,
        )

    def test_valid_record_maps_to_legacy_features(self) -> None:
        adapted = self.adapt(self.example)
        model_record = adapted.model_record

        self.assertEqual(model_record["satellite_id"], "SAT-001")
        self.assertEqual(model_record["mode"], "nominal")
        self.assertEqual(model_record["solar_panel_current"], 5.8)
        self.assertEqual(model_record["bus_temperature_c"], 29.4)
        self.assertEqual(model_record["battery_voltage"], 28.1)
        self.assertEqual(model_record["battery_current"], 2.4)

    def test_maximum_absolute_wheel_speed_is_used(self) -> None:
        adapted = self.adapt(self.example)
        self.assertEqual(adapted.model_record["reaction_wheel_rpm"], 4120.0)

    def test_invalid_record_is_rejected_before_adaptation(self) -> None:
        record = copy.deepcopy(self.example)
        record["telemetry"]["battery_voltage_v"] = 900

        with self.assertRaises(TelemetryAdapterError) as context:
            self.adapt(record)

        self.assertFalse(context.exception.validation.valid)

    def test_validation_warning_does_not_block_adaptation(self) -> None:
        adapted = self.adapt(
            self.example,
            reference_time=self.example_time + timedelta(minutes=10),
        )
        self.assertTrue(adapted.validation.valid)
        self.assertEqual(adapted.validation.data_quality, "degraded")

    def test_command_features_are_not_fabricated(self) -> None:
        model_record = self.adapt(self.example).model_record
        self.assertNotIn("recent_command_name", model_record)
        self.assertNotIn("recent_command_status", model_record)
        self.assertNotIn("seconds_since_last_command", model_record)

    def test_mapping_assumptions_are_exposed(self) -> None:
        adapted = self.adapt(self.example)
        self.assertEqual(adapted.adapter_version, "0.1.0")
        self.assertEqual(len(adapted.assumptions), 3)

    def test_prepare_dataset_validates_adapts_then_aligns_command(self) -> None:
        command = {
            "satellite_id": "SAT-001",
            "timestamp": "2026-07-21T18:29:00Z",
            "command_name": "maintain_attitude",
            "command_status": "successful",
        }
        with patch(
            "health.health_monitor.load_json_records",
            side_effect=[[self.example], [command]],
        ):
            dataset = prepare_dataset(
                Path("telemetry.json"),
                Path("commands.json"),
                validation_reference_time=self.example_time,
            )

        self.assertEqual(dataset.loc[0, "battery_voltage"], 28.1)
        self.assertEqual(dataset.loc[0, "recent_command_name"], "maintain_attitude")
        self.assertEqual(dataset.loc[0, "seconds_since_last_command"], 60.0)
        self.assertEqual(dataset.loc[0, "input_data_quality"], "complete")

    def test_prepare_dataset_rejects_mixed_envelope_and_legacy_records(self) -> None:
        legacy = {"satellite_id": "SAT-001", "timestamp": "2026-07-21T18:30:00Z"}
        with patch(
            "health.health_monitor.load_json_records",
            side_effect=[[self.example, legacy], [{}]],
        ):
            with self.assertRaisesRegex(ValueError, "may not mix"):
                prepare_dataset(Path("telemetry.json"), Path("commands.json"))


if __name__ == "__main__":
    unittest.main()
