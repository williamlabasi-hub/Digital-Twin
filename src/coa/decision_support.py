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
from .decision_tree import evaluate_coa_decision_tree


REPORT_SCHEMA_PATH = files(__package__).joinpath("coa-report.schema.json")
BLOCKED_ACTIONS = [
    "autonomous_maneuver",
    "autonomous_spacecraft_command",
    "threat_designation_from_proximity",
]
MAX_EVIDENCE_AGE_SECONDS = 24 * 60 * 60
MAX_EVIDENCE_SKEW_SECONDS = 15 * 60


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


def _parse_utc_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise COADecisionSupportError(f"{label} requires a timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise COADecisionSupportError(f"{label} has an invalid timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise COADecisionSupportError(f"{label} timestamp requires a timezone.")
    return parsed.astimezone(timezone.utc)


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
    object_id_usability = object_id["decision_support"]["usability"]
    if (
        object_id_usability != "withheld"
        and object_id["subject"]["subject_id"] != secondary_id
    ):
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
    generated_times = {
        evidence_type: _parse_utc_timestamp(
            record["generated_at"],
            f"{evidence_type} evidence",
        )
        for evidence_type, record in indexed.items()
    }
    freshness_times = {
        evidence_type: _parse_utc_timestamp(
            (
                record["generated_at"]
                if evidence_type == "collision_risk"
                else record["observation_timestamp"]
            ),
            f"{evidence_type} evidence observation",
        )
        for evidence_type, record in indexed.items()
    }
    temporal_issues: list[str] = []
    for evidence_type, source_generated_at in generated_times.items():
        if (generated_at - source_generated_at).total_seconds() < 0:
            raise COADecisionSupportError(
                f"{evidence_type} evidence is dated after the COA report."
            )
    for evidence_type, observed_at in freshness_times.items():
        age_seconds = (generated_at - observed_at).total_seconds()
        if age_seconds < 0:
            if evidence_type != "collision_risk":
                raise COADecisionSupportError(
                    f"{evidence_type} observation is dated after the COA report."
                )
            continue
        if age_seconds > MAX_EVIDENCE_AGE_SECONDS:
            temporal_issues.append(f"{evidence_type}_evidence_stale")
            summary = next(
                item for item in evidence_summary
                if item["evidence_type"] == evidence_type
            )
            if summary["usability"] == "usable":
                summary["usability"] = "degraded"
                summary["data_quality_status"] = "degraded"
    skew_seconds = (
        max(freshness_times.values()) - min(freshness_times.values())
    ).total_seconds()
    if skew_seconds > MAX_EVIDENCE_SKEW_SECONDS:
        temporal_issues.append("subsystem_evidence_not_synchronized")
        for summary in evidence_summary:
            if summary["usability"] == "usable":
                summary["usability"] = "degraded"
                summary["data_quality_status"] = "degraded"
    health_status = health["payload"]["overall_status"]
    identity_status = object_id["payload"]["identity_status"]
    affiliation = object_id["payload"]["affiliation"]
    risk_level = collision_payload["risk"]["level"]
    collision_probability = collision_payload["probability"][
        "collision_probability"
    ]

    decision = evaluate_coa_decision_tree(
        evidence_summary,
        risk_level=str(risk_level),
        health_status=str(health_status),
    )
    selected_codes = [item["code"] for item in decision["candidate_coas"]]
    operator_summary = {
        "headline": (
            f"COA status is {decision['status']}; collision risk is {risk_level}."
        ),
        "selection_basis": [
            f"Primary health is {health_status}.",
            f"Secondary identity status is {identity_status}.",
            f"Collision risk is {risk_level}.",
            *[f"Temporal check: {issue}." for issue in temporal_issues],
        ],
        "selected_coa_codes": selected_codes,
        "operator_action": (
            "Review prerequisites and candidate COAs; no command or maneuver "
            "is authorized by this report."
        ),
    }

    report = {
        "schema_version": "0.2.0",
        "contract_version": "0.2.0",
        "report_id": (
            f"COA-REPORT-{collision['source']['source_record_id']}"
        ),
        "generated_at": _iso_utc(generated_at),
        "primary_subject_id": primary_id,
        "secondary_subject_id": secondary_id,
        "status": decision["status"],
        "evidence_summary": evidence_summary,
        "assessment": {
            "collision_risk_level": risk_level,
            "collision_probability": collision_probability,
            "primary_health_status": health_status,
            "secondary_identity_status": identity_status,
            "secondary_affiliation": affiliation,
        },
        "decision_tree": decision["decision_tree"],
        "candidate_coas": decision["candidate_coas"],
        "advisories": decision["advisories"],
        "operator_summary": operator_summary,
        "blocked_actions": list(BLOCKED_ACTIONS),
        "limitations": [
            "Inputs and thresholds are prototype, non-operational evidence.",
            "Advisories require operator review and independent mission constraints.",
            "This component cannot issue commands or authorize maneuvers.",
            "Proximity and affiliation do not establish hostile intent.",
        ],
        "decision_scope": "operator_advisory_only_no_command_authority",
        "artifact_metadata": {
            "name": "prototype-coa-decision-support",
            "version": "prototype-0.2",
            "validation_status": "prototype_unvalidated",
        },
        "use_designation": "prototype_non_operational",
    }
    validate_coa_report(report)
    return report
