"""Run the complete health pipeline against versioned synthetic scenarios."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from health.health_monitor import build_report, prepare_dataset  # noqa: E402


def main() -> int:
    telemetry = ROOT / "data" / "raw" / "telemetry" / "HealthTelemetry1.json"
    commands = ROOT / "data" / "raw" / "command_history" / "CommandHistory1.json"
    labels_path = ROOT / "data" / "raw" / "telemetry" / "HealthLabels1.json"
    model_path = ROOT / "data" / "processed" / "health" / "models" / "satellite_health_model.joblib"

    dataset = prepare_dataset(telemetry, commands)
    report = build_report(dataset, joblib.load(model_path), history=[])
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    expected = {
        (item["satellite_id"], item["timestamp"]): item["health_status"]
        for item in labels
    }
    correct = 0
    abstained = 0
    for entry in report:
        timestamp = str(entry["timestamp"]).replace("+00:00", "Z")
        label = expected[(entry["satellite_id"], timestamp)]
        correct += entry["prediction"] == label
        abstained += not entry["model_assurance"]["accepted"]

    summary = {
        "scenario_records": len(report),
        "raw_ml_matches_synthetic_labels": correct,
        "model_abstentions": abstained,
        "schema_contract": "validated separately by test_health_monitor.py",
        "validation_level": "synthetic_fault_injection_only",
        "hardware_in_the_loop_complete": False,
    }
    print(json.dumps(summary, indent=2))
    return 0 if correct == len(report) and abstained == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
