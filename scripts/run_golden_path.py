"""Run the prototype subsystems as one reproducible integration scenario."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from coa import (  # noqa: E402
    adapt_collision_risk,
    adapt_health_report,
    adapt_object_identification,
    build_coa_report,
)
from collision_risk.geometry import assess_closest_approach  # noqa: E402
from common.data_gen import orbit_catalog  # noqa: E402
from common.dashboard_contracts import (  # noqa: E402
    CONTRACT_VERSION as DASHBOARD_CONTRACT_VERSION,
    validate_dashboard_contract,
)
from health.health_monitor import build_report, prepare_dataset  # noqa: E402
from object_identification.data_gen_pipeline import (  # noqa: E402
    build_data_gen_prediction,
    load_candidate_manifest,
)
from object_identification.association import validate_prediction  # noqa: E402


DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "outputs" / "golden-path"
HEALTH_MODEL = (
    REPOSITORY_ROOT
    / "data"
    / "processed"
    / "health"
    / "models"
    / "satellite_health_model.joblib"
)
HEALTH_TELEMETRY = (
    REPOSITORY_ROOT / "data" / "raw" / "telemetry" / "HealthTelemetry1.json"
)
HEALTH_COMMANDS = (
    REPOSITORY_ROOT
    / "data"
    / "raw"
    / "command_history"
    / "CommandHistory1.json"
)
OBJECT_FIXTURES = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "object_identification" / "data_gen"
)
COLLISION_INPUT = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "collision_risk"
    / "conjunction-assessment-input.example.json"
)
PRIMARY_SPACECRAFT_ID = "SAT-001"
GENERATED_AT = datetime(2026, 7, 29, 20, 1, tzinfo=timezone.utc)
GENERATED_AT_TEXT = GENERATED_AT.isoformat().replace("+00:00", "Z")
LIVE_OBSERVATION_CATALOG = 25544
LIVE_PRIMARY_CATALOG = 20580
LIVE_CANDIDATES = (
    (25544, "payload"),
    (25338, "payload"),
    (43013, "payload"),
)
SCENARIOS = (
    "nominal",
    "ambiguous_identity",
    "missing_covariance",
    "unavailable_health",
    "stale_evidence",
    "collision_abstained",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, value: Any) -> None:
    """Replace one JSON reference without exposing a partially written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    _write_json(temporary, value)
    temporary.replace(path)


def _new_run_id() -> str:
    published_at = datetime.now(timezone.utc)
    timestamp = published_at.strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def _publish_staged_run(staging_dir: Path, run_dir: Path) -> None:
    """Atomically promote a run, tolerating brief Windows file-indexer locks."""

    for attempt in range(20):
        try:
            staging_dir.replace(run_dir)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def _validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise ValueError(
            "run_id must contain only letters, numbers, period, underscore, or hyphen."
        )


def _timestamp_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _health_report(scenario_time: datetime = GENERATED_AT) -> dict[str, Any]:
    dataset = prepare_dataset(
        HEALTH_TELEMETRY,
        HEALTH_COMMANDS,
        validation_reference_time=scenario_time,
    )
    reports = build_report(dataset, joblib.load(HEALTH_MODEL), history=[])
    report = next(
        report
        for report in reports
        if report["satellite_id"] == PRIMARY_SPACECRAFT_ID
    )
    report["report_generated_at"] = _timestamp_text(scenario_time)
    return report


def _propagation_time(scenario_time: datetime = GENERATED_AT) -> dict[str, int]:
    return {
        "year": scenario_time.year,
        "month": scenario_time.month,
        "day": scenario_time.day,
        "hour": scenario_time.hour,
        "minute": scenario_time.minute,
        "second": scenario_time.second,
    }


def _live_orbital_inputs(
    orbit_provider: Any = orbit_catalog,
    scenario_time: datetime = GENERATED_AT,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Generate current orbital inputs through Landon's data-generation API."""

    propagation_time = _propagation_time(scenario_time)
    primary = orbit_provider(LIVE_PRIMARY_CATALOG, propagation_time)
    observation = orbit_provider(LIVE_OBSERVATION_CATALOG, propagation_time)
    candidates = [
        {
            "propagation": orbit_provider(catalog, propagation_time),
            "catalog_source": "LIVE_TLE_API",
            "object_type": object_type,
            "affiliation": "other",
            "affiliation_authority": "PROTOTYPE_OPERATOR",
            "affiliation_source_record_id": f"LIVE-AFF-{catalog}",
        }
        for catalog, object_type in LIVE_CANDIDATES
    ]
    return primary, observation, candidates


def _object_identification(
    orbital_source: str = "fixture",
    orbit_provider: Any = orbit_catalog,
    scenario_time: datetime = GENERATED_AT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if orbital_source == "live":
        primary, observation, candidates = _live_orbital_inputs(
            orbit_provider,
            scenario_time,
        )
        data_source = "LANDON_DATA_GEN_LIVE_TLE"
    elif orbital_source == "fixture":
        observation = _load_json(
            OBJECT_FIXTURES / "observation-propagation.example.json"
        )
        candidates = load_candidate_manifest(
            OBJECT_FIXTURES / "candidate-manifest.example.json"
        )
        data_source = "VERSIONED_GOLDEN_PATH_FIXTURE"
        primary = None
    else:
        raise ValueError("orbital_source must be 'fixture' or 'live'")

    bundle = build_data_gen_prediction(
        observation,
        candidates,
        observation_id="OBS-GOLDEN-PATH-1",
        track_id="TRACK-GOLDEN-PATH-1",
        sensor_id="SIMULATED-SENSOR",
        sensor_type="other",
        data_source=data_source,
        measurement_quality=0.9,
    )
    scenario_time_text = _timestamp_text(scenario_time)
    bundle["prediction"]["generated_at"] = scenario_time_text
    for candidate in bundle["candidates"]:
        candidate["prepared"]["prepared_at"] = scenario_time_text
    orbital_generation = {
        "mode": orbital_source,
        "provider": (
            "src.common.data_gen.orbit_catalog"
            if orbital_source == "live"
            else "versioned_fixture"
        ),
        "generated_for": scenario_time_text,
        "primary": primary,
        "observation": observation,
        "candidates": [candidate["propagation"] for candidate in candidates],
    }
    return bundle, orbital_generation


def _collision_assessment(
    secondary_object_id: str,
    *,
    primary_propagation: dict[str, Any] | None = None,
    secondary_propagation: dict[str, Any] | None = None,
    scenario_time: datetime = GENERATED_AT,
    omit_covariance: bool = False,
    incompatible_frames: bool = False,
) -> dict[str, Any]:
    request = copy.deepcopy(_load_json(COLLISION_INPUT))
    request["request_id"] = "CONJ-GOLDEN-PATH-1"
    request["primary"]["object_id"] = PRIMARY_SPACECRAFT_ID
    request["primary"]["provenance"]["source_record_id"] = (
        "GOLDEN-PATH-SAT-001"
    )
    request["secondary"]["object_id"] = secondary_object_id
    request["secondary"]["provenance"]["source_record_id"] = (
        f"GOLDEN-PATH-{secondary_object_id}"
    )
    if omit_covariance:
        for state in (request["primary"], request["secondary"]):
            state.pop("state_covariance", None)
            state.pop("covariance_metadata", None)
    if incompatible_frames:
        request["secondary"]["coordinate_frame"] = "TEME"
    if primary_propagation is not None and secondary_propagation is not None:
        scenario_time_text = _timestamp_text(scenario_time)
        request["analysis_window"] = {
            "start": scenario_time_text,
            "end": (scenario_time + timedelta(minutes=15))
            .isoformat()
            .replace("+00:00", "Z"),
        }
        for label, propagation in (
            ("primary", primary_propagation),
            ("secondary", secondary_propagation),
        ):
            request[label].pop("state_covariance", None)
            request[label].pop("covariance_metadata", None)
            request[label]["epoch"] = scenario_time_text
            request[label]["position_km"] = propagation["position_km"]
            request[label]["velocity_km_s"] = propagation[
                "cartesian_velocity_km_s"
            ]
            request[label]["provenance"]["source"] = "LIVE_TLE_API"
            request[label]["provenance"]["source_record_valid_at"] = (
                scenario_time_text
            )
            request[label]["propagation"] = {
                "method": "SGP4",
                "version": "src.common.data_gen.orbit_catalog",
                "propagated_at": scenario_time_text,
            }
    return assess_closest_approach(request, generated_at=scenario_time)


def _apply_scenario_overrides(
    scenario: str,
    health_report: dict[str, Any],
    object_bundle: dict[str, Any],
) -> None:
    """Apply deterministic evidence degradations before subsystem adaptation."""

    if scenario == "unavailable_health":
        health_report["overall_health"]["status"] = "Unknown"
        health_report["overall_health"]["contributors"] = []
        health_report["overall_health"]["subsystem_statuses"] = {
            name: "Unknown"
            for name in health_report["overall_health"]["subsystem_statuses"]
        }
        health_report["data_quality"]["status"] = "degraded"
        health_report["data_quality"].setdefault("notes", []).append(
            "Scenario override: health evidence is unavailable."
        )
    elif scenario == "stale_evidence":
        stale_time = _timestamp_text(GENERATED_AT - timedelta(days=2))
        object_bundle["prediction"]["observation_timestamp"] = stale_time
    elif scenario == "ambiguous_identity":
        prediction = object_bundle["prediction"]
        prediction["canonical_object_id"] = None
        prediction["identity_status"] = "unknown"
        prediction["affiliation"] = "unknown"
        prediction["classification"] = "unknown"
        prediction["catalog_provenance"] = None
        prediction["affiliation_provenance"] = None
        prediction["candidate_selection"]["decision_basis"] = "ambiguous"
        prediction["candidate_selection"]["best_to_second_score_gap"] = 0.0
        prediction["rationale"] = [
            "Scenario override: multiple candidates are intentionally ambiguous."
        ]
        validate_prediction(prediction)


def run_golden_path(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    orbital_source: str = "fixture",
    orbit_provider: Any = orbit_catalog,
    scenario: str = "nominal",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run all subsystems and write validated integration artifacts."""

    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of: {', '.join(SCENARIOS)}")
    if orbital_source == "live" and scenario != "nominal":
        raise ValueError(
            "Degraded scenario modes require deterministic fixture orbital inputs."
        )

    output_root = Path(output_dir)
    run_id = run_id or _new_run_id()
    _validate_run_id(run_id)
    runs_dir = output_root / "runs"
    run_dir = runs_dir / run_id
    staging_dir = runs_dir / f".staging-{run_id}"
    if run_dir.exists() or staging_dir.exists():
        raise ValueError(f"Golden-path run already exists: {run_id}")
    scenario_time = (
        datetime.now(timezone.utc).replace(microsecond=0)
        if orbital_source == "live"
        else GENERATED_AT
    )
    health_report = _health_report(scenario_time)
    object_bundle, orbital_generation = _object_identification(
        orbital_source,
        orbit_provider,
        scenario_time,
    )
    _apply_scenario_overrides(scenario, health_report, object_bundle)
    canonical_secondary_id = object_bundle["prediction"]["canonical_object_id"]
    secondary_object_id = (
        canonical_secondary_id
        if isinstance(canonical_secondary_id, str) and canonical_secondary_id
        else object_bundle["prediction"]["observation_id"]
    )
    primary_propagation = orbital_generation["primary"]
    secondary_propagation = None
    if orbital_source == "live" and canonical_secondary_id is not None:
        selected_catalog = secondary_object_id.removeprefix("CAT-")
        secondary_propagation = next(
            (
                propagation
                for propagation in orbital_generation["candidates"]
                if str(propagation["catalog"]) == selected_catalog
            ),
            None,
        )
        if secondary_propagation is None:
            raise ValueError(
                "Identified object has no matching live propagation record."
            )
    collision_assessment = _collision_assessment(
        secondary_object_id,
        primary_propagation=primary_propagation,
        secondary_propagation=secondary_propagation,
        scenario_time=scenario_time,
        omit_covariance=scenario == "missing_covariance",
        incompatible_frames=scenario == "collision_abstained",
    )

    evidence = {
        "health": adapt_health_report(health_report),
        "object_identification": adapt_object_identification(object_bundle),
        "collision_risk": adapt_collision_risk(collision_assessment),
    }
    coa_report = build_coa_report(
        list(evidence.values()),
        generated_at=scenario_time,
    )

    artifact_names = {
        "health_report": "health-report.json",
        "orbital_generation": "orbital-generation.json",
        "object_identification": "object-identification.json",
        "collision_risk": "collision-risk.json",
        "health_evidence": "health-evidence.json",
        "object_identification_evidence": "object-identification-evidence.json",
        "collision_risk_evidence": "collision-risk-evidence.json",
        "coa_report": "coa-report.json",
        "summary": "summary.json",
    }
    staged_artifacts = {
        name: staging_dir / filename for name, filename in artifact_names.items()
    }
    published_artifacts = {
        name: run_dir / filename for name, filename in artifact_names.items()
    }
    _write_json(staged_artifacts["health_report"], health_report)
    _write_json(staged_artifacts["orbital_generation"], orbital_generation)
    _write_json(staged_artifacts["object_identification"], object_bundle)
    _write_json(staged_artifacts["collision_risk"], collision_assessment)
    _write_json(staged_artifacts["health_evidence"], evidence["health"])
    _write_json(
        staged_artifacts["object_identification_evidence"],
        evidence["object_identification"],
    )
    _write_json(
        staged_artifacts["collision_risk_evidence"], evidence["collision_risk"]
    )
    _write_json(staged_artifacts["coa_report"], coa_report)

    summary = {
        "dashboard_contract_version": DASHBOARD_CONTRACT_VERSION,
        "scenario": "integrated_prototype_golden_path",
        "scenario_mode": scenario,
        "run_id": run_id,
        "run_directory": str(run_dir.resolve()),
        "orbital_source": orbital_source,
        "orbital_provider": orbital_generation["provider"],
        "primary_spacecraft_id": PRIMARY_SPACECRAFT_ID,
        "identified_secondary_object_id": canonical_secondary_id,
        "tracked_secondary_subject_id": secondary_object_id,
        "health_status": health_report["overall_health"]["status"],
        "object_identification_decision": object_bundle["prediction"][
            "candidate_selection"
        ]["decision_basis"],
        "collision_assessment_status": collision_assessment["assessment_status"],
        "collision_risk_level": collision_assessment["risk"]["level"],
        "coa_status": coa_report["status"],
        "evidence_usability": {
            item["evidence_type"]: item["usability"]
            for item in coa_report["evidence_summary"]
        },
        "candidate_coa_codes": [
            item["code"] for item in coa_report["candidate_coas"]
        ],
        "advisory_codes": [item["code"] for item in coa_report["advisories"]],
        "limitations": [
            (
                "Orbital inputs were retrieved from the live TLE service."
                if orbital_source == "live"
                else "Versioned orbital inputs are synthetic integration fixtures."
            ),
            "Subsystem observation times are not a synchronized operational event.",
            "Outputs are prototype decision support and cannot authorize commands.",
        ],
        "artifacts": {
            name: str(path.resolve()) for name, path in published_artifacts.items()
        },
    }
    validate_dashboard_contract(summary, "summary")
    _write_json(staged_artifacts["summary"], summary)
    latest = {
        "dashboard_contract_version": DASHBOARD_CONTRACT_VERSION,
        "run_id": run_id,
        "run_directory": str(run_dir.resolve()),
        "summary": str(published_artifacts["summary"].resolve()),
        "published_at": _timestamp_text(datetime.now(timezone.utc)),
    }
    validate_dashboard_contract(latest, "latest")
    _publish_staged_run(staging_dir, run_dir)
    _write_json_atomic(
        output_root / "latest.json",
        latest,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Health, Object Identification, Collision Risk, and COA together."
    )
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--orbital-source",
        choices=("fixture", "live"),
        default="fixture",
        help="Use deterministic fixtures or Landon's live TLE propagation path.",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="nominal",
        help="Run the nominal fixture story or one expected degraded-evidence mode.",
    )
    args = parser.parse_args()
    try:
        summary = run_golden_path(
            args.output_directory,
            orbital_source=args.orbital_source,
            scenario=args.scenario,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Golden-path error: {exc}", file=sys.stderr)
        return 1
    print(f"Golden-path artifacts written to: {summary['run_directory']}")
    print(
        f"Result: health={summary['health_status']}, "
        f"identity={summary['identified_secondary_object_id']}, "
        f"collision={summary['collision_risk_level']}, "
        f"coa={summary['coa_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
