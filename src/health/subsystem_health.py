"""Explainable prototype health rules for non-power spacecraft subsystems."""

from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd


SEVERITY = {"Unknown": -1, "Healthy": 0, "Warning": 1, "Degraded": 2, "Critical": 3}


def _number(value: Any) -> float | None:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None


def _finding(code: str, status: str, parameter: str, value: Any, threshold: str, message: str) -> dict[str, Any]:
    return {
        "fault_code": code,
        "status": status,
        "parameter": parameter,
        "observed_value": value,
        "threshold": threshold,
        "message": message,
    }


def _result(
    findings: list[dict[str, Any]],
    *,
    method: str,
    trends: dict[str, Any] | None = None,
    context_notes: list[str] | None = None,
    quality: str = "complete",
    available_measurements: int = 1,
    required_measurements: int = 1,
) -> dict[str, Any]:
    status = max(
        (item["status"] for item in findings),
        key=lambda value: SEVERITY[value],
        default="Healthy",
    )
    if available_measurements == 0:
        status = "Unknown"
    notes = context_notes or []
    confidence = 0.0 if status == "Unknown" else 0.9
    if notes:
        confidence = 0.65
    if quality == "degraded":
        confidence = min(confidence, 0.4)
    return {
        "status": status,
        "confidence": confidence,
        "method": method,
        "fault_codes": [item["fault_code"] for item in findings],
        "evidence": findings,
        "trends": trends or {},
        "context_notes": notes,
        "limitations": [
            "Thresholds are prototype assumptions and are not approved spacecraft limits."
        ],
        "data_completeness": {
            "available_measurements": available_measurements,
            "required_measurements": required_measurements,
            "sufficient": available_measurements > 0,
        },
    }


def _rate(row: Mapping[str, Any], previous: Mapping[str, Any] | None, field: str) -> tuple[float | None, float | None]:
    if previous is None:
        return None, None
    now_time = pd.to_datetime(row.get("timestamp"), errors="coerce", utc=True)
    before_time = pd.to_datetime(previous.get("timestamp"), errors="coerce", utc=True)
    now = _number(row.get(field))
    before = _number(previous.get(field))
    if pd.isna(now_time) or pd.isna(before_time) or now is None or before is None:
        return None, None
    seconds = (now_time - before_time).total_seconds()
    if seconds <= 0:
        return None, None
    return (now - before) / (seconds / 3600), seconds


def assess_thermal(row: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    trends: dict[str, Any] = {}
    for field, label in (
        ("flight_computer_temperature_c", "FLIGHT_COMPUTER"),
        ("radiator_temperature_c", "RADIATOR"),
    ):
        value = _number(row.get(field))
        if value is not None:
            if value >= 90:
                findings.append(_finding(f"THM_{label}_OVERTEMP_CRITICAL", "Critical", field, value, ">= 90 C", "Temperature exceeds the prototype critical threshold."))
            elif value >= 70:
                findings.append(_finding(f"THM_{label}_OVERTEMP_WARNING", "Warning", field, value, ">= 70 C", "Temperature exceeds the prototype warning threshold."))
        rate, seconds = _rate(row, previous, field)
        trends[f"{field}_rate_c_per_hour"] = rate
        if rate is not None and rate > 5:
            findings.append(_finding(f"THM_{label}_RISING_FAST", "Warning", field, rate, "> 5 C/hour", "Temperature is rising faster than the prototype trend threshold."))
        if seconds is not None:
            trends["interval_seconds"] = seconds
    available = sum(_number(row.get(field)) is not None for field in (
        "flight_computer_temperature_c", "radiator_temperature_c"
    ))
    return _result(findings, method="prototype_thermal_rules", trends=trends, quality=str(row.get("input_data_quality", "complete")), available_measurements=available, required_measurements=2)


def assess_payload(row: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    temperature = _number(row.get("payload_temperature_c"))
    if temperature is not None:
        if temperature >= 85:
            findings.append(_finding("PAYLOAD_OVERTEMP_CRITICAL", "Critical", "payload_temperature_c", temperature, ">= 85 C", "Payload temperature exceeds the prototype critical threshold."))
        elif temperature >= 65:
            findings.append(_finding("PAYLOAD_OVERTEMP_WARNING", "Warning", "payload_temperature_c", temperature, ">= 65 C", "Payload temperature exceeds the prototype warning threshold."))
    rate, seconds = _rate(row, previous, "payload_temperature_c")
    if rate is not None and rate > 5:
        findings.append(_finding("PAYLOAD_TEMPERATURE_RISING_FAST", "Warning", "payload_temperature_c", rate, "> 5 C/hour", "Payload temperature is rising rapidly."))
    return _result(findings, method="prototype_payload_rules", trends={"temperature_rate_c_per_hour": rate, "interval_seconds": seconds}, quality=str(row.get("input_data_quality", "complete")), available_measurements=int(temperature is not None))


def assess_adcs(row: Mapping[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    wheels = [_number(row.get(f"reaction_wheel_{index}_speed_rpm")) for index in range(1, 4)]
    for index, speed in enumerate(wheels, 1):
        if speed is None:
            continue
        magnitude = abs(speed)
        if magnitude >= 9500:
            findings.append(_finding("ADCS_WHEEL_OVERSPEED_CRITICAL", "Critical", f"reaction_wheel_{index}_speed_rpm", speed, "absolute value >= 9500 rpm", "Reaction wheel exceeds the prototype critical speed."))
        elif magnitude >= 7500:
            findings.append(_finding("ADCS_WHEEL_SPEED_WARNING", "Warning", f"reaction_wheel_{index}_speed_rpm", speed, "absolute value >= 7500 rpm", "Reaction wheel exceeds the prototype warning speed."))
    gyro = [_number(row.get(f"gyro_{axis}_rate_deg_s")) for axis in "xyz"]
    if all(value is not None for value in gyro):
        magnitude = math.sqrt(sum(value * value for value in gyro))
        if magnitude >= 50:
            findings.append(_finding("ADCS_BODY_RATE_CRITICAL", "Critical", "gyro_vector", magnitude, ">= 50 deg/s", "Body-rate magnitude exceeds the prototype critical threshold."))
        elif magnitude >= 10:
            findings.append(_finding("ADCS_BODY_RATE_WARNING", "Warning", "gyro_vector", magnitude, ">= 10 deg/s", "Body-rate magnitude exceeds the prototype warning threshold."))
    available = sum(value is not None for value in wheels + gyro)
    return _result(findings, method="prototype_adcs_rules", quality=str(row.get("input_data_quality", "complete")), available_measurements=available, required_measurements=6)


def assess_communications(row: Mapping[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    notes: list[str] = []
    rate = _number(row.get("downlink_rate_kbps"))
    pass_state = str(row.get("communications_pass_state", "unknown"))
    if rate is not None and rate < 100:
        if pass_state == "active":
            findings.append(_finding("COMMS_DOWNLINK_CRITICAL", "Critical", "downlink_rate_kbps", rate, "< 100 kbps during active pass", "Downlink is critically low during an active communications pass."))
        elif pass_state == "inactive":
            notes.append("Low downlink rate is expected outside a communications pass.")
        else:
            findings.append(_finding("COMMS_DOWNLINK_LOW_CONTEXT_UNKNOWN", "Warning", "downlink_rate_kbps", rate, "< 100 kbps", "Downlink is low but pass state is unknown."))
            notes.append("Communications-pass state is required for fault isolation.")
    elif rate is not None and rate < 300 and pass_state == "active":
        findings.append(_finding("COMMS_DOWNLINK_WARNING", "Warning", "downlink_rate_kbps", rate, "< 300 kbps during active pass", "Downlink is below the prototype active-pass threshold."))
    return _result(findings, method="prototype_communications_rules", context_notes=notes, quality=str(row.get("input_data_quality", "complete")), available_measurements=int(rate is not None))


def assess_cdh(row: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    memory = _number(row.get("memory_usage_pct"))
    if memory is not None:
        if memory >= 95:
            findings.append(_finding("CDH_MEMORY_CRITICAL", "Critical", "memory_usage_pct", memory, ">= 95%", "Memory usage exceeds the prototype critical threshold."))
        elif memory >= 80:
            findings.append(_finding("CDH_MEMORY_WARNING", "Warning", "memory_usage_pct", memory, ">= 80%", "Memory usage exceeds the prototype warning threshold."))
    errors = _number(row.get("memory_corrected_error_count"))
    previous_errors = _number(previous.get("memory_corrected_error_count")) if previous else None
    delta = errors - previous_errors if errors is not None and previous_errors is not None else None
    if delta is not None and delta > 0:
        findings.append(_finding("CDH_CORRECTED_ERRORS_INCREASING", "Warning", "memory_corrected_error_count", delta, "> 0 new errors", "Corrected memory-error counter increased."))
    available = sum(value is not None for value in (memory, errors))
    return _result(findings, method="prototype_cdh_rules", trends={"corrected_error_count_delta": delta}, quality=str(row.get("input_data_quality", "complete")), available_measurements=available, required_measurements=2)


def assess_propulsion(row: Mapping[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    remaining = _number(row.get("propellant_remaining_pct"))
    if remaining is not None:
        if remaining < 5:
            findings.append(_finding("PROP_PROPELLANT_CRITICAL", "Critical", "propellant_remaining_pct", remaining, "< 5%", "Propellant estimate is below the prototype critical threshold."))
        elif remaining < 15:
            findings.append(_finding("PROP_PROPELLANT_WARNING", "Warning", "propellant_remaining_pct", remaining, "< 15%", "Propellant estimate is below the prototype warning threshold."))
    firing = row.get("thruster_firing")
    pulse = _number(row.get("thruster_pulse_width_ms"))
    if firing is True and (pulse is None or pulse <= 0):
        findings.append(_finding("PROP_THRUSTER_STATE_INCONSISTENT", "Warning", "thruster_pulse_width_ms", pulse, "> 0 while firing", "Thruster firing state lacks a positive pulse width."))
    available = sum(value is not None for value in (remaining, pulse)) + int(firing is not None)
    return _result(findings, method="prototype_propulsion_rules", quality=str(row.get("input_data_quality", "complete")), available_measurements=available, required_measurements=3)


def assess_timing(row: Mapping[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for field, warning, critical, code in (
        ("time_sync_offset_ms", 100, 1000, "TIME_SYNC_OFFSET"),
        ("clock_drift_us_day", 100, 1000, "TIME_CLOCK_DRIFT"),
    ):
        value = _number(row.get(field))
        if value is None:
            continue
        if abs(value) >= critical:
            findings.append(_finding(f"{code}_CRITICAL", "Critical", field, value, f"absolute value >= {critical}", "Timing value exceeds the prototype critical threshold."))
        elif abs(value) >= warning:
            findings.append(_finding(f"{code}_WARNING", "Warning", field, value, f"absolute value >= {warning}", "Timing value exceeds the prototype warning threshold."))
    available = sum(_number(row.get(field)) is not None for field in (
        "time_sync_offset_ms", "clock_drift_us_day"
    ))
    return _result(findings, method="prototype_timing_rules", quality=str(row.get("input_data_quality", "complete")), available_measurements=available, required_measurements=2)


def assess_command_control(row: Mapping[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    depth = _number(row.get("command_queue_depth"))
    if depth is not None:
        if depth >= 50:
            findings.append(_finding("CMD_QUEUE_CRITICAL", "Critical", "command_queue_depth", depth, ">= 50", "Command queue exceeds the prototype critical depth."))
        elif depth >= 20:
            findings.append(_finding("CMD_QUEUE_WARNING", "Warning", "command_queue_depth", depth, ">= 20", "Command queue exceeds the prototype warning depth."))
    status = str(row.get("latest_command_status") or row.get("recent_command_status") or "unknown").lower()
    if status in {"failed", "timed_out", "rejected"}:
        findings.append(_finding("CMD_RECENT_FAILURE", "Warning", "latest_command_status", status, "successful", "Most recent command did not complete successfully."))
    available = int(depth is not None) + int(status != "unknown")
    return _result(findings, method="prototype_command_control_rules", quality=str(row.get("input_data_quality", "complete")), available_measurements=available, required_measurements=2)


def assess_non_power_subsystems(row: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return every non-power subsystem assessment represented by the contract."""

    return {
        "thermal": assess_thermal(row, previous),
        "payload": assess_payload(row, previous),
        "adcs": assess_adcs(row),
        "communications": assess_communications(row),
        "cdh": assess_cdh(row, previous),
        "propulsion": assess_propulsion(row),
        "timing": assess_timing(row),
        "command_control": assess_command_control(row),
    }
