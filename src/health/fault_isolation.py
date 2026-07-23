"""Prototype cross-subsystem fault-isolation hypotheses."""

from __future__ import annotations

from typing import Any, Mapping


def isolate_cross_subsystem_faults(
    subsystem_health: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Correlate explainable findings without claiming a confirmed root cause."""

    statuses = {name: result.get("status") for name, result in subsystem_health.items()}
    codes = {
        name: set(result.get("fault_codes", []))
        for name, result in subsystem_health.items()
    }
    hypotheses: list[dict[str, Any]] = []

    def add(identifier: str, confidence: float, summary: str, evidence: list[str]):
        hypotheses.append({
            "hypothesis_id": identifier,
            "confidence": confidence,
            "summary": summary,
            "supporting_subsystems": evidence,
            "status": "candidate_not_confirmed",
        })

    if statuses.get("power") == "Critical" and statuses.get("communications") == "Critical":
        add(
            "FI_POWER_COMMUNICATIONS_CASCADE", 0.7,
            "A power-system fault may be contributing to communications degradation.",
            ["power", "communications"],
        )
    if statuses.get("power") == "Critical" and statuses.get("cdh") == "Critical":
        add(
            "FI_POWER_CDH_CASCADE", 0.65,
            "Power degradation and C&DH stress are occurring together.",
            ["power", "cdh"],
        )
    if any("OVERCURRENT" in code for code in codes.get("power", set())) and (
        statuses.get("thermal") in {"Warning", "Critical"}
        or statuses.get("payload") in {"Warning", "Critical"}
    ):
        add(
            "FI_ELECTRICAL_THERMAL_LOAD", 0.6,
            "Elevated electrical load may be associated with thermal stress.",
            ["power", "thermal", "payload"],
        )
    if statuses.get("adcs") == "Critical" and any(
        "OVERCURRENT" in code for code in codes.get("power", set())
    ):
        add(
            "FI_ADCS_POWER_LOAD", 0.6,
            "Reaction-wheel stress may be contributing to elevated power demand.",
            ["adcs", "power"],
        )
    if statuses.get("communications") == "Critical" and statuses.get("command_control") in {"Warning", "Critical"}:
        add(
            "FI_COMMAND_LINK_DEGRADATION", 0.7,
            "Communications degradation may be affecting command execution.",
            ["communications", "command_control"],
        )
    return hypotheses
