"""Adapt validated housekeeping telemetry to the legacy health-model contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from common.telemetry_validation import ValidationResult, validate_telemetry_record


ADAPTER_VERSION = "0.1.0"

CANONICAL_MODEL_VERSION = "0.2.0"


class TelemetryAdapterError(ValueError):
    """Raised when an invalid housekeeping record cannot be adapted."""

    def __init__(self, validation: ValidationResult) -> None:
        self.validation = validation
        messages = [
            issue.message
            for issue in validation.issues
            if issue.severity == "error"
        ]
        super().__init__(
            "Invalid housekeeping telemetry: " + "; ".join(messages)
        )


@dataclass(frozen=True)
class AdaptedTelemetry:
    """Legacy model record plus its validation and mapping provenance."""

    model_record: dict[str, Any]
    validation: ValidationResult
    adapter_version: str
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_record": self.model_record,
            "validation": self.validation.to_dict(),
            "adapter_version": self.adapter_version,
            "assumptions": list(self.assumptions),
        }


def _maximum_absolute_wheel_speed(telemetry: dict[str, Any]) -> float | None:
    speeds = [
        telemetry.get("reaction_wheel_1_speed_rpm"),
        telemetry.get("reaction_wheel_2_speed_rpm"),
        telemetry.get("reaction_wheel_3_speed_rpm"),
    ]
    available = [abs(float(speed)) for speed in speeds if speed is not None]
    return max(available) if available else None


def adapt_housekeeping_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert an already validated envelope to legacy health feature names.

    Command-history features are intentionally omitted. They must be attached
    afterward by the existing timestamp-aware command integration function.
    """

    telemetry = record["telemetry"]
    battery_current = telemetry.get("battery_current_a")

    return {
        "satellite_id": record["satellite_id"],
        "timestamp": record["timestamp"],
        "solar_panel_current": telemetry.get("solar_array_current_a"),
        "bus_temperature_c": telemetry.get("flight_computer_temperature_c"),
        "payload_temperature_c": telemetry.get("payload_temperature_c"),
        "reaction_wheel_rpm": _maximum_absolute_wheel_speed(telemetry),
        "downlink_rate_kbps": telemetry.get("downlink_rate_kbps"),
        "battery_voltage": telemetry.get("battery_voltage_v"),
        "battery_current": (
            abs(float(battery_current)) if battery_current is not None else None
        ),
        "mode": record["spacecraft_mode"],
    }


def validate_and_adapt_housekeeping_record(
    record: dict[str, Any],
    *,
    reference_time: datetime | None = None,
    schema: dict[str, Any] | None = None,
    dictionary: dict[str, Any] | None = None,
) -> AdaptedTelemetry:
    """Validate one envelope and adapt it only when it has no errors."""

    validation = validate_telemetry_record(
        record,
        reference_time=reference_time,
        schema=schema,
        dictionary=dictionary,
    )
    if not validation.valid:
        raise TelemetryAdapterError(validation)

    model_record = adapt_housekeeping_record(record)
    model_record["input_data_quality"] = validation.data_quality
    model_record["input_validation_issues"] = [
        issue.message for issue in validation.issues
    ]
    model_record["telemetry_adapter_version"] = ADAPTER_VERSION

    return AdaptedTelemetry(
        model_record=model_record,
        validation=validation,
        adapter_version=ADAPTER_VERSION,
        assumptions=(
            "flight_computer_temperature_c is used as the legacy bus_temperature_c feature",
            "maximum absolute wheel speed is used as the legacy reaction_wheel_rpm feature",
            "absolute battery current is used because the legacy model was trained on unsigned magnitudes",
        ),
    )


def validate_and_prepare_canonical_record(
    record: dict[str, Any],
    *,
    reference_time: datetime | None = None,
    schema: dict[str, Any] | None = None,
    dictionary: dict[str, Any] | None = None,
) -> AdaptedTelemetry:
    """Validate and flatten canonical fields without legacy transformations."""

    validation = validate_telemetry_record(
        record,
        reference_time=reference_time,
        schema=schema,
        dictionary=dictionary,
    )
    if not validation.valid:
        raise TelemetryAdapterError(validation)

    telemetry = record["telemetry"]
    canonical_fields = (
        "battery_state_of_charge_pct",
        "solar_array_voltage_v",
        "solar_array_current_a",
        "flight_computer_temperature_c",
        "payload_temperature_c",
        "reaction_wheel_1_speed_rpm",
        "reaction_wheel_2_speed_rpm",
        "reaction_wheel_3_speed_rpm",
        "downlink_rate_kbps",
        "battery_voltage_v",
        "battery_current_a",
    )
    model_record = {
        "satellite_id": record["satellite_id"],
        "timestamp": record["timestamp"],
        "spacecraft_mode": record["spacecraft_mode"],
        **telemetry,
        "eclipse_state": (record.get("operational_context") or {}).get(
            "eclipse_state", "unknown"
        ),
        "solar_array_configuration": (
            record.get("operational_context") or {}
        ).get("solar_array_configuration", "unknown"),
        "battery_current_sign_convention": (
            record.get("operational_context") or {}
        ).get("battery_current_sign_convention", "unknown"),
        "communications_pass_state": (
            record.get("operational_context") or {}
        ).get("communications_pass_state", "unknown"),
        **{field: telemetry.get(field) for field in canonical_fields},
        "input_data_quality": validation.data_quality,
        "input_validation_issues": [issue.message for issue in validation.issues],
        "telemetry_contract_version": record["schema_version"],
    }
    return AdaptedTelemetry(
        model_record=model_record,
        validation=validation,
        adapter_version=CANONICAL_MODEL_VERSION,
        assumptions=(),
    )
