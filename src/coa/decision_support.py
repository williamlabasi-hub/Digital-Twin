"""Deterministic, non-operational COA advisory selection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from .evidence_adapter import (
    COAEvidenceAdapterError,
    validate_coa_evidence,
)


REPORT_SCHEMA_PATH = files(__package__).joinpath("coa-report.schema.json")
BLOCKED_ACTIONS = [
    "autonomous_maneuver",
    "autonomous_spacecraft_command",
    "threat_designation_from_proximity",
]


class COADecisionSupportError(ValueError):
    """Evidence cannot safely produce a COA decision-support report."""


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_coa_report(report: Mapping[str, Any]) -> None:
    schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(report),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
            for error in errors
        )
        raise COADecisionSupportError(f"Invalid COA report: {detail}")


def _index_evidence(
    evidence_records: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    if len(evidence_records) != 3:
        raise COADecisionSupportError(
            "Exactly one health, object-identification, and collision-risk "
            "evidence record is required."
        )
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in evidence_records:
        try:
            validate_coa_evidence(record)
        except COAEvidenceAdapterError as exc:
            raise COADecisionSupportError(str(exc)) from exc
        evidence_type = str(record["evidence_type"])
        if evidence_type in indexed:
            raise COADecisionSupportError(
                f"Duplicate evidence type: {evidence_type}."
            )
        indexed[evidence_type] = record
    expected = {"health", "object_identification", "collision_risk"}
    if set(indexed) != expected:
        missing = ", ".join(sorted(expected - set(indexed)))
        raise COADecisionSupportError(
            f"Required evidence types are missing: {missing}."
        )
    return indexed


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


def _collision_advisories(
    risk_level: str,
) -> list[dict[str, Any]]:
    if risk_level == "negligible":
        return [
            _advisory(
                "CONTINUE_CONJUNCTION_MONITORING",
                "routine",
                "Continue routine conjunction monitoring.",
                "Computed prototype collision risk is negligible.",
                operator_review=False,
            )
        ]
    if risk_level == "low":
        return [
            _advisory(
                "INCREASE_CONJUNCTION_MONITORING",
                "watch",
                "Increase conjunction monitoring cadence.",
                "Computed prototype collision risk is low but non-negligible.",
            )
        ]
    if risk_level == "moderate":
        return [
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
        ]
    if risk_level in {"high", "critical"}:
        priority = "urgent"
        return [
            _advisory(
                "ESCALATE_COLLISION_REVIEW",
                priority,
                "Escalate for immediate operator collision-risk review.",
                f"Computed prototype collision risk is {risk_level}.",
            ),
            _advisory(
                "REQUEST_URGENT_TRACKING_UPDATE",
                priority,
                "Request an urgent tracking and covariance update.",
                "Independent refreshed evidence is required before action selection.",
            ),
            _advisory(
                "ASSESS_MANEUVER_OPTIONS",
                priority,
                "Assess maneuver options and constraints.",
                "Option assessment does not authorize execution.",
            ),
        ]
    return [
        _advisory(
            "REQUEST_COLLISION_EVIDENCE",
            "priority",
            "Request additional conjunction evidence.",
            "Collision risk is undetermined.",
        )
    ]


def build_coa_report(
    evidence_records: Sequence[Mapping[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a schema-valid advisory report from three evidence envelopes."""

    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise COADecisionSupportError("generated_at requires a timezone.")

    indexed = _index_evidence(evidence_records)
    health = indexed["health"]
    object_id = indexed["object_identification"]
    collision = indexed["collision_risk"]
    collision_payload = collision["payload"]
    primary_id = str(collision_payload["primary_object_id"])
    secondary_id = str(collision_payload["secondary_object_id"])
    if health["subject"]["subject_id"] != primary_id:
        raise COADecisionSupportError(
            "Health evidence subject must match the collision primary object."
        )
    if object_id["subject"]["subject_id"] != secondary_id:
        raise COADecisionSupportError(
            "Object-identification subject must match the collision secondary object."
        )

    evidence_summary = [
        {
            "evidence_type": evidence_type,
            "evidence_id": record["evidence_id"],
            "subject_id": record["subject"]["subject_id"],
            "usability": record["decision_support"]["usability"],
            "data_quality_status": record["data_quality"]["status"],
            "withheld_reason": record["decision_support"]["withheld_reason"],
        }
        for evidence_type, record in (
            ("health", health),
            ("object_identification", object_id),
            ("collision_risk", collision),
        )
    ]
    withheld = [
        summary for summary in evidence_summary
        if summary["usability"] == "withheld"
    ]
    degraded = [
        summary for summary in evidence_summary
        if summary["usability"] == "degraded"
    ]

    health_status = health["payload"]["overall_status"]
    identity_status = object_id["payload"]["identity_status"]
    affiliation = object_id["payload"]["affiliation"]
    risk_level = collision_payload["risk"]["level"]
    collision_probability = collision_payload["probability"][
        "collision_probability"
    ]

    if withheld:
        status = "insufficient_evidence"
        advisories = [
            _advisory(
                "RESOLVE_WITHHELD_EVIDENCE",
                "priority",
                "Resolve withheld evidence before selecting a course of action.",
                "At least one required subsystem withheld decision support.",
            )
        ]
    else:
        status = "limited" if degraded else "advisory_ready"
        advisories = _collision_advisories(str(risk_level))
        if degraded:
            advisories.insert(
                0,
                _advisory(
                    "IMPROVE_DEGRADED_EVIDENCE",
                    "priority",
                    "Obtain complete evidence before action authorization.",
                    "At least one required evidence record is degraded.",
                ),
            )
        if health_status in {"Degraded", "Critical"}:
            advisories.append(
                _advisory(
                    "ASSESS_HEALTH_CONSTRAINTS",
                    "urgent" if health_status == "Critical" else "priority",
                    "Assess spacecraft health constraints before maneuver planning.",
                    f"Primary spacecraft health is {health_status}.",
                )
            )

    report = {
        "schema_version": "0.1.0",
        "contract_version": "0.1.0",
        "report_id": (
            f"COA-REPORT-{collision['source']['source_record_id']}"
        ),
        "generated_at": _iso_utc(generated_at),
        "primary_subject_id": primary_id,
        "secondary_subject_id": secondary_id,
        "status": status,
        "evidence_summary": evidence_summary,
        "assessment": {
            "collision_risk_level": risk_level,
            "collision_probability": collision_probability,
            "primary_health_status": health_status,
            "secondary_identity_status": identity_status,
            "secondary_affiliation": affiliation,
        },
        "advisories": advisories,
        "blocked_actions": BLOCKED_ACTIONS,
        "limitations": [
            "Inputs and thresholds are prototype, non-operational evidence.",
            "Advisories require operator review and independent mission constraints.",
            "This component cannot issue commands or authorize maneuvers.",
            "Proximity and affiliation do not establish hostile intent.",
        ],
        "decision_scope": "operator_advisory_only_no_command_authority",
        "artifact_metadata": {
            "name": "prototype-coa-decision-support",
            "version": "prototype-0.1",
            "validation_status": "prototype_unvalidated",
        },
        "use_designation": "prototype_non_operational",
    }
    validate_coa_report(report)
    return report
