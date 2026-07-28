"""Deterministic synthetic evaluation for prototype object association.

The generated scenarios are for engineering evaluation only. They do not
represent operational sensor performance or operational validation data.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .association import (
    AssociationConfig,
    build_ranked_prediction,
    load_association_config,
)
from .input_pipeline import (
    ObjectIdentificationInputError,
    prepare_identification_input,
)


EVALUATION_TIME = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)
OBSERVATION_TIMESTAMP = "2026-07-27T18:59:30Z"
DEFAULT_THRESHOLDS = (0.40, 0.50, 0.60, 0.70, 0.80)
DEFAULT_AMBIGUITY_MARGINS = (0.02, 0.05, 0.10)


def _diagonal_covariance(variance: float) -> list[list[float]]:
    return [
        [variance, 0.0, 0.0],
        [0.0, variance, 0.0],
        [0.0, 0.0, variance],
    ]


def _candidate_records(
    candidate_id: str,
    position_km: list[float],
    velocity_km_s: list[float],
    affiliation: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    orbital_record_id = f"ORB-{candidate_id}"
    catalog = {
        "schema_version": "0.1.0",
        "canonical_object_id": candidate_id,
        "catalog_source": "SYNTHETIC_EVALUATION_CATALOG",
        "catalog_record_id": f"EVAL-{candidate_id}",
        "valid_from": "2026-07-27T18:00:00Z",
        "valid_to": "2026-07-28T18:00:00Z",
        "object_name": f"SYNTHETIC {candidate_id}",
        "object_type": "payload",
        "orbital_record_id": orbital_record_id,
    }
    orbital = {
        "schema_version": "0.1.0",
        "orbital_record_id": orbital_record_id,
        "subject_id": candidate_id,
        "subject_id_type": "canonical_object_id",
        "timestamp": OBSERVATION_TIMESTAMP,
        "coordinate_frame": "ECI",
        "position_km": position_km,
        "velocity_km_s": velocity_km_s,
        "position_covariance_km2": _diagonal_covariance(1.0),
        "velocity_covariance_km2_s2": _diagonal_covariance(0.0001),
        "source": "SYNTHETIC_EVALUATION_CATALOG",
        "derivation": {
            "method": "sgp4",
            "version": "synthetic-evaluation-0.1",
        },
    }
    affiliation_record = {
        "schema_version": "0.1.0",
        "canonical_object_id": candidate_id,
        "affiliation": affiliation,
        "affiliation_authority": "SYNTHETIC_EVALUATION_AUTHORITY",
        "affiliation_source_record_id": f"AFF-{candidate_id}",
        "affiliation_effective_at": "2026-01-01T00:00:00Z",
        "affiliation_expires_at": None,
        "designation_status": "prototype_unvalidated",
        "review_notes": "Synthetic evaluation record; non-operational.",
    }
    return catalog, orbital, affiliation_record


def _observation(
    case_id: str,
    position_km: list[float],
    velocity_km_s: list[float],
    measurement_quality: float,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "observation_id": f"OBS-{case_id}",
        "track_id": f"TRACK-{case_id}",
        "timestamp": OBSERVATION_TIMESTAMP,
        "sensor": {
            "sensor_id": "SYNTHETIC-SENSOR",
            "sensor_type": "fused",
        },
        "data_source": "SYNTHETIC_EVALUATION",
        "coordinate_frame": "ECI",
        "position_km": position_km,
        "velocity_km_s": velocity_km_s,
        "position_covariance_km2": _diagonal_covariance(1.0),
        "velocity_covariance_km2_s2": _diagonal_covariance(0.0001),
        "measurement_quality": measurement_quality,
    }


def _prepare_candidates(
    observation: dict[str, Any],
    candidates: list[
        tuple[str, list[float], list[float], str]
    ],
) -> list[dict[str, Any]]:
    prepared = []
    for candidate_id, position, velocity, affiliation in candidates:
        catalog, orbital, affiliation_record = _candidate_records(
            candidate_id,
            position,
            velocity,
            affiliation,
        )
        prepared.append(
            prepare_identification_input(
                observation,
                catalog,
                orbital,
                affiliation_record,
                prepared_at=EVALUATION_TIME,
            )
        )
    return prepared


def generate_synthetic_cases(
    *,
    case_count: int = 60,
    seed: int = 20260728,
) -> list[dict[str, Any]]:
    """Generate balanced known, unknown, and ambiguous labeled scenarios."""
    if case_count < 3:
        raise ValueError("case_count must be at least 3")
    rng = random.Random(seed)
    labels = ("known", "unknown", "ambiguous")
    cases: list[dict[str, Any]] = []
    base_position = [6628.0, 1045.0, -421.0]
    base_velocity = [-1.08, 7.31, 1.42]

    for index in range(case_count):
        label = labels[index % len(labels)]
        case_id = f"{index + 1:04d}"
        quality = rng.uniform(0.72, 0.98)
        observation_position = [
            value + rng.gauss(0, 0.35) for value in base_position
        ]
        observation_velocity = [
            value + rng.gauss(0, 0.003) for value in base_velocity
        ]
        observation = _observation(
            case_id,
            observation_position,
            observation_velocity,
            quality,
        )

        candidates: list[
            tuple[str, list[float], list[float], str]
        ] = []
        expected_id: str | None = None
        if label == "known":
            expected_id = f"CAT-{case_id}-TRUE"
            candidates.append(
                (
                    expected_id,
                    [
                        value + rng.gauss(0, 0.45)
                        for value in observation_position
                    ],
                    [
                        value + rng.gauss(0, 0.004)
                        for value in observation_velocity
                    ],
                    "blue",
                )
            )
            distractor_offsets = (8.0, 16.0)
        elif label == "unknown":
            near_offset = rng.uniform(0.8, 2.0)
            candidates.append(
                (
                    f"CAT-{case_id}-HARD-NEGATIVE",
                    [
                        observation_position[0] + near_offset,
                        observation_position[1] + rng.uniform(-0.5, 0.5),
                        observation_position[2] + rng.uniform(-0.5, 0.5),
                    ],
                    [
                        observation_velocity[0] + rng.uniform(0.002, 0.008),
                        observation_velocity[1],
                        observation_velocity[2],
                    ],
                    "red",
                )
            )
            distractor_offsets = (8.0, 16.0)
        else:
            first_id = f"CAT-{case_id}-AMB-A"
            second_id = f"CAT-{case_id}-AMB-B"
            for candidate_id in (first_id, second_id):
                candidates.append(
                    (
                        candidate_id,
                        [
                            value + rng.gauss(0, 0.10)
                            for value in observation_position
                        ],
                        [
                            value + rng.gauss(0, 0.001)
                            for value in observation_velocity
                        ],
                        "other",
                    )
                )
            distractor_offsets = (12.0,)

        for distractor_index, offset in enumerate(distractor_offsets, start=1):
            direction = -1.0 if distractor_index % 2 == 0 else 1.0
            candidates.append(
                (
                    f"CAT-{case_id}-DIST-{distractor_index}",
                    [
                        observation_position[0] + direction * offset,
                        observation_position[1] + rng.uniform(-1.0, 1.0),
                        observation_position[2] + rng.uniform(-1.0, 1.0),
                    ],
                    [
                        observation_velocity[0] + direction * 0.08,
                        observation_velocity[1],
                        observation_velocity[2],
                    ],
                    "red",
                )
            )

        cases.append(
            {
                "case_id": case_id,
                "ground_truth": label,
                "expected_canonical_object_id": expected_id,
                "prepared_candidates": _prepare_candidates(
                    observation,
                    candidates,
                ),
            }
        )
    return cases


def evaluate_configuration(
    cases: list[dict[str, Any]],
    config: AssociationConfig,
) -> dict[str, Any]:
    counts = {
        "case_count": len(cases),
        "expected_known": 0,
        "expected_unknown": 0,
        "expected_ambiguous": 0,
        "predicted_known": 0,
        "correct_matches": 0,
        "false_matches": 0,
        "missed_matches": 0,
        "correct_unknown": 0,
        "correct_ambiguous": 0,
    }
    for case in cases:
        prediction = build_ranked_prediction(
            case["prepared_candidates"],
            config,
            generated_at=EVALUATION_TIME,
        )
        truth = case["ground_truth"]
        decision = prediction["candidate_selection"]["decision_basis"]
        predicted_known = prediction["identity_status"] == "known"
        if truth == "known":
            counts["expected_known"] += 1
            if (
                predicted_known
                and prediction["canonical_object_id"]
                == case["expected_canonical_object_id"]
            ):
                counts["correct_matches"] += 1
            else:
                counts["missed_matches"] += 1
                if predicted_known:
                    counts["false_matches"] += 1
        elif truth == "unknown":
            counts["expected_unknown"] += 1
            if decision == "no_candidate_above_threshold":
                counts["correct_unknown"] += 1
            if predicted_known:
                counts["false_matches"] += 1
        else:
            counts["expected_ambiguous"] += 1
            if decision == "ambiguous":
                counts["correct_ambiguous"] += 1
            if predicted_known:
                counts["false_matches"] += 1
        if predicted_known:
            counts["predicted_known"] += 1

    non_known = counts["expected_unknown"] + counts["expected_ambiguous"]
    metrics = {
        "precision": (
            counts["correct_matches"] / counts["predicted_known"]
            if counts["predicted_known"]
            else 0.0
        ),
        "recall": (
            counts["correct_matches"] / counts["expected_known"]
            if counts["expected_known"]
            else 0.0
        ),
        "false_match_rate": (
            counts["false_matches"] / non_known if non_known else 0.0
        ),
        "missed_match_rate": (
            counts["missed_matches"] / counts["expected_known"]
            if counts["expected_known"]
            else 0.0
        ),
        "unknown_accuracy": (
            counts["correct_unknown"] / counts["expected_unknown"]
            if counts["expected_unknown"]
            else 0.0
        ),
        "ambiguity_accuracy": (
            counts["correct_ambiguous"] / counts["expected_ambiguous"]
            if counts["expected_ambiguous"]
            else 0.0
        ),
    }
    return {
        "match_threshold": config.match_threshold,
        "ambiguity_margin": config.ambiguity_margin,
        **counts,
        **metrics,
    }


def evaluate_sweep(
    cases: list[dict[str, Any]],
    base_config: AssociationConfig,
    *,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    ambiguity_margins: tuple[float, ...] = DEFAULT_AMBIGUITY_MARGINS,
) -> list[dict[str, Any]]:
    return [
        evaluate_configuration(
            cases,
            replace(
                base_config,
                match_threshold=threshold,
                ambiguity_margin=margin,
            ),
        )
        for threshold in thresholds
        for margin in ambiguity_margins
    ]


def recommend_configuration(
    results: list[dict[str, Any]],
    *,
    maximum_false_match_rate: float = 0.01,
    minimum_recall: float = 0.80,
    fallback_recall_floor: float = 0.70,
) -> dict[str, Any]:
    eligible = [
        result
        for result in results
        if result["false_match_rate"] <= maximum_false_match_rate
        and result["recall"] >= minimum_recall
    ]
    if eligible:
        selected = max(
            eligible,
            key=lambda result: (
                result["recall"],
                result["ambiguity_accuracy"],
                result["unknown_accuracy"],
                -result["false_match_rate"],
                -result["match_threshold"],
                -result["ambiguity_margin"],
            ),
        )
        selection_rule = (
            f"maximize recall with false_match_rate <= "
            f"{maximum_false_match_rate:.3f} and recall >= "
            f"{minimum_recall:.3f}"
        )
    else:
        fallback = [
            result
            for result in results
            if result["recall"] >= fallback_recall_floor
        ] or results
        selected = min(
            fallback,
            key=lambda result: (
                result["false_match_rate"],
                -result["ambiguity_accuracy"],
                -result["unknown_accuracy"],
                -result["recall"],
                result["match_threshold"],
                result["ambiguity_margin"],
            ),
        )
        selection_rule = (
            "safety target was not achieved; choose the lowest false-match "
            f"result retaining recall >= {fallback_recall_floor:.3f}"
        )
    return {
        "selection_rule": selection_rule,
        "maximum_false_match_rate_target": maximum_false_match_rate,
        "minimum_recall_target": minimum_recall,
        "safety_target_met": bool(eligible),
        **selected,
    }


def build_evaluation_report(
    *,
    case_count: int,
    seed: int,
    base_config: AssociationConfig,
) -> dict[str, Any]:
    cases = generate_synthetic_cases(case_count=case_count, seed=seed)
    sweep = evaluate_sweep(cases, base_config)
    return {
        "report_version": "0.1.0",
        "use_designation": "synthetic_prototype_non_operational",
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "seed": seed,
        "case_count": case_count,
        "scenario_counts": {
            label: sum(
                case["ground_truth"] == label for case in cases
            )
            for label in ("known", "unknown", "ambiguous")
        },
        "thresholds": list(DEFAULT_THRESHOLDS),
        "ambiguity_margins": list(DEFAULT_AMBIGUITY_MARGINS),
        "recommendation": recommend_configuration(sweep),
        "sweep_results": sweep,
        "limitations": [
            "Synthetic scenarios do not represent operational sensor data.",
            "Metrics do not constitute operational validation.",
            "Thresholds must be reevaluated on representative labeled data.",
        ],
    }


def write_report(report: dict[str, Any], output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "object-identification-evaluation.json"
    csv_path = output_directory / "object-identification-threshold-sweep.csv"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = report["sweep_results"]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate prototype object association on deterministic synthetic "
            "known, unknown, and ambiguous scenarios."
        )
    )
    parser.add_argument("--cases", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Association config; repository default is used when omitted.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("outputs") / "object_identification" / "evaluation",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.cases < 3:
            raise ObjectIdentificationInputError(
                "--cases must be at least 3"
            )
        config = (
            load_association_config(args.config)
            if args.config is not None
            else load_association_config()
        )
        report = build_evaluation_report(
            case_count=args.cases,
            seed=args.seed,
            base_config=config,
        )
        write_report(report, args.output_directory)
    except (ObjectIdentificationInputError, ValueError) as exc:
        print(f"Object-identification evaluation error: {exc}", file=sys.stderr)
        return 1

    recommendation = report["recommendation"]
    print(
        "Recommended synthetic-prototype settings: "
        f"match_threshold={recommendation['match_threshold']:.2f}, "
        f"ambiguity_margin={recommendation['ambiguity_margin']:.2f}"
    )
    print(
        "Metrics: "
        f"precision={recommendation['precision']:.3f}, "
        f"recall={recommendation['recall']:.3f}, "
        f"false_match_rate={recommendation['false_match_rate']:.3f}, "
        f"ambiguity_accuracy={recommendation['ambiguity_accuracy']:.3f}"
    )
    print(f"Reports written to: {args.output_directory.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
