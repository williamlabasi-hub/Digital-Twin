"""Versioned, deterministic policy tree for prototype COA selection."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


POLICY_NAME = "prototype-coa-decision-tree"
POLICY_VERSION = "prototype-0.2"


def _advisory(
    code: str,
    priority: str,
    text: str,
    rationale: str,
    *,
    operator_review: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "priority": priority,
        "text": text,
        "rationale": rationale,
        "requires_operator_review": operator_review,
    }


def _candidate_coa(
    code: str,
    name: str,
    priority: str,
    disposition: str,
    rationale: str,
    actions: list[str],
    constraints: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "priority": priority,
        "disposition": disposition,
        "rationale": rationale,
        "actions": actions,
        "constraints": constraints,
        "requires_operator_approval": True,
    }


def _collision_branch(risk_level: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if risk_level == "negligible":
        return (
            [
                _advisory(
                    "CONTINUE_CONJUNCTION_MONITORING",
                    "routine",
                    "Continue routine conjunction monitoring.",
                    "Computed prototype collision risk is negligible.",
                    operator_review=False,
                )
            ],
            [
                _candidate_coa(
                    "COA_ROUTINE_MONITORING",
                    "Continue routine monitoring",
                    "routine",
                    "recommended_for_review",
                    "Prototype collision risk is negligible.",
                    ["Continue the current conjunction-screening cadence."],
                    ["Reevaluate when new tracking or covariance data arrive."],
                )
            ],
        )
    if risk_level == "low":
        return (
            [
                _advisory(
                    "INCREASE_CONJUNCTION_MONITORING",
                    "watch",
                    "Increase conjunction monitoring cadence.",
                    "Computed prototype collision risk is low but non-negligible.",
                )
            ],
            [
                _candidate_coa(
                    "COA_INCREASE_MONITORING",
                    "Increase monitoring cadence",
                    "watch",
                    "recommended_for_review",
                    "Prototype collision risk is low but non-negligible.",
                    ["Increase conjunction-screening cadence."],
                    ["Do not infer maneuver necessity from this prototype result."],
                )
            ],
        )
    if risk_level == "moderate":
        return (
            [
                _advisory(
                    "REQUEST_REFINED_TRACKING",
                    "priority",
                    "Request refined tracking and covariance updates.",
                    "Moderate prototype risk warrants improved encounter evidence.",
                ),
                _advisory(
                    "BEGIN_MANEUVER_PLANNING_REVIEW",
                    "priority",
                    "Begin operator maneuver-planning review.",
                    "Planning review preserves response time without authorizing a maneuver.",
                ),
            ],
            [
                _candidate_coa(
                    "COA_REFINE_TRACKING",
                    "Refine tracking before selection",
                    "priority",
                    "recommended_for_review",
                    "Moderate risk requires better encounter evidence.",
                    ["Request refreshed state estimates and covariance."],
                    ["Reassess collision risk before selecting an executable response."],
                ),
                _candidate_coa(
                    "COA_MANEUVER_PLANNING_REVIEW",
                    "Begin maneuver-planning review",
                    "priority",
                    "planning_only",
                    "Early planning preserves response time if risk persists.",
                    ["Develop and compare candidate avoidance options."],
                    [
                        "Do not execute a maneuver.",
                        "Apply independent mission, conjunction, and health constraints.",
                    ],
                ),
            ],
        )
    if risk_level in {"high", "critical"}:
        return (
            [
                _advisory(
                    "ESCALATE_COLLISION_REVIEW",
                    "urgent",
                    "Escalate for immediate operator collision-risk review.",
                    f"Computed prototype collision risk is {risk_level}.",
                ),
                _advisory(
                    "REQUEST_URGENT_TRACKING_UPDATE",
                    "urgent",
                    "Request an urgent tracking and covariance update.",
                    "Independent refreshed evidence is required before action selection.",
                ),
                _advisory(
                    "ASSESS_MANEUVER_OPTIONS",
                    "urgent",
                    "Assess maneuver options and constraints.",
                    "Option assessment does not authorize execution.",
                ),
            ],
            [
                _candidate_coa(
                    "COA_URGENT_COLLISION_RESPONSE_REVIEW",
                    "Conduct urgent collision-response review",
                    "urgent",
                    "recommended_for_review",
                    f"Prototype collision risk is {risk_level}.",
                    [
                        "Escalate to the authorized conjunction-response team.",
                        "Request urgent refreshed tracking and covariance.",
                        "Assess maneuver and no-maneuver options.",
                    ],
                    [
                        "Independent evidence and mission constraints are required.",
                        "Operator approval is required before any command or maneuver.",
                    ],
                )
            ],
        )
    return (
        [
            _advisory(
                "REQUEST_COLLISION_EVIDENCE",
                "priority",
                "Request additional conjunction evidence.",
                "Collision risk is undetermined.",
            )
        ],
        [
            _candidate_coa(
                "COA_OBTAIN_COLLISION_EVIDENCE",
                "Obtain collision evidence",
                "priority",
                "prerequisite",
                "Collision risk is undetermined.",
                ["Obtain sufficient state, covariance, and encounter evidence."],
                ["Do not select a maneuver response while risk is undetermined."],
            )
        ],
    )


def evaluate_coa_decision_tree(
    evidence_summary: Sequence[Mapping[str, Any]],
    *,
    risk_level: str,
    health_status: str,
) -> dict[str, Any]:
    """Evaluate the policy tree and return selections plus an audit trace."""

    withheld_types = [
        str(item["evidence_type"])
        for item in evidence_summary
        if item["usability"] == "withheld"
    ]
    degraded_types = [
        str(item["evidence_type"])
        for item in evidence_summary
        if item["usability"] == "degraded"
    ]
    trace: list[dict[str, str]] = [
        {
            "node_id": "required_evidence_withheld",
            "question": "Did any required subsystem withhold evidence?",
            "observed_value": ",".join(withheld_types) or "none",
            "branch": "yes" if withheld_types else "no",
        }
    ]
    if withheld_types:
        return {
            "status": "insufficient_evidence",
            "advisories": [
                _advisory(
                    "RESOLVE_WITHHELD_EVIDENCE",
                    "priority",
                    "Resolve withheld evidence before selecting a course of action.",
                    "At least one required subsystem withheld decision support.",
                )
            ],
            "candidate_coas": [
                _candidate_coa(
                    "COA_RESOLVE_WITHHELD_EVIDENCE",
                    "Resolve withheld evidence",
                    "priority",
                    "prerequisite",
                    "A required subsystem withheld decision support.",
                    ["Resolve missing, invalid, or ambiguous evidence."],
                    ["Do not select a collision-response COA until evidence is resolved."],
                )
            ],
            "decision_tree": {
                "policy_name": POLICY_NAME,
                "policy_version": POLICY_VERSION,
                "terminal_node": "insufficient_evidence",
                "trace": trace,
            },
        }

    trace.append(
        {
            "node_id": "required_evidence_degraded",
            "question": "Is any required evidence degraded?",
            "observed_value": ",".join(degraded_types) or "none",
            "branch": "yes" if degraded_types else "no",
        }
    )
    trace.append(
        {
            "node_id": "collision_risk_level",
            "question": "Which collision-risk branch applies?",
            "observed_value": risk_level,
            "branch": risk_level,
        }
    )
    advisories, candidate_coas = _collision_branch(risk_level)
    if degraded_types:
        advisories.insert(
            0,
            _advisory(
                "IMPROVE_DEGRADED_EVIDENCE",
                "priority",
                "Obtain complete evidence before action authorization.",
                "At least one required evidence record is degraded.",
            ),
        )
        candidate_coas.insert(
            0,
            _candidate_coa(
                "COA_IMPROVE_DEGRADED_EVIDENCE",
                "Improve degraded evidence",
                "priority",
                "prerequisite",
                "One or more required evidence records are degraded.",
                ["Obtain current, complete subsystem evidence."],
                ["Treat other COAs as planning-only until evidence improves."],
            ),
        )

    health_branch = (
        health_status
        if health_status in {"Warning", "Degraded", "Critical"}
        else "no_constraint"
    )
    trace.append(
        {
            "node_id": "primary_health_constraints",
            "question": "Does primary health constrain maneuver planning?",
            "observed_value": health_status,
            "branch": health_branch,
        }
    )
    if health_status in {"Warning", "Degraded", "Critical"}:
        priority = (
            "urgent" if health_status == "Critical"
            else "watch" if health_status == "Warning"
            else "priority"
        )
        advisories.append(
            _advisory(
                "ASSESS_HEALTH_CONSTRAINTS",
                priority,
                "Assess spacecraft health constraints before maneuver planning.",
                f"Primary spacecraft health is {health_status}.",
            )
        )
        candidate_coas.append(
            _candidate_coa(
                "COA_ASSESS_HEALTH_CONSTRAINTS",
                "Assess health constraints",
                priority,
                "prerequisite",
                f"Primary spacecraft health is {health_status}.",
                ["Assess maneuver feasibility under current spacecraft health."],
                ["Do not worsen spacecraft health through response planning."],
            )
        )

    return {
        "status": "limited" if degraded_types else "advisory_ready",
        "advisories": advisories,
        "candidate_coas": candidate_coas,
        "decision_tree": {
            "policy_name": POLICY_NAME,
            "policy_version": POLICY_VERSION,
            "terminal_node": "candidate_coas_generated",
            "trace": trace,
        },
    }
