"""Run generated orbital data through multi-candidate identification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "object_identification"

from .association import build_ranked_prediction, load_association_config
from .data_gen_adapter import build_identification_records
from .input_pipeline import ObjectIdentificationInputError
from .ml_association import load_ml_artifact, predict_with_ml
from .uncertainty import (
    DEFAULT_UNCERTAINTY_CONFIG_PATH,
    apply_uncertainty_model,
    load_uncertainty_config,
)


PIPELINE_VERSION = "0.1.0"
REQUIRED_CANDIDATE_FIELDS = {
    "input",
    "catalog_source",
    "object_type",
    "affiliation",
    "affiliation_authority",
    "affiliation_source_record_id",
}
OPTIONAL_CANDIDATE_FIELDS = {
    "canonical_object_id",
    "designation_status",
}


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectIdentificationInputError(
            f"unable to read {label} JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ObjectIdentificationInputError(
            f"{label} JSON must contain one object: {path}"
        )
    return value


def load_candidate_manifest(path: str | Path) -> list[dict[str, Any]]:
    """Load candidate metadata and propagation records from a manifest."""
    manifest_path = Path(path)
    manifest = _load_json_object(manifest_path, "candidate manifest")
    if manifest.get("schema_version") != "0.1.0":
        raise ObjectIdentificationInputError(
            "candidate manifest schema_version must be 0.1.0"
        )
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ObjectIdentificationInputError(
            "candidate manifest must contain at least one candidate"
        )

    loaded: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        label = f"candidate manifest entry {index}"
        if not isinstance(candidate, dict):
            raise ObjectIdentificationInputError(
                f"{label} must be an object"
            )
        fields = set(candidate)
        missing = REQUIRED_CANDIDATE_FIELDS - fields
        unexpected = fields - (
            REQUIRED_CANDIDATE_FIELDS | OPTIONAL_CANDIDATE_FIELDS
        )
        if missing:
            raise ObjectIdentificationInputError(
                f"{label} is missing fields: {sorted(missing)}"
            )
        if unexpected:
            raise ObjectIdentificationInputError(
                f"{label} has unexpected fields: {sorted(unexpected)}"
            )
        input_value = candidate["input"]
        if not isinstance(input_value, str) or not input_value.strip():
            raise ObjectIdentificationInputError(
                f"{label}.input must be a non-empty path"
            )
        input_path = Path(input_value)
        if not input_path.is_absolute():
            input_path = manifest_path.parent / input_path
        loaded.append(
            {
                **candidate,
                "propagation": _load_json_object(
                    input_path,
                    f"{label} propagation",
                ),
            }
        )
    return loaded


def build_data_gen_prediction(
    observation_propagation: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    observation_id: str,
    track_id: str,
    sensor_id: str,
    sensor_type: str,
    data_source: str,
    measurement_quality: float,
    config_path: str | Path | None = None,
    estimate_uncertainty: bool = False,
    uncertainty_config_path: str | Path = (
        DEFAULT_UNCERTAINTY_CONFIG_PATH
    ),
    ml_artifact_path: str | Path | None = None,
) -> dict[str, Any]:
    """Adapt, validate, rank, and classify generated candidate states."""
    if not candidates:
        raise ObjectIdentificationInputError(
            "at least one generated candidate is required"
        )

    if estimate_uncertainty:
        (
            observation_propagation,
            candidates,
            uncertainty_assurance,
        ) = apply_uncertainty_model(
            observation_propagation,
            candidates,
            sensor_type=sensor_type,
            measurement_quality=measurement_quality,
            config=load_uncertainty_config(uncertainty_config_path),
        )
    else:
        uncertainty_assurance = {
            "mode": "input_only",
            "model_name": None,
            "model_version": None,
            "validation_status": "not_applied",
            "assumptions": [
                "Covariance was accepted only when supplied in input data.",
                "Incomplete covariance uses configured scale fallback.",
            ],
        }

    candidate_records: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        propagation = candidate.get("propagation")
        if not isinstance(propagation, dict):
            raise ObjectIdentificationInputError(
                f"candidate {index}.propagation must be an object"
            )
        try:
            records = build_identification_records(
                observation_propagation,
                propagation,
                observation_id=observation_id,
                track_id=track_id,
                sensor_id=sensor_id,
                sensor_type=sensor_type,
                data_source=data_source,
                measurement_quality=measurement_quality,
                catalog_source=candidate["catalog_source"],
                object_type=candidate["object_type"],
                affiliation=candidate["affiliation"],
                affiliation_authority=candidate[
                    "affiliation_authority"
                ],
                affiliation_source_record_id=candidate[
                    "affiliation_source_record_id"
                ],
                canonical_object_id=candidate.get(
                    "canonical_object_id"
                ),
                designation_status=candidate.get(
                    "designation_status",
                    "prototype_unvalidated",
                ),
            )
        except KeyError as exc:
            raise ObjectIdentificationInputError(
                f"candidate {index} is missing metadata field: {exc.args[0]}"
            ) from exc
        candidate_records.append(records)

    config = (
        load_association_config(config_path)
        if config_path is not None
        else load_association_config()
    )
    prepared_candidates = [
        records["prepared"] for records in candidate_records
    ]
    if ml_artifact_path is None:
        prediction = build_ranked_prediction(
            prepared_candidates,
            config,
        )
        inference_assurance = {
            "requested_mode": "rule",
            "mode": "rule",
            "abstained": False,
            "abstention_reason": None,
            "artifact_version": None,
            "model_name": None,
            "use_designation": "prototype_non_operational",
        }
    else:
        artifact = load_ml_artifact(ml_artifact_path)
        ml_result = predict_with_ml(
            prepared_candidates,
            artifact,
            config,
        )
        prediction = ml_result["prediction"]
        inference_assurance = {
            "requested_mode": "machine_learning",
            "mode": ml_result["mode"],
            "abstained": ml_result["abstained"],
            "abstention_reason": ml_result.get("abstention_reason"),
            "artifact_version": artifact["artifact_version"],
            "model_name": artifact["model_name"],
            "use_designation": artifact["use_designation"],
        }
    return {
        "pipeline_version": PIPELINE_VERSION,
        "use_designation": "prototype_non_operational",
        "uncertainty_assurance": uncertainty_assurance,
        "inference_assurance": inference_assurance,
        "observation": candidate_records[0]["observation"],
        "candidates": [
            {
                "catalog": records["catalog"],
                "orbital": records["orbital"],
                "affiliation": records["affiliation"],
                "prepared": records["prepared"],
            }
            for records in candidate_records
        ],
        "prediction": prediction,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Adapt generated orbital records, rank multiple catalog "
            "candidates, and write an object-identification prediction."
        )
    )
    parser.add_argument("--observation-input", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--track-id", required=True)
    parser.add_argument("--sensor-id", required=True)
    parser.add_argument(
        "--sensor-type",
        choices=["radar", "optical", "space_based", "fused", "other"],
        required=True,
    )
    parser.add_argument("--data-source", required=True)
    parser.add_argument(
        "--measurement-quality",
        type=float,
        required=True,
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--estimate-uncertainty",
        action="store_true",
        help=(
            "Fill missing covariance with the configured transparent "
            "prototype uncertainty model."
        ),
    )
    parser.add_argument(
        "--uncertainty-config",
        type=Path,
        default=DEFAULT_UNCERTAINTY_CONFIG_PATH,
    )
    parser.add_argument(
        "--ml-artifact",
        type=Path,
        help=(
            "Optional compatible synthetic ML artifact. Inference safely "
            "falls back to the rule model when outside its domain."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bundle = build_data_gen_prediction(
            _load_json_object(
                args.observation_input,
                "observation propagation",
            ),
            load_candidate_manifest(args.candidate_manifest),
            observation_id=args.observation_id,
            track_id=args.track_id,
            sensor_id=args.sensor_id,
            sensor_type=args.sensor_type,
            data_source=args.data_source,
            measurement_quality=args.measurement_quality,
            config_path=args.config,
            estimate_uncertainty=args.estimate_uncertainty,
            uncertainty_config_path=args.uncertainty_config,
            ml_artifact_path=args.ml_artifact,
        )
    except ObjectIdentificationInputError as exc:
        print(f"Data-generation pipeline error: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, indent=2) + "\n",
        encoding="utf-8",
    )
    prediction = bundle["prediction"]
    print(f"Prediction written to: {args.output.resolve()}")
    print(
        "Decision: "
        f"{prediction['candidate_selection']['decision_basis']} "
        f"(identity_status={prediction['identity_status']}, "
        f"candidate_count="
        f"{prediction['candidate_selection']['candidate_count']})"
    )
    inference = bundle["inference_assurance"]
    print(
        "Inference: "
        f"{inference['mode']} "
        f"(abstained={str(inference['abstained']).lower()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
