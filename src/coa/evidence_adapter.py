"""Adapt subsystem results into the shared, non-operational COA evidence contract."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


CONTRACT_VERSION = "0.1.0"
USE_DESIGNATION = "prototype_non_operational"


class COAEvidenceAdapterError(ValueError):
    """Raised when subsystem evidence cannot satisfy the COA contract."""


def _schema() -> dict[str, Any]:
    resource = files(__package__).joinpath("coa-evidence.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_coa_evidence(record: Mapping[str, Any]) -> None:
    """Validate one adapted record and raise a concise contract error."""

    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: "
            f"{error.message}"
            for error in errors
        )
        raise COAEvidenceAdapterError(f"Invalid COA evidence: {detail}")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise COAEvidenceAdapterError(f"{name} must be an object.")
    return value


def _quality_issues(data_quality: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    for issue in data_quality.get("issues", []):
        if isinstance(issue, Mapping):
            code = issue.get("code")
            message = issue.get("message")
            text = ": ".join(str(item) for item in (code, message) if item)
            if text:
                issues.append(text)
        elif issue:
            issues.append(str(issue))
    for field in ("notes", "missing_model_values"):
        for value in data_quality.get(field, []):
            if value:
                issues.append(str(value))
    return list(dict.fromkeys(issues))


def _health_fault_codes(subsystems: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for assessment in subsystems.values():
        if isinstance(assessment, Mapping):
            codes.extend(str(code) for code in assessment.get("fault_codes", []))
    return list(dict.fromkeys(codes))


def adapt_health_report(
    report: Mapping[str, Any],
    *,
    source_schema_version: str = "1.1.0",
    validate: bool = True,
) -> dict[str, Any]:
    """Convert one final health report record into COA evidence."""

    report = _require_mapping(report, "health report")
    overall = _require_mapping(report.get("overall_health"), "overall_health")
    assurance = _require_mapping(report.get("model_assurance"), "model_assurance")
    data_quality = _require_mapping(report.get("data_quality"), "data_quality")
    subsystems = _require_mapping(report.get("subsystem_health"), "subsystem_health")

    satellite_id = report.get("satellite_id")
    observed_at = report.get("timestamp")
    generated_at = report.get("report_generated_at")
    if not all(isinstance(value, str) and value for value in (
        satellite_id,
        observed_at,
        generated_at,
    )):
        raise COAEvidenceAdapterError(
            "Health report requires satellite_id, timestamp, and report_generated_at."
        )

    health_status = overall.get("status")
    quality_status = data_quality.get("status", "degraded")
    if health_status == "Unknown":
        usability = "withheld"
        withheld_reason = "overall_health_unknown"
    elif quality_status == "degraded":
        usability = "degraded"
        withheld_reason = None
    else:
        usability = "usable"
        withheld_reason = None

    subsystem_statuses = overall.get("subsystem_statuses", {})
    subsystem_confidences = {
        name: assessment.get("confidence")
        for name, assessment in subsystems.items()
        if isinstance(assessment, Mapping)
        and isinstance(assessment.get("confidence"), (int, float))
    }

    evidence = {
        "schema_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "evidence_id": f"COA-HEALTH-{satellite_id}-{observed_at}",
        "generated_at": generated_at,
        "evidence_type": "health",
        "subject": {
            "subject_id": satellite_id,
            "subject_type": "spacecraft",
            "identity_status": "known",
        },
        "observation_timestamp": observed_at,
        "source": {
            "component": "health",
            "source_record_id": f"HEALTH-{satellite_id}-{observed_at}",
            "source_schema_version": source_schema_version,
            "source_generated_at": generated_at,
        },
        "decision_support": {
            "usability": usability,
            "confidence": None,
            "confidence_interpretation": (
                "not_provided_at_overall_health_level; "
                "see payload.subsystem_confidences"
            ),
            "withheld_reason": withheld_reason,
        },
        "data_quality": {
            "status": quality_status,
            "issues": _quality_issues(data_quality),
        },
        "payload": {
            "overall_status": health_status,
            "ml_status": overall.get("ml_status"),
            "ml_accepted": bool(overall.get("ml_accepted")),
            "ml_assurance": copy.deepcopy(dict(assurance)),
            "subsystem_statuses": copy.deepcopy(dict(subsystem_statuses)),
            "subsystem_confidences": subsystem_confidences,
            "fault_codes": _health_fault_codes(subsystems),
            "fault_hypotheses": copy.deepcopy(report.get("fault_hypotheses", [])),
            "health_trend": copy.deepcopy(report.get("health_trend")),
            "preliminary_advisories": copy.deepcopy(
                report.get("recommendations", [])
            ),
            "recommendation_scope": report.get("recommendation_scope"),
        },
        "use_designation": USE_DESIGNATION,
    }
    if validate:
        validate_coa_evidence(evidence)
    return evidence


def adapt_health_predictions(
    bundle: Mapping[str, Any],
    *,
    validate: bool = True,
) -> list[dict[str, Any]]:
    """Convert every report in a versioned health-prediction bundle."""

    bundle = _require_mapping(bundle, "health prediction bundle")
    reports = bundle.get("report")
    if not isinstance(reports, list):
        raise COAEvidenceAdapterError(
            "Health prediction bundle requires a report array."
        )
    schema_version = bundle.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        raise COAEvidenceAdapterError(
            "Health prediction bundle requires schema_version."
        )
    return [
        adapt_health_report(
            _require_mapping(report, f"report[{index}]"),
            source_schema_version=schema_version,
            validate=validate,
        )
        for index, report in enumerate(reports)
    ]


def adapt_object_identification(
    result: Mapping[str, Any],
    *,
    validate: bool = True,
) -> dict[str, Any]:
    """Convert an object-ID prediction or pipeline bundle into COA evidence."""

    result = _require_mapping(result, "object-identification result")
    prediction_value = result.get("prediction")
    prediction = (
        _require_mapping(prediction_value, "prediction")
        if isinstance(prediction_value, Mapping)
        else result
    )
    pipeline_assurance = result.get("inference_assurance")
    inference_assurance = (
        copy.deepcopy(dict(pipeline_assurance))
        if isinstance(pipeline_assurance, Mapping)
        else copy.deepcopy(prediction.get("inference_assurance"))
    )

    observation_id = prediction.get("observation_id")
    observed_at = prediction.get("observation_timestamp")
    generated_at = prediction.get("generated_at")
    record_id = prediction.get("record_id")
    if not all(isinstance(value, str) and value for value in (
        observation_id,
        observed_at,
        generated_at,
        record_id,
    )):
        raise COAEvidenceAdapterError(
            "Object-ID prediction requires record_id, observation_id, "
            "observation_timestamp, and generated_at."
        )

    identity_status = prediction.get("identity_status")
    canonical_id = prediction.get("canonical_object_id")
    selection = prediction.get("candidate_selection") or {}
    decision_basis = selection.get("decision_basis")
    quality = _require_mapping(prediction.get("data_quality"), "data_quality")
    quality_status = quality.get("status", "degraded")

    clear_identity = identity_status == "known" and (
        decision_basis in (None, "clear_match")
    )
    if not clear_identity:
        usability = "withheld"
        withheld_reason = (
            decision_basis
            if decision_basis in ("ambiguous", "no_candidate_above_threshold")
            else "identity_unknown"
        )
    elif quality_status == "degraded":
        usability = "degraded"
        withheld_reason = None
    else:
        usability = "usable"
        withheld_reason = None

    evidence = {
        "schema_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "evidence_id": f"COA-OBJECT-ID-{record_id}",
        "generated_at": generated_at,
        "evidence_type": "object_identification",
        "subject": {
            "subject_id": canonical_id or observation_id,
            "subject_type": (
                "space_object" if canonical_id else "observed_track"
            ),
            "identity_status": identity_status,
        },
        "observation_timestamp": observed_at,
        "source": {
            "component": "object_identification",
            "source_record_id": record_id,
            "source_schema_version": prediction.get(
                "contract_version", prediction.get("schema_version")
            ),
            "source_generated_at": generated_at,
        },
        "decision_support": {
            "usability": usability,
            "confidence": prediction.get("match_score"),
            "confidence_interpretation": prediction.get(
                "match_score_interpretation"
            ),
            "withheld_reason": withheld_reason,
        },
        "data_quality": {
            "status": quality_status,
            "issues": _quality_issues(quality),
        },
        "payload": {
            "canonical_object_id": canonical_id,
            "identity_status": identity_status,
            "affiliation": prediction.get("affiliation"),
            "classification": prediction.get("classification"),
            "candidate_selection": copy.deepcopy(selection) or None,
            "candidate_rankings": copy.deepcopy(
                prediction.get("candidate_rankings", [])
            ),
            "catalog_provenance": copy.deepcopy(
                prediction.get("catalog_provenance")
            ),
            "affiliation_provenance": copy.deepcopy(
                prediction.get("affiliation_provenance")
            ),
            "inference_assurance": inference_assurance,
            "rationale": copy.deepcopy(prediction.get("rationale", [])),
        },
        "use_designation": USE_DESIGNATION,
    }
    if validate:
        validate_coa_evidence(evidence)
    return evidence
