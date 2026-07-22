"""Batch-local alert persistence, confirmation, duration, and hysteresis."""

from __future__ import annotations

from typing import Any

import pandas as pd


SEVERITY = {"Unknown": -1, "Healthy": 0, "Warning": 1, "Degraded": 2, "Critical": 3}


def apply_alert_persistence(
    assessment: dict[str, Any],
    timestamp: Any,
    state: dict[str, Any],
    *,
    confirmation_samples: int = 2,
    clearing_samples: int = 2,
) -> dict[str, Any]:
    """Attach persistent alert state without discarding the raw assessment."""

    raw_status = str(assessment["status"])
    current_time = pd.to_datetime(timestamp, errors="coerce", utc=True)
    previous_raw = state.get("previous_raw")
    consecutive = state.get("consecutive", 0) + 1 if previous_raw == raw_status else 1
    state["previous_raw"] = raw_status
    state["consecutive"] = consecutive

    active_status = state.get("active_status", "Healthy")
    active_since = state.get("active_since")
    alert_state = "clear"

    if raw_status == "Unknown":
        effective = active_status if active_status != "Healthy" else "Unknown"
        alert_state = "insufficient_data"
    elif raw_status == "Critical":
        effective = "Critical"
        alert_state = "confirmed"
        if active_status != "Critical":
            active_since = current_time
        state["active_status"] = effective
        state["active_since"] = active_since
        state["healthy_count"] = 0
    elif SEVERITY[raw_status] > 0:
        if consecutive >= confirmation_samples:
            effective = raw_status
            alert_state = "confirmed"
            if active_status == "Healthy":
                active_since = current_time
            state["active_status"] = effective
            state["active_since"] = active_since
        else:
            effective = active_status
            alert_state = "observed"
        state["healthy_count"] = 0
    else:
        healthy_count = state.get("healthy_count", 0) + 1
        state["healthy_count"] = healthy_count
        if active_status != "Healthy" and healthy_count < clearing_samples:
            effective = active_status
            alert_state = "clearing"
        else:
            effective = "Healthy"
            alert_state = "clear"
            state["active_status"] = "Healthy"
            state["active_since"] = None
            active_since = None

    duration_seconds = None
    active_since = state.get("active_since")
    if active_since is not None and pd.notna(current_time):
        duration_seconds = max(0.0, (current_time - active_since).total_seconds())

    assessment["effective_status"] = effective
    assessment["persistence"] = {
        "alert_state": alert_state,
        "consecutive_samples": consecutive,
        "confirmation_samples": confirmation_samples,
        "clearing_samples": clearing_samples,
        "active_since": active_since.isoformat() if active_since is not None else None,
        "duration_seconds": duration_seconds,
    }
    return assessment
