"""Synthetic-prototype ML candidate association.

Models trained here are architecture prototypes only. They must not be used
operationally without representative independent labeled data and approval.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .association import (
    AssociationConfig,
    build_ranked_prediction,
    calculate_association_score,
    load_association_config,
)
from .evaluation import generate_synthetic_cases
from .input_pipeline import ObjectIdentificationInputError


FEATURE_NAMES = (
    "position_residual_km",
    "velocity_residual_km_s",
    "normalized_distance_squared",
    "measurement_quality",
    "rule_match_score",
    "candidate_count",
    "rule_rank",
    "score_gap_from_best",
    "best_to_second_score_gap",
)
DEFAULT_OUTPUT_DIRECTORY = (
    Path("outputs") / "object_identification" / "ml"
)


@dataclass(frozen=True)
class ScenarioSplit:
    training: list[dict[str, Any]]
    calibration: list[dict[str, Any]]
    test: list[dict[str, Any]]


def split_scenarios(
    cases: list[dict[str, Any]],
    *,
    seed: int,
) -> ScenarioSplit:
    """Split complete scenarios before feature rows to prevent leakage."""
    shuffled = list(cases)
    random.Random(seed).shuffle(shuffled)
    training_end = max(1, int(len(shuffled) * 0.60))
    calibration_end = max(training_end + 1, int(len(shuffled) * 0.80))
    if calibration_end >= len(shuffled):
        calibration_end = len(shuffled) - 1
    return ScenarioSplit(
        training=shuffled[:training_end],
        calibration=shuffled[training_end:calibration_end],
        test=shuffled[calibration_end:],
    )


def _scenario_rows(
    case: dict[str, Any],
    config: AssociationConfig,
) -> tuple[list[list[float]], list[int]]:
    scored = [
        (
            prepared,
            calculate_association_score(prepared, config),
        )
        for prepared in case["prepared_candidates"]
    ]
    scored.sort(
        key=lambda item: (
            -item[1]["match_score"],
            item[0]["candidate"]["canonical_object_id"],
        )
    )
    best_score = scored[0][1]["match_score"]
    second_score = (
        scored[1][1]["match_score"] if len(scored) > 1 else best_score
    )
    best_to_second_gap = best_score - second_score
    features: list[list[float]] = []
    labels: list[int] = []
    expected_id = case["expected_canonical_object_id"]
    for rank, (prepared, metrics) in enumerate(scored, start=1):
        features.append(
            [
                metrics["position_residual_km"],
                metrics["velocity_residual_km_s"],
                metrics["normalized_distance_squared"],
                metrics["measurement_quality"],
                metrics["match_score"],
                float(len(scored)),
                float(rank),
                best_score - metrics["match_score"],
                best_to_second_gap,
            ]
        )
        labels.append(
            int(
                case["ground_truth"] == "known"
                and prepared["candidate"]["canonical_object_id"] == expected_id
            )
        )
    return features, labels


def build_feature_dataset(
    cases: list[dict[str, Any]],
    config: AssociationConfig,
) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[int] = []
    for case in cases:
        case_rows, case_labels = _scenario_rows(case, config)
        rows.extend(case_rows)
        labels.extend(case_labels)
    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=int)


def _candidate_models(seed: int) -> dict[str, Any]:
    return {
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=1000,
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=150,
            max_depth=8,
            min_samples_leaf=3,
            class_weight="balanced",
            random_state=seed,
            n_jobs=1,
        ),
    }


def _calibrate(
    model: Any,
    calibration_features: np.ndarray,
    calibration_labels: np.ndarray,
    seed: int,
) -> LogisticRegression:
    raw_probability = model.predict_proba(calibration_features)[:, 1].reshape(
        -1, 1
    )
    calibrator = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        random_state=seed,
    )
    calibrator.fit(raw_probability, calibration_labels)
    return calibrator


def _calibrated_probability(
    model: Any,
    calibrator: LogisticRegression,
    features: np.ndarray,
) -> np.ndarray:
    raw_probability = model.predict_proba(features)[:, 1].reshape(-1, 1)
    return calibrator.predict_proba(raw_probability)[:, 1]


def _model_metrics(
    labels: np.ndarray,
    probability: np.ndarray,
    *,
    threshold: float = 0.5,
) -> dict[str, float]:
    predicted = (probability >= threshold).astype(int)
    negative_count = int(np.sum(labels == 0))
    false_positive_count = int(np.sum((predicted == 1) & (labels == 0)))
    return {
        "precision": float(
            precision_score(labels, predicted, zero_division=0)
        ),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "false_positive_rate": (
            false_positive_count / negative_count if negative_count else 0.0
        ),
        "brier_score": float(brier_score_loss(labels, probability)),
    }


def train_ml_association(
    *,
    case_count: int = 300,
    seed: int = 20260728,
    config: AssociationConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if case_count < 30:
        raise ObjectIdentificationInputError(
            "ML training requires at least 30 scenarios"
        )
    association_config = config or load_association_config()
    cases = generate_synthetic_cases(case_count=case_count, seed=seed)
    split = split_scenarios(cases, seed=seed)
    training_features, training_labels = build_feature_dataset(
        split.training, association_config
    )
    calibration_features, calibration_labels = build_feature_dataset(
        split.calibration, association_config
    )
    test_features, test_labels = build_feature_dataset(
        split.test, association_config
    )
    model_results: dict[str, dict[str, Any]] = {}
    fitted: dict[str, tuple[Any, LogisticRegression]] = {}
    for name, model in _candidate_models(seed).items():
        model.fit(training_features, training_labels)
        calibrator = _calibrate(
            model,
            calibration_features,
            calibration_labels,
            seed,
        )
        probability = _calibrated_probability(
            model, calibrator, test_features
        )
        model_results[name] = _model_metrics(test_labels, probability)
        fitted[name] = (model, calibrator)

    selected_name = min(
        model_results,
        key=lambda name: (
            model_results[name]["false_positive_rate"],
            -model_results[name]["f1"],
            model_results[name]["brier_score"],
            name,
        ),
    )
    selected_model, selected_calibrator = fitted[selected_name]
    rule_baseline_probability = test_features[
        :, FEATURE_NAMES.index("rule_match_score")
    ]
    rule_baseline_metrics = _model_metrics(
        test_labels,
        rule_baseline_probability,
        threshold=association_config.match_threshold,
    )
    feature_minimum = training_features.min(axis=0)
    feature_maximum = training_features.max(axis=0)
    feature_span = np.maximum(feature_maximum - feature_minimum, 1e-12)
    artifact = {
        "artifact_version": "0.1.0",
        "use_designation": "synthetic_prototype_non_operational",
        "model_name": selected_name,
        "model": selected_model,
        "calibrator": selected_calibrator,
        "feature_names": FEATURE_NAMES,
        "feature_minimum": feature_minimum,
        "feature_maximum": feature_maximum,
        "ood_lower_bound": feature_minimum - 0.10 * feature_span,
        "ood_upper_bound": feature_maximum + 0.10 * feature_span,
        "probability_threshold": 0.5,
        "ambiguity_margin": association_config.ambiguity_margin,
        "seed": seed,
        "case_count": case_count,
    }
    report = {
        "report_version": "0.1.0",
        "use_designation": "synthetic_prototype_non_operational",
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "seed": seed,
        "scenario_count": case_count,
        "scenario_split": {
            "training": len(split.training),
            "calibration": len(split.calibration),
            "test": len(split.test),
            "split_unit": "complete_scenario",
        },
        "candidate_row_counts": {
            "training": len(training_labels),
            "calibration": len(calibration_labels),
            "test": len(test_labels),
        },
        "feature_names": list(FEATURE_NAMES),
        "models": model_results,
        "rule_baseline": {
            "name": "covariance-aware-transparent-association",
            "threshold": association_config.match_threshold,
            **rule_baseline_metrics,
        },
        "selected_model": selected_name,
        "selection_rule": (
            "minimize false-positive rate, then maximize F1, then minimize "
            "Brier score on held-out scenarios"
        ),
        "versions": {
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "joblib": joblib.__version__,
        },
        "limitations": [
            "Training, calibration, and test scenarios are synthetic.",
            "Calibrated values are not operational probabilities.",
            "Artifact abstains outside the synthetic training feature range.",
            "Representative independent labeled data is required for approval.",
        ],
    }
    return artifact, report


def save_ml_artifacts(
    artifact: dict[str, Any],
    report: dict[str, Any],
    output_directory: Path,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        artifact,
        output_directory / "object-identification-ml.joblib",
    )
    (
        output_directory / "object-identification-ml-report.json"
    ).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def predict_with_ml(
    prepared_candidates: list[dict[str, Any]],
    artifact: dict[str, Any],
    config: AssociationConfig,
) -> dict[str, Any]:
    """Predict candidate matches or abstain to the transparent rule fallback."""
    synthetic_case = {
        "ground_truth": "unknown",
        "expected_canonical_object_id": None,
        "prepared_candidates": prepared_candidates,
    }
    rows, _ = _scenario_rows(synthetic_case, config)
    features = np.asarray(rows, dtype=float)
    lower = np.asarray(artifact["ood_lower_bound"], dtype=float)
    upper = np.asarray(artifact["ood_upper_bound"], dtype=float)
    outside = np.any((features < lower) | (features > upper), axis=1)
    if bool(np.any(outside)):
        return {
            "mode": "rule_fallback",
            "abstained": True,
            "abstention_reason": "feature_outside_synthetic_training_domain",
            "prediction": build_ranked_prediction(
                prepared_candidates,
                config,
            ),
        }
    probability = _calibrated_probability(
        artifact["model"],
        artifact["calibrator"],
        features,
    )
    ranked = sorted(
        zip(prepared_candidates, probability, strict=True),
        key=lambda item: (
            -item[1],
            item[0]["candidate"]["canonical_object_id"],
        ),
    )
    top_probability = float(ranked[0][1])
    second_probability = (
        float(ranked[1][1]) if len(ranked) > 1 else None
    )
    gap = (
        top_probability - second_probability
        if second_probability is not None
        else None
    )
    threshold = float(artifact["probability_threshold"])
    ambiguous = bool(
        second_probability is not None
        and top_probability >= threshold
        and second_probability >= threshold
        and gap is not None
        and gap <= float(artifact["ambiguity_margin"])
    )
    known = top_probability >= threshold and not ambiguous
    return {
        "mode": "ml",
        "abstained": False,
        "use_designation": artifact["use_designation"],
        "identity_status": "known" if known else "unknown",
        "canonical_object_id": (
            ranked[0][0]["candidate"]["canonical_object_id"]
            if known
            else None
        ),
        "decision_basis": (
            "ambiguous"
            if ambiguous
            else "clear_match"
            if known
            else "no_candidate_above_threshold"
        ),
        "probability_interpretation": (
            "synthetic_calibrated_candidate_match_score_non_operational"
        ),
        "rankings": [
            {
                "rank": rank,
                "canonical_object_id": prepared["candidate"][
                    "canonical_object_id"
                ],
                "synthetic_match_score": float(candidate_probability),
            }
            for rank, (prepared, candidate_probability) in enumerate(
                ranked, start=1
            )
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the synthetic-prototype object association ML model."
    )
    parser.add_argument("--cases", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifact, report = train_ml_association(
            case_count=args.cases,
            seed=args.seed,
        )
        save_ml_artifacts(artifact, report, args.output_directory)
    except (ObjectIdentificationInputError, ValueError) as exc:
        print(f"Object-identification ML training error: {exc}", file=sys.stderr)
        return 1
    metrics = report["models"][report["selected_model"]]
    print(f"Selected model: {report['selected_model']}")
    print(
        "Held-out synthetic metrics: "
        f"precision={metrics['precision']:.3f}, "
        f"recall={metrics['recall']:.3f}, "
        f"f1={metrics['f1']:.3f}, "
        f"false_positive_rate={metrics['false_positive_rate']:.3f}, "
        f"brier_score={metrics['brier_score']:.3f}"
    )
    print(f"Artifacts written to: {args.output_directory.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
