"""Explainable prototype electrical-power health assessment."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


SEVERITY = {"Unknown": -1, "Healthy": 0, "Warning": 1, "Degraded": 2, "Critical": 3}


def _number(value: Any) -> float | None:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None


def _finding(
    code: str, status: str, parameter: str, value: float, threshold: str, message: str
) -> dict[str, Any]:
    return {
        "fault_code": code,
        "status": status,
        "parameter": parameter,
        "observed_value": value,
        "threshold": threshold,
        "message": message,
    }


def assess_power_subsystem(
    row: Mapping[str, Any], previous_row: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Assess power telemetry using transparent, unapproved prototype rules."""

    voltage = _number(row.get("battery_voltage_v"))
    current = _number(row.get("battery_current_a"))
    state_of_charge = _number(row.get("battery_state_of_charge_pct"))
    solar_voltage = _number(row.get("solar_array_voltage_v"))
    solar_current = _number(row.get("solar_array_current_a"))
    eclipse_state = str(row.get("eclipse_state", "unknown"))
    array_configuration = str(row.get("solar_array_configuration", "unknown"))
    sign_convention = str(row.get("battery_current_sign_convention", "unknown"))
    findings: list[dict[str, Any]] = []
    available_measurements = sum(
        value is not None
        for value in (voltage, current, state_of_charge, solar_voltage, solar_current)
    )

    if voltage is not None:
        if voltage < 22:
            findings.append(_finding(
                "PWR_BATTERY_UNDERVOLTAGE_CRITICAL", "Critical",
                "battery_voltage_v", voltage, "< 22 V",
                "Battery voltage is below the prototype critical threshold.",
            ))
        elif voltage < 25:
            findings.append(_finding(
                "PWR_BATTERY_UNDERVOLTAGE_WARNING", "Warning",
                "battery_voltage_v", voltage, "< 25 V",
                "Battery voltage is below the prototype warning threshold.",
            ))

    if current is not None:
        magnitude = abs(current)
        if magnitude > 9:
            findings.append(_finding(
                "PWR_BATTERY_OVERCURRENT_CRITICAL", "Critical",
                "battery_current_a", current, "absolute value > 9 A",
                "Battery-current magnitude exceeds the prototype critical threshold.",
            ))
        elif magnitude > 7:
            findings.append(_finding(
                "PWR_BATTERY_OVERCURRENT_WARNING", "Warning",
                "battery_current_a", current, "absolute value > 7 A",
                "Battery-current magnitude exceeds the prototype warning threshold.",
            ))

    if state_of_charge is not None:
        if state_of_charge < 15:
            findings.append(_finding(
                "PWR_BATTERY_SOC_CRITICAL", "Critical",
                "battery_state_of_charge_pct", state_of_charge, "< 15%",
                "Battery state of charge is below the prototype critical threshold.",
            ))
        elif state_of_charge < 30:
            findings.append(_finding(
                "PWR_BATTERY_SOC_WARNING", "Warning",
                "battery_state_of_charge_pct", state_of_charge, "< 30%",
                "Battery state of charge is below the prototype warning threshold.",
            ))

    context_notes: list[str] = []
    if solar_current is not None and solar_current < 1:
        if eclipse_state == "eclipse" or array_configuration == "stowed":
            context_notes.append(
                "Low solar-array current is explained by eclipse or a stowed array."
            )
        elif eclipse_state == "sunlight" and array_configuration == "deployed":
            findings.append(_finding(
                "PWR_SOLAR_CURRENT_LOW_IN_SUNLIGHT", "Critical",
                "solar_array_current_a", solar_current, "< 1 A",
                "Solar-array current is critically low while sunlit and deployed.",
            ))
        else:
            findings.append(_finding(
                "PWR_SOLAR_CURRENT_LOW_CONTEXT_UNKNOWN", "Warning",
                "solar_array_current_a", solar_current, "< 1 A",
                "Solar-array current is low, but operational context is incomplete.",
            ))
            context_notes.append("Eclipse state or array configuration was inconclusive.")

    if (
        solar_voltage is not None
        and solar_voltage < 10
        and eclipse_state == "sunlight"
        and array_configuration == "deployed"
    ):
        findings.append(_finding(
            "PWR_SOLAR_VOLTAGE_LOW_IN_SUNLIGHT", "Critical",
            "solar_array_voltage_v", solar_voltage, "< 10 V",
            "Solar-array voltage is critically low while sunlit and deployed.",
        ))

    trends: dict[str, Any] = {
        "battery_voltage_rate_v_per_hour": None,
        "battery_current_rate_a_per_hour": None,
        "solar_current_rate_a_per_hour": None,
        "interval_seconds": None,
    }
    if previous_row is not None:
        current_time = pd.to_datetime(row.get("timestamp"), errors="coerce", utc=True)
        previous_time = pd.to_datetime(previous_row.get("timestamp"), errors="coerce", utc=True)
        if pd.notna(current_time) and pd.notna(previous_time):
            seconds = (current_time - previous_time).total_seconds()
            if seconds > 0:
                trends["interval_seconds"] = seconds
                for field, output in (
                    ("battery_voltage_v", "battery_voltage_rate_v_per_hour"),
                    ("battery_current_a", "battery_current_rate_a_per_hour"),
                    ("solar_array_current_a", "solar_current_rate_a_per_hour"),
                ):
                    now = _number(row.get(field))
                    before = _number(previous_row.get(field))
                    if now is not None and before is not None:
                        trends[output] = (now - before) / (seconds / 3600)

                voltage_rate = trends["battery_voltage_rate_v_per_hour"]
                if voltage_rate is not None and voltage_rate < -1:
                    findings.append(_finding(
                        "PWR_BATTERY_VOLTAGE_DECLINING", "Warning",
                        "battery_voltage_v", voltage_rate, "< -1 V/hour",
                        "Battery voltage is declining faster than the prototype trend threshold.",
                    ))

    status = max(
        (finding["status"] for finding in findings),
        key=lambda value: SEVERITY[value],
        default="Healthy",
    )
    if available_measurements == 0:
        status = "Unknown"
    quality = row.get("input_data_quality", "complete")
    confidence = 0.0 if status == "Unknown" else 0.9
    if context_notes:
        confidence = min(confidence, 0.6)
    if quality == "degraded":
        confidence = min(confidence, 0.4)

    power_proxies = {
        "solar_output_w": (
            solar_voltage * solar_current
            if solar_voltage is not None and solar_current is not None
            else None
        ),
        "battery_power_w": (
            voltage * current if voltage is not None and current is not None else None
        ),
        "battery_power_interpretation": sign_convention,
        "net_power_balance_w": None,
    }
    if sign_convention == "unknown":
        context_notes.append("Battery-current sign convention is unknown.")
    context_notes.append(
        "Net power balance is unavailable until total spacecraft load telemetry is defined."
    )

    return {
        "status": status,
        "confidence": confidence,
        "method": "prototype_engineering_rules",
        "fault_codes": [finding["fault_code"] for finding in findings],
        "evidence": findings,
        "trends": trends,
        "power_proxies": power_proxies,
        "context_notes": context_notes,
        "limitations": [
            "Thresholds are prototype assumptions and are not approved spacecraft limits."
        ],
        "data_completeness": {
            "available_measurements": available_measurements,
            "required_measurements": 5,
            "sufficient": available_measurements > 0,
        },
    }


def aggregate_health(ml_prediction: str, power_status: str) -> dict[str, Any]:
    """Conservatively combine ML and deterministic subsystem health."""

    status = max((ml_prediction, power_status), key=lambda value: SEVERITY[value])
    contributors = ["ml_classifier"]
    if power_status != "Healthy":
        contributors.append("power_subsystem_rules")
    return {
        "status": status,
        "method": "maximum_severity",
        "contributors": contributors,
        "ml_status": ml_prediction,
        "power_status": power_status,
    }


def aggregate_all_health(
    ml_prediction: str,
    subsystem_health: Mapping[str, Mapping[str, Any]],
    *,
    ml_accepted: bool = True,
) -> dict[str, Any]:
    """Conservatively combine ML with every available subsystem result."""

    subsystem_statuses = {
        name: str(result.get("effective_status", result["status"]))
        for name, result in subsystem_health.items()
    }
    candidates = {**subsystem_statuses}
    if ml_accepted:
        candidates["ml_classifier"] = ml_prediction
    status = max(candidates.values(), key=lambda value: SEVERITY[value])
    contributors = [
        name for name, value in candidates.items() if SEVERITY[value] == SEVERITY[status]
    ]
    return {
        "status": status,
        "method": "maximum_severity",
        "contributors": contributors,
        "ml_status": ml_prediction,
        "ml_accepted": ml_accepted,
        "subsystem_statuses": subsystem_statuses,
    }
