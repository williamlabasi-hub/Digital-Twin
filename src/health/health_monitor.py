from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

try:
    from .health_features import HEALTH_CLASSES, MODEL_FEATURES, NUMERICAL_FEATURES
    from .telemetry_adapter import validate_and_adapt_housekeeping_record
except ImportError:  # Allow direct execution: python src/health/health_monitor.py
    from health_features import HEALTH_CLASSES, MODEL_FEATURES, NUMERICAL_FEATURES
    from telemetry_adapter import validate_and_adapt_housekeeping_record


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parents[1]

DEFAULT_MODEL_PATH = REPOSITORY_ROOT / "data" / "processed" / "health" / "models" / "satellite_health_model.joblib"
DEFAULT_TELEMETRY_PATH = REPOSITORY_ROOT / "data" / "raw" / "telemetry" / "HealthTelemetry1.json"
DEFAULT_COMMAND_HISTORY_PATH = REPOSITORY_ROOT / "data" / "raw" / "command_history" / "CommandHistory1.json"
DEFAULT_REPORT_PATH = REPOSITORY_ROOT / "data" / "outputs" / "health" / "health_predictions.json"
DEFAULT_HISTORY_PATH = REPOSITORY_ROOT / "data" / "outputs" / "health" / "health_history.json"
DEFAULT_SCHEMA_PATH = REPOSITORY_ROOT / "docs" / "requirements" / "health" / "health_predictions.schema.json"


OUTPUT_SCHEMA_VERSION = "1.1.0"


def load_json_records(
    file_path: Path,
) -> list[dict[str, Any]]:
    """
    Load JSON records from a file.

    The file may contain:
    - one JSON object
    - an array of JSON objects
    """

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    with file_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(data, dict):
        return [data]

    if not isinstance(data, list):
        raise ValueError(
            f"Unsupported JSON contents in {file_path}"
        )

    if not all(
        isinstance(record, dict)
        for record in data
    ):
        raise ValueError(
            f"Expected a JSON array of objects in {file_path}"
        )

    return data


def integrate_command_history(
    telemetry_df: pd.DataFrame,
    command_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Attach the most recent command for the same satellite
    that occurred at or before each telemetry timestamp.
    """

    telemetry_required = {
        "satellite_id",
        "timestamp",
    }

    command_required = {
        "satellite_id",
        "command_name",
        "timestamp",
        "command_status",
    }

    missing_telemetry = (
        telemetry_required
        - set(telemetry_df.columns)
    )

    missing_command = (
        command_required
        - set(command_df.columns)
    )

    if missing_telemetry:
        raise ValueError(
            "Telemetry missing columns: "
            f"{sorted(missing_telemetry)}"
        )

    if missing_command:
        raise ValueError(
            "Command history missing columns: "
            f"{sorted(missing_command)}"
        )

    telemetry_df = telemetry_df.copy()
    command_df = command_df.copy()

    telemetry_df["timestamp"] = pd.to_datetime(
        telemetry_df["timestamp"],
        errors="coerce",
        utc=True,
    )

    command_df["timestamp"] = pd.to_datetime(
        command_df["timestamp"],
        errors="coerce",
        utc=True,
    )

    if telemetry_df["timestamp"].isna().any():
        bad_rows = telemetry_df.index[
            telemetry_df["timestamp"].isna()
        ].tolist()

        raise ValueError(
            "Telemetry contains invalid timestamps "
            f"at rows: {bad_rows}"
        )

    if command_df["timestamp"].isna().any():
        bad_rows = command_df.index[
            command_df["timestamp"].isna()
        ].tolist()

        raise ValueError(
            "Command history contains invalid timestamps "
            f"at rows: {bad_rows}"
        )

    if telemetry_df["satellite_id"].isna().any():
        raise ValueError("Telemetry contains missing satellite_id values.")

    if command_df["satellite_id"].isna().any():
        raise ValueError("Command history contains missing satellite_id values.")

    command_df = command_df.rename(
        columns={
            "command_name": "recent_command_name",
            "command_status": "recent_command_status",
            "timestamp": "recent_command_timestamp",
        }
    )

    telemetry_df = telemetry_df.sort_values(
        [
            "timestamp",
            "satellite_id",
        ]
    ).reset_index(drop=True)

    command_df = command_df.sort_values(
        [
            "recent_command_timestamp",
            "satellite_id",
        ]
    ).reset_index(drop=True)

    integrated = pd.merge_asof(
        telemetry_df,
        command_df[
            [
                "satellite_id",
                "recent_command_name",
                "recent_command_status",
                "recent_command_timestamp",
            ]
        ],
        left_on="timestamp",
        right_on="recent_command_timestamp",
        by="satellite_id",
        direction="backward",
        allow_exact_matches=True,
    )

    integrated["seconds_since_last_command"] = (
        integrated["timestamp"]
        - integrated["recent_command_timestamp"]
    ).dt.total_seconds()

    integrated["recent_command_name"] = (
        integrated["recent_command_name"]
        .fillna("no_previous_command")
    )

    integrated["recent_command_status"] = (
        integrated["recent_command_status"]
        .fillna("unknown")
    )

    return integrated


def prepare_dataset(
    telemetry_path: Path,
    command_history_path: Path,
    validation_reference_time: datetime | None = None,
) -> pd.DataFrame:
    """
    Load telemetry and command history and create
    the integrated prediction dataset.
    """

    telemetry_records = load_json_records(
        telemetry_path
    )

    command_records = load_json_records(
        command_history_path
    )

    envelope_flags = ["telemetry" in record for record in telemetry_records]
    if any(envelope_flags) and not all(envelope_flags):
        raise ValueError(
            "Telemetry input may not mix Version 0.1 envelopes with legacy flat records."
        )

    if all(envelope_flags):
        telemetry_records = [
            validate_and_adapt_housekeeping_record(
                record,
                reference_time=validation_reference_time,
            ).model_record
            for record in telemetry_records
        ]

    telemetry_df = pd.DataFrame(telemetry_records)

    command_df = pd.DataFrame(
        command_records
    )

    if telemetry_df.empty:
        raise ValueError(
            "Telemetry file contains no records."
        )

    if command_df.empty:
        raise ValueError(
            "Command history file contains no records."
        )

    return integrate_command_history(
        telemetry_df=telemetry_df,
        command_df=command_df,
    )


def validate_features(
    dataframe: pd.DataFrame,
    required_features: list[str],
) -> None:
    """
    Ensure all model features exist.

    Operational inference is strict: a missing column usually indicates
    a schema or integration error and must not silently become a prediction.
    """

    missing = (
        set(required_features)
        - set(dataframe.columns)
    )

    if missing:
        raise ValueError(
            "Prediction input is missing required model feature columns: "
            f"{sorted(missing)}"
        )

    invalid_numeric: dict[str, list[int]] = {}
    for column in NUMERICAL_FEATURES:
        values = pd.to_numeric(dataframe[column], errors="coerce")
        newly_invalid = values.isna() & dataframe[column].notna()
        if newly_invalid.any():
            invalid_numeric[column] = dataframe.index[newly_invalid].tolist()
        dataframe[column] = values

    if invalid_numeric:
        raise ValueError(
            "Prediction input contains non-numeric model values at rows: "
            f"{invalid_numeric}"
        )


def make_json_safe(
    value: Any,
) -> Any:
    """
    Convert pandas and NumPy values into JSON-safe values.
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass

    return value


def assess_telemetry(
    row: pd.Series,
) -> list[str]:
    """
    Generate human-readable telemetry observations.

    These rules explain the data. They do not change
    the Random Forest prediction.
    """

    assessment: list[str] = []

    battery_voltage = row.get(
        "battery_voltage"
    )

    bus_temperature = row.get(
        "bus_temperature_c"
    )

    payload_temperature = row.get(
        "payload_temperature_c"
    )

    reaction_wheel_rpm = row.get(
        "reaction_wheel_rpm"
    )

    downlink_rate = row.get(
        "downlink_rate_kbps"
    )

    solar_current = row.get(
        "solar_panel_current"
    )

    command_status = str(
        row.get(
            "recent_command_status",
            "unknown",
        )
    ).lower()

    if pd.notna(battery_voltage):
        if battery_voltage < 22:
            assessment.append(
                "Battery voltage is critically low."
            )
        elif battery_voltage < 25:
            assessment.append(
                "Battery voltage is below the nominal range."
            )
        else:
            assessment.append(
                "Battery voltage is within the expected range."
            )

    if pd.notna(bus_temperature):
        if bus_temperature >= 80:
            assessment.append(
                "Bus temperature is critically high."
            )
        elif bus_temperature >= 65:
            assessment.append(
                "Bus temperature is elevated."
            )
        else:
            assessment.append(
                "Bus temperature is within the expected range."
            )

    if pd.notna(payload_temperature):
        if payload_temperature >= 80:
            assessment.append(
                "Payload temperature is critically high."
            )
        elif payload_temperature >= 65:
            assessment.append(
                "Payload temperature is elevated."
            )
        else:
            assessment.append(
                "Payload temperature is within the expected range."
            )

    if pd.notna(reaction_wheel_rpm):
        if reaction_wheel_rpm >= 9000:
            assessment.append(
                "Reaction wheel speed is near a critical operating level."
            )
        elif reaction_wheel_rpm >= 7000:
            assessment.append(
                "Reaction wheel speed is elevated."
            )
        else:
            assessment.append(
                "Reaction wheel speed is within the expected range."
            )

    if pd.notna(downlink_rate):
        if downlink_rate < 100:
            assessment.append(
                "Downlink performance is severely reduced."
            )
        elif downlink_rate < 300:
            assessment.append(
                "Downlink performance is below nominal."
            )
        else:
            assessment.append(
                "Downlink performance is within the expected range."
            )

    if pd.notna(solar_current):
        if solar_current < 1:
            assessment.append(
                "Solar-panel current is critically low."
            )
        elif solar_current < 3:
            assessment.append(
                "Solar-panel current is below nominal."
            )
        else:
            assessment.append(
                "Solar-panel current is within the expected range."
            )

    if command_status in {
        "failed",
        "failure",
        "rejected",
        "timeout",
        "timed_out",
        "cancelled",
    }:
        assessment.append(
            "The most recent command did not complete successfully."
        )

    elif command_status in {
        "completed",
        "successful",
        "success",
        "executed",
    }:
        assessment.append(
            "The most recent command completed successfully."
        )

    if not assessment:
        assessment.append(
            "No telemetry assessment statements were generated."
        )

    return assessment


def create_recommendations(
    prediction: str,
    row: pd.Series,
) -> list[str]:
    """
    Create initial operator recommendations based on
    the prediction and telemetry values.
    """

    recommendations_by_class = {
        "Healthy": [
            "Continue nominal operations.",
            "Continue routine telemetry monitoring.",
            "No corrective action is currently required.",
        ],
        "Warning": [
            "Increase telemetry monitoring frequency.",
            "Review the telemetry parameters contributing to the warning state.",
            "Prepare corrective action if the condition continues.",
        ],
        "Degraded": [
            "Reduce nonessential payload or subsystem activity.",
            "Review recent commands and subsystem telemetry.",
            "Prepare to enter safe mode if conditions worsen.",
        ],
        "Critical": [
            "Notify the operator immediately.",
            "Consider entering emergency or safe mode.",
            "Suspend nonessential satellite operations.",
        ],
    }

    recommendations = list(
        recommendations_by_class.get(
            prediction,
            [
                "Review the prediction and telemetry manually."
            ],
        )
    )

    bus_temperature = row.get(
        "bus_temperature_c"
    )

    payload_temperature = row.get(
        "payload_temperature_c"
    )

    battery_voltage = row.get(
        "battery_voltage"
    )

    reaction_wheel_rpm = row.get(
        "reaction_wheel_rpm"
    )

    if (
        pd.notna(bus_temperature)
        and bus_temperature >= 65
    ):
        recommendations.append(
            "Review the thermal-control subsystem."
        )

    if (
        pd.notna(payload_temperature)
        and payload_temperature >= 65
    ):
        recommendations.append(
            "Reduce payload activity if temperature continues rising."
        )

    if (
        pd.notna(battery_voltage)
        and battery_voltage < 25
    ):
        recommendations.append(
            "Reduce nonessential power consumption."
        )

    if (
        pd.notna(reaction_wheel_rpm)
        and reaction_wheel_rpm >= 7000
    ):
        recommendations.append(
            "Review attitude-control system performance."
        )

    return list(
        dict.fromkeys(recommendations)
    )


def describe_data_quality(row: pd.Series) -> dict[str, Any]:
    """Describe missing model values that the saved pipeline may impute."""

    missing_features = [
        feature
        for feature in MODEL_FEATURES
        if pd.isna(row.get(feature))
    ]
    command_available = pd.notna(row.get("recent_command_timestamp"))

    notes: list[str] = list(row.get("input_validation_issues") or [])
    if missing_features:
        notes.append(
            "Missing model values were passed to the saved preprocessing "
            "pipeline for imputation."
        )
    if not command_available:
        notes.append("No preceding command was available for this sample.")

    upstream_status = row.get("input_data_quality", "complete")
    status = "degraded" if missing_features or upstream_status == "degraded" else "complete"

    return {
        "status": status,
        "missing_model_values": missing_features,
        "preceding_command_available": bool(command_available),
        "telemetry_adapter_version": row.get("telemetry_adapter_version"),
        "notes": notes,
    }


def load_history(
    history_path: Path,
) -> list[dict[str, Any]]:
    """
    Load previous prediction reports.
    """

    if not history_path.exists():
        return []

    try:
        return load_json_records(
            history_path
        )

    except (
        json.JSONDecodeError,
        ValueError,
    ):
        logging.warning(
            "Existing history file could not be read. "
            "Starting a new history."
        )

        return []


def determine_health_trend(
    satellite_id: str,
    current_prediction: str,
    current_timestamp: Any,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare the current health state with the latest
    previous state for the same satellite.
    """

    severity = {
        "Healthy": 0,
        "Warning": 1,
        "Degraded": 2,
        "Critical": 3,
    }

    current_dt = pd.to_datetime(current_timestamp, errors="coerce", utc=True)
    previous_records: list[tuple[pd.Timestamp, dict[str, Any]]] = []
    for record in history:
        if str(record.get("satellite_id")) != satellite_id:
            continue
        record_dt = pd.to_datetime(record.get("timestamp"), errors="coerce", utc=True)
        if pd.isna(record_dt):
            continue
        if pd.isna(current_dt) or record_dt < current_dt:
            previous_records.append((record_dt, record))

    if not previous_records:
        return {
            "previous_health_status": None,
            "trend": (
                "No previous prediction is available."
            ),
        }

    _, previous_record = max(previous_records, key=lambda item: item[0])

    previous_prediction = str(
        previous_record.get("prediction")
    )

    current_level = severity.get(
        current_prediction
    )

    previous_level = severity.get(
        previous_prediction
    )

    if (
        current_level is None
        or previous_level is None
    ):
        trend = (
            "Health trend could not be determined."
        )

    elif current_level > previous_level:
        trend = (
            f"Health has worsened from "
            f"{previous_prediction} to "
            f"{current_prediction}."
        )

    elif current_level < previous_level:
        trend = (
            f"Health has improved from "
            f"{previous_prediction} to "
            f"{current_prediction}."
        )

    else:
        trend = (
            f"Health remains {current_prediction}."
        )

    return {
        "previous_health_status": (
            previous_prediction
        ),
        "trend": trend,
    }


def build_report(
    records_df: pd.DataFrame,
    model: Any,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Run model predictions and build complete health reports.
    """

    validate_features(
        dataframe=records_df,
        required_features=MODEL_FEATURES,
    )

    model_input = records_df[
        MODEL_FEATURES
    ].copy()

    predictions = model.predict(
        model_input
    )

    unexpected_predictions = sorted(
        {str(value) for value in predictions} - set(HEALTH_CLASSES)
    )
    if unexpected_predictions:
        raise ValueError(
            "Model returned unsupported health class(es): "
            f"{unexpected_predictions}"
        )

    probabilities = None
    classes: list[Any] = []

    if hasattr(
        model,
        "predict_proba",
    ):
        probabilities = model.predict_proba(
            model_input
        )

        classes = list(
            model.classes_
        )

        unexpected_classes = sorted(
            {str(value) for value in classes} - set(HEALTH_CLASSES)
        )
        if unexpected_classes:
            raise ValueError(
                "Model exposes unsupported health class(es): "
                f"{unexpected_classes}"
            )

    report: list[dict[str, Any]] = []
    trend_history = list(history)
    report_generated_at = datetime.now(timezone.utc).isoformat()

    for index, prediction_value in enumerate(
        predictions
    ):
        row = records_df.iloc[index]

        prediction = str(
            prediction_value
        )

        satellite_id = str(
            row.get("satellite_id")
        )

        health_trend = determine_health_trend(
            satellite_id=satellite_id,
            current_prediction=prediction,
            current_timestamp=row.get("timestamp"),
            history=trend_history,
        )

        entry: dict[str, Any] = {
            "report_generated_at": report_generated_at,
            "satellite_id": satellite_id,
            "timestamp": make_json_safe(
                row.get("timestamp")
            ),
            "prediction": prediction,
            "recent_command": {
                "name": make_json_safe(
                    row.get(
                        "recent_command_name"
                    )
                ),
                "status": make_json_safe(
                    row.get(
                        "recent_command_status"
                    )
                ),
                "timestamp": make_json_safe(
                    row.get(
                        "recent_command_timestamp"
                    )
                ),
                "seconds_since_command": (
                    make_json_safe(
                        row.get(
                            "seconds_since_last_command"
                        )
                    )
                ),
            },
            "telemetry": {
                "solar_panel_current": make_json_safe(
                    row.get(
                        "solar_panel_current"
                    )
                ),
                "bus_temperature_c": make_json_safe(
                    row.get(
                        "bus_temperature_c"
                    )
                ),
                "payload_temperature_c": make_json_safe(
                    row.get(
                        "payload_temperature_c"
                    )
                ),
                "reaction_wheel_rpm": make_json_safe(
                    row.get(
                        "reaction_wheel_rpm"
                    )
                ),
                "downlink_rate_kbps": make_json_safe(
                    row.get(
                        "downlink_rate_kbps"
                    )
                ),
                "battery_voltage": make_json_safe(
                    row.get(
                        "battery_voltage"
                    )
                ),
                "battery_current": make_json_safe(
                    row.get(
                        "battery_current"
                    )
                ),
                "mode": make_json_safe(
                    row.get("mode")
                ),
            },
            "assessment": assess_telemetry(
                row
            ),
            "data_quality": describe_data_quality(row),
            "recommendations": (
                create_recommendations(
                    prediction=prediction,
                    row=row,
                )
            ),
            "recommendation_scope": (
                "preliminary_health_advisory_not_operator_coa"
            ),
            "health_trend": health_trend,
        }

        if probabilities is not None:
            class_probability_map = {
                str(class_name): float(
                    probabilities[
                        index,
                        class_index,
                    ]
                )
                for class_index, class_name
                in enumerate(classes)
            }

            entry[
                "class_probabilities"
            ] = class_probability_map

            entry[
                "predicted_probability"
            ] = class_probability_map[
                prediction
            ]

            entry["probability_interpretation"] = (
                "uncalibrated_random_forest_vote_fraction"
            )

        else:
            entry["class_probabilities"] = {}
            entry["predicted_probability"] = None
            entry["probability_interpretation"] = "unavailable"

        report.append(
            entry
        )
        trend_history.append(entry)

    return report


def print_report(
    report: list[dict[str, Any]],
) -> None:
    """
    Print health reports in the VS Code terminal.
    """

    for result in report:
        print(
            "\n"
            + "=" * 60
        )

        print(
            "SATELLITE HEALTH REPORT"
        )

        print(
            "=" * 60
        )

        print(
            f"Satellite: "
            f"{result['satellite_id']}"
        )

        print(
            f"Timestamp: "
            f"{result['timestamp']}"
        )

        print(
            "Predicted health: "
            f"{result['prediction']}"
        )

        if (
            "predicted_probability"
            in result
        ):
            print(
                "Prediction confidence: "
                f"{result['predicted_probability']:.2%}"
            )

        print(
            "\nRecent Command"
        )

        print(
            "-" * 60
        )

        recent_command = result[
            "recent_command"
        ]

        print(
            f"Name: "
            f"{recent_command['name']}"
        )

        print(
            f"Status: "
            f"{recent_command['status']}"
        )

        print(
            "Command timestamp: "
            f"{recent_command['timestamp']}"
        )

        print(
            "Seconds since command: "
            f"{recent_command['seconds_since_command']}"
        )

        if (
            "class_probabilities"
            in result
        ):
            print(
                "\nClass Probabilities"
            )

            print(
                "-" * 60
            )

            sorted_probabilities = sorted(
                result[
                    "class_probabilities"
                ].items(),
                key=lambda item: item[1],
                reverse=True,
            )

            for (
                class_name,
                probability,
            ) in sorted_probabilities:
                print(
                    f"{class_name:<12}: "
                    f"{probability:.2%}"
                )

        print(
            "\nTelemetry Assessment"
        )

        print(
            "-" * 60
        )

        for statement in result[
            "assessment"
        ]:
            print(
                f"- {statement}"
            )

        print(
            "\nHealth Trend"
        )

        print(
            "-" * 60
        )

        print(
            "Previous health: "
            f"{result['health_trend']['previous_health_status']}"
        )

        print(
            "Trend: "
            f"{result['health_trend']['trend']}"
        )

        print(
            "\nRecommendations"
        )

        print(
            "-" * 60
        )

        for recommendation in result[
            "recommendations"
        ]:
            print(
                f"- {recommendation}"
            )

        print(
            "\nRaw Telemetry"
        )

        print(
            "-" * 60
        )

        for (
            telemetry_name,
            telemetry_value,
        ) in result[
            "telemetry"
        ].items():
            print(
                f"{telemetry_name:<24}: "
                f"{telemetry_value}"
            )

        print(
            "=" * 60
        )


def save_json(
    records: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """
    Save records to a JSON file.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            records,
            file,
            indent=2,
            default=str,
        )


def validate_json_file(
    file_path: Path,
    schema_path: Path,
) -> None:
    """
    Validate a JSON file against a JSON Schema (Draft-07).

    If `jsonschema` is not installed the function logs a warning and
    skips validation.
    """

    try:
        from jsonschema import Draft7Validator
    except Exception:
        logging.warning(
            "jsonschema not installed; skipping schema validation."
            " Install with: py -3 -m pip install jsonschema"
        )
        return

    if not schema_path.exists():
        logging.warning(
            "Schema file not found; skipping validation: %s",
            schema_path,
        )
        return

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)

    if errors:
        for e in errors:
            path = "->".join(map(str, e.path)) if e.path else "(root)"
            logging.error("Schema validation error: %s at %s", e.message, path)

        raise ValueError(f"Validation failed: {len(errors)} schema error(s)")

    logging.info("Validation successful: output matches schema %s", schema_path)


def build_ml_records(report: list[dict[str, Any]], ml_format: str = "full") -> list[dict[str, Any]]:
    """Flatten report entries into ML-friendly records.

    Modes:
    - "full": include telemetry, recent command fields, prediction, predicted_probability, and class probabilities.
    - "minimal": include only the model features (`MODEL_FEATURES`), plus `satellite_id`, `timestamp`, `prediction`, and `predicted_probability`.
    """

    ml: list[dict[str, Any]] = []

    for r in report:
        rec: dict[str, Any] = {}

        # Always include these meta fields
        rec["satellite_id"] = r.get("satellite_id")
        rec["timestamp"] = r.get("timestamp")
        rec["prediction"] = r.get("prediction")
        rec["predicted_probability"] = r.get("predicted_probability")

        telemetry = r.get("telemetry", {})
        recent = r.get("recent_command", {})

        if ml_format == "minimal":
            # Minimal: only model features
            for feat in MODEL_FEATURES:
                if feat in telemetry:
                    rec[feat] = telemetry.get(feat)
                elif feat == "recent_command_name":
                    rec[feat] = recent.get("name")
                elif feat == "recent_command_status":
                    rec[feat] = recent.get("status")
                elif feat == "seconds_since_last_command":
                    rec[feat] = recent.get("seconds_since_command")
                else:
                    # top-level or missing
                    rec[feat] = r.get(feat, telemetry.get(feat))

            ml.append(rec)
            continue

        # Full format: include telemetry flattened
        for k, v in telemetry.items():
            rec[k] = v

        rec["recent_command_name"] = recent.get("name")
        rec["recent_command_status"] = recent.get("status")
        rec["recent_command_timestamp"] = recent.get("timestamp")
        rec["seconds_since_command"] = recent.get("seconds_since_command")

        class_probabilities = r.get("class_probabilities", {})
        rec["class_probabilities"] = class_probabilities
        rec["probability_healthy"] = class_probabilities.get("Healthy")
        rec["probability_warning"] = class_probabilities.get("Warning")
        rec["probability_degraded"] = class_probabilities.get("Degraded")
        rec["probability_critical"] = class_probabilities.get("Critical")

        ml.append(rec)

    return ml


def save_report(
    report: list[dict[str, Any]],
    output_path: Path,
    validate: bool = True,
    ml_format: str = "full",
    model_metadata: dict[str, Any] | None = None,
) -> Path:
    """Save the report as a JSON object containing both the
    human `report` and flattened `ml_records` for downstream ML.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # JSON-only output
    ml = build_ml_records(report, ml_format=ml_format)
    out_obj = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_metadata": model_metadata or {},
        "report": report,
        "ml_records": ml,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2, default=str)

    logging.info("Wrote JSON report with ml_records to %s", output_path.resolve())

    # Optionally validate the produced JSON against the shipped schema.
    if validate:
        try:
            validate_json_file(output_path, DEFAULT_SCHEMA_PATH)
        except Exception as exc:  # validation errors are raised as exceptions
            logging.exception("Schema validation failed: %s", exc)
            raise

    return output_path


def parse_args() -> argparse.Namespace:
    """
    Read optional paths from the command line.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Generate satellite health predictions "
            "from new telemetry using a trained "
            "Random Forest model."
        )
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=(
            "Path to the trained "
            "satellite-health model."
        ),
    )

    parser.add_argument(
        "--telemetry",
        type=Path,
        default=DEFAULT_TELEMETRY_PATH,
        help=(
            "Path to the new telemetry JSON file."
        ),
    )

    parser.add_argument(
        "--command-history",
        type=Path,
        default=DEFAULT_COMMAND_HISTORY_PATH,
        help=(
            "Path to the command-history JSON file."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=(
            "Path where the current prediction report (JSON) will be written."
        ),
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help=(
            "Path where cumulative prediction "
            "history will be stored."
        ),
    )

    parser.add_argument(
        "--no-validate",
        action="store_true",
        help=(
            "Skip JSON Schema validation after writing the JSON output."
        ),
    )

    parser.add_argument(
        "--ml-format",
        choices=("full", "minimal"),
        default="full",
        help=(
            "Format for the flattened ML records embedded in the JSON."
            " 'full' includes class probabilities and all telemetry fields;"
            " 'minimal' includes only the model features, prediction, and probability."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """
    Main health-monitor workflow.
    """

    args = parse_args()

    logging.basicConfig(
        level=(logging.DEBUG if args.debug else logging.INFO),
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    print(
        f"Loading model from: "
        f"{args.model}"
    )

    if not args.model.exists():
        raise FileNotFoundError(
            f"Model file not found: "
            f"{args.model}"
        )

    model = joblib.load(
        args.model
    )

    print(
        f"Loading telemetry from: "
        f"{args.telemetry}"
    )

    print(
        "Loading command history from: "
        f"{args.command_history}"
    )

    dataset = prepare_dataset(
        telemetry_path=args.telemetry,
        command_history_path=(
            args.command_history
        ),
    )

    print(
        "\nIntegrated incoming records:"
    )

    print(
        dataset[
            [
                column
                for column in [
                    "satellite_id",
                    "timestamp",
                    "recent_command_name",
                    "recent_command_status",
                    "seconds_since_last_command",
                ]
                if column
                in dataset.columns
            ]
        ]
    )

    history = load_history(
        args.history
    )

    print(
        "\nRunning predictions..."
    )

    report = build_report(
        records_df=dataset,
        model=model,
        history=history,
    )

    print_report(
        report
    )

    written_report_path = save_report(
        report=report,
        output_path=args.output,
        validate=(not args.no_validate),
        ml_format=args.ml_format,
        model_metadata=getattr(model, "health_model_metadata_", {}),
    )

    print(
    "\nCurrent prediction report written to: "
    f"{written_report_path.resolve()}"
    )

    updated_history = (
        history
        + report
    )

    save_json(records=updated_history, output_path=args.history)

    print(
        "\nCurrent prediction report written to: "
        f"{args.output.resolve()}"
    )

    print(
        "Prediction history written to: "
        f"{args.history.resolve()}"
    )


if __name__ == "__main__":
    main()
