import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import joblib
import pandas as pd
from jsonschema import Draft7Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from health.health_features import MODEL_FEATURES
import health.health_monitor as health_monitor_module
from health.health_monitor import (
    DEFAULT_SCHEMA_PATH,
    build_ml_records,
    build_report,
    create_recommendations,
    determine_health_trend,
    integrate_command_history,
    prepare_dataset,
    parse_args,
    save_report,
    validate_features,
)


class HealthMonitorTests(unittest.TestCase):
    def test_installed_cli_requires_external_runtime_inputs(self) -> None:
        missing = REPOSITORY_ROOT / "_not_installed_with_wheel"
        with (
            patch.object(health_monitor_module, "DEFAULT_MODEL_PATH", missing),
            patch.object(
                health_monitor_module,
                "DEFAULT_TELEMETRY_PATH",
                missing,
            ),
            patch.object(
                health_monitor_module,
                "DEFAULT_COMMAND_HISTORY_PATH",
                missing,
            ),
            patch.object(sys, "argv", ["health-monitor"]),
            redirect_stderr(StringIO()),
            self.assertRaises(SystemExit) as context,
        ):
            parse_args()

        self.assertEqual(context.exception.code, 2)

    def test_installed_cli_accepts_explicit_runtime_inputs(self) -> None:
        missing = REPOSITORY_ROOT / "_not_installed_with_wheel"
        arguments = [
            "health-monitor",
            "--model",
            "model.joblib",
            "--telemetry",
            "telemetry.json",
            "--command-history",
            "commands.json",
        ]
        with (
            patch.object(health_monitor_module, "DEFAULT_MODEL_PATH", missing),
            patch.object(
                health_monitor_module,
                "DEFAULT_TELEMETRY_PATH",
                missing,
            ),
            patch.object(
                health_monitor_module,
                "DEFAULT_COMMAND_HISTORY_PATH",
                missing,
            ),
            patch.object(sys, "argv", arguments),
        ):
            parsed = parse_args()

        self.assertEqual(parsed.model, Path("model.joblib"))
        self.assertEqual(parsed.telemetry, Path("telemetry.json"))
        self.assertEqual(parsed.command_history, Path("commands.json"))
        self.assertEqual(parsed.output, Path.cwd() / "health_predictions.json")
        self.assertEqual(parsed.history, Path.cwd() / "health_history.json")

    def test_stale_healthy_prediction_does_not_recommend_nominal_operations(self) -> None:
        row = pd.Series(
            {
                **{feature: 1 for feature in MODEL_FEATURES},
                "input_data_quality": "degraded",
                "input_validation_issues": [
                    "battery_voltage_v is 900 seconds old; limit is 30 seconds."
                ],
            }
        )

        recommendations = create_recommendations("Healthy", row)

        self.assertNotIn("Continue nominal operations.", recommendations)
        self.assertNotIn("No corrective action is currently required.", recommendations)
        self.assertTrue(any("historical" in item for item in recommendations))
        self.assertTrue(any("current telemetry" in item for item in recommendations))

    def test_health_monitor_supports_direct_script_help(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPOSITORY_ROOT / "src" / "health" / "health_monitor.py"), "--help"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("satellite health predictions", completed.stdout.lower())

    def test_committed_example_output_matches_health_schema(self) -> None:
        output_path = REPOSITORY_ROOT / "data" / "outputs" / "health" / "health_predictions.json"
        schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        output = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertFalse(list(Draft7Validator(schema).iter_errors(output)))

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
        if not model_path.exists():
            self.skipTest("Versioned model artifact is not present.")

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
                DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8")
            )
        finally:
            output_path.unlink(missing_ok=True)

        self.assertEqual(len(report), len(dataset))
        self.assertFalse(list(Draft7Validator(schema).iter_errors(output)))
        for entry in report:
            self.assertAlmostEqual(sum(entry["class_probabilities"].values()), 1.0)
            self.assertEqual(
                set(entry["subsystem_health"]),
                {"power", "thermal", "payload", "adcs", "communications", "cdh", "propulsion", "timing", "command_control"},
            )
            self.assertIn(entry["overall_health"]["status"], {
                "Healthy", "Warning", "Degraded", "Critical"
            })


if __name__ == "__main__":
    unittest.main()
