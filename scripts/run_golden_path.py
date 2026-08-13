"""Run the prototype subsystems as one reproducible integration scenario."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
from health.health_monitor import build_report, prepare_dataset  # noqa: E402
from object_identification.data_gen_pipeline import (  # noqa: E402
    build_data_gen_prediction,
    load_candidate_manifest,
)


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


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


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


def run_golden_path(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    orbital_source: str = "fixture",
    orbit_provider: Any = orbit_catalog,
) -> dict[str, Any]:
    """Run all subsystems and write validated integration artifacts."""

    output_dir = Path(output_dir)
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
    secondary_object_id = object_bundle["prediction"]["canonical_object_id"]
    if not isinstance(secondary_object_id, str) or not secondary_object_id:
        raise ValueError("Golden path requires a clear object-identification match.")
    primary_propagation = orbital_generation["primary"]
    secondary_propagation = None
    if orbital_source == "live":
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

    artifacts = {
        "health_report": output_dir / "health-report.json",
        "orbital_generation": output_dir / "orbital-generation.json",
        "object_identification": output_dir / "object-identification.json",
        "collision_risk": output_dir / "collision-risk.json",
        "health_evidence": output_dir / "health-evidence.json",
        "object_identification_evidence": output_dir / "object-identification-evidence.json",
        "collision_risk_evidence": output_dir / "collision-risk-evidence.json",
        "coa_report": output_dir / "coa-report.json",
        "summary": output_dir / "summary.json",
    }
    _write_json(artifacts["health_report"], health_report)
    _write_json(artifacts["orbital_generation"], orbital_generation)
    _write_json(artifacts["object_identification"], object_bundle)
    _write_json(artifacts["collision_risk"], collision_assessment)
    _write_json(artifacts["health_evidence"], evidence["health"])
    _write_json(
        artifacts["object_identification_evidence"],
        evidence["object_identification"],
    )
    _write_json(artifacts["collision_risk_evidence"], evidence["collision_risk"])
    _write_json(artifacts["coa_report"], coa_report)

    summary = {
        "scenario": "integrated_prototype_golden_path",
        "orbital_source": orbital_source,
        "orbital_provider": orbital_generation["provider"],
        "primary_spacecraft_id": PRIMARY_SPACECRAFT_ID,
        "identified_secondary_object_id": secondary_object_id,
        "health_status": health_report["overall_health"]["status"],
        "object_identification_decision": object_bundle["prediction"][
            "candidate_selection"
        ]["decision_basis"],
        "collision_assessment_status": collision_assessment["assessment_status"],
        "collision_risk_level": collision_assessment["risk"]["level"],
        "coa_status": coa_report["status"],
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
        "artifacts": {name: str(path.resolve()) for name, path in artifacts.items()},
    }
    _write_json(artifacts["summary"], summary)
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
    args = parser.parse_args()
    try:
        summary = run_golden_path(
            args.output_directory,
            orbital_source=args.orbital_source,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Golden-path error: {exc}", file=sys.stderr)
        return 1
    print(f"Golden-path artifacts written to: {args.output_directory.resolve()}")
    print(
        f"Result: health={summary['health_status']}, "
        f"identity={summary['identified_secondary_object_id']}, "
        f"collision={summary['collision_risk_level']}, "
        f"coa={summary['coa_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
