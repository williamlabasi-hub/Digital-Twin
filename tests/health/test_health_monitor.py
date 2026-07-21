import json
import sys
import unittest
from pathlib import Path

import joblib
import pandas as pd
from jsonschema import Draft7Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from health.health_features import MODEL_FEATURES
from health.health_monitor import (
    build_ml_records,
    build_report,
    determine_health_trend,
    integrate_command_history,
    prepare_dataset,
    save_report,
    validate_features,
)


class HealthMonitorTests(unittest.TestCase):
    def test_command_alignment_never_uses_a_future_command(self) -> None:
        telemetry = pd.DataFrame(
            [{"satellite_id": "SAT-1", "timestamp": "2026-01-01T00:10:00Z"}]
        )
        commands = pd.DataFrame(
            [
                {
                    "satellite_id": "SAT-1",
                    "timestamp": "2026-01-01T00:05:00Z",
                    "command_name": "past",
                    "command_status": "successful",
                },
                {
                    "satellite_id": "SAT-1",
                    "timestamp": "2026-01-01T00:15:00Z",
                    "command_name": "future",
                    "command_status": "successful",
                },
            ]
        )

        result = integrate_command_history(telemetry, commands)

        self.assertEqual(result.loc[0, "recent_command_name"], "past")
        self.assertEqual(result.loc[0, "seconds_since_last_command"], 300.0)

    def test_trend_uses_latest_record_before_current_time(self) -> None:
        history = [
            {
                "satellite_id": "SAT-1",
                "timestamp": "2026-01-01T00:20:00Z",
                "prediction": "Critical",
            },
            {
                "satellite_id": "SAT-1",
                "timestamp": "2026-01-01T00:05:00Z",
                "prediction": "Healthy",
            },
        ]

        trend = determine_health_trend(
            "SAT-1", "Warning", "2026-01-01T00:10:00Z", history
        )

        self.assertEqual(trend["previous_health_status"], "Healthy")
        self.assertIn("worsened", trend["trend"])

    def test_missing_feature_column_is_rejected(self) -> None:
        frame = pd.DataFrame([{feature: 1 for feature in MODEL_FEATURES[:-1]}])

        with self.assertRaisesRegex(ValueError, "missing required"):
            validate_features(frame, MODEL_FEATURES)

    def test_full_ml_record_matches_public_field_names(self) -> None:
        report = [
            {
                "satellite_id": "SAT-1",
                "timestamp": "2026-01-01T00:00:00Z",
                "prediction": "Healthy",
                "predicted_probability": 0.8,
                "telemetry": {"battery_voltage": 28.0},
                "recent_command": {"seconds_since_command": 60.0},
                "class_probabilities": {"Healthy": 0.8, "Warning": 0.2},
            }
        ]

        record = build_ml_records(report)[0]

        self.assertEqual(record["seconds_since_command"], 60.0)
        self.assertEqual(record["class_probabilities"]["Healthy"], 0.8)
        self.assertNotIn("seconds_since_last_command", record)

    def test_saved_model_and_sample_data_produce_schema_valid_output(self) -> None:
        model_path = (
            REPOSITORY_ROOT
            / "data"
            / "processed"
            / "health"
            / "models"
            / "satellite_health_model.joblib"
        )
        schema_path = (
            REPOSITORY_ROOT
            / "docs"
            / "requirements"
            / "health"
            / "health_predictions.schema.json"
        )
        if not model_path.exists() or not schema_path.exists():
            self.skipTest(
                "Versioned model artifact and health-report schema are not present."
            )

        dataset = prepare_dataset(
            REPOSITORY_ROOT / "data" / "raw" / "telemetry" / "HealthTelemetry1.json",
            REPOSITORY_ROOT
            / "data"
            / "raw"
            / "command_history"
            / "CommandHistory1.json",
        )
        model = joblib.load(model_path)
        report = build_report(dataset, model, history=[])

        output_path = Path(__file__).resolve().parent / "_health_predictions_test.json"
        try:
            save_report(
                report,
                output_path,
                model_metadata=model.health_model_metadata_,
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))
            schema = json.loads(
                schema_path.read_text(encoding="utf-8")
            )
        finally:
            output_path.unlink(missing_ok=True)

        self.assertEqual(len(report), len(dataset))
        self.assertFalse(list(Draft7Validator(schema).iter_errors(output)))
        for entry in report:
            self.assertAlmostEqual(sum(entry["class_probabilities"].values()), 1.0)


if __name__ == "__main__":
    unittest.main()
