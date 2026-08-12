"""CMD interface for safe synthetic-prototype ML object association."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "object_identification"

from .association import load_association_config
from .input_pipeline import (
    ObjectIdentificationInputError,
    prepare_identification_input_from_files,
)
from .ml_association import (
    DEFAULT_OUTPUT_DIRECTORY,
    load_ml_artifact,
    predict_with_ml,
)


DEFAULT_ARTIFACT_PATH = (
    DEFAULT_OUTPUT_DIRECTORY / "object-identification-ml.joblib"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run safe synthetic-prototype ML object association with automatic "
            "out-of-domain abstention to the transparent rule fallback."
        )
    )
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT_PATH)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        nargs=3,
        action="append",
        required=True,
        metavar=("CATALOG", "ORBITAL", "AFFILIATION"),
        type=Path,
        help="Candidate evidence triplet; repeat for multiple candidates.",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifact = load_ml_artifact(args.artifact)
        config = (
            load_association_config(args.config)
            if args.config is not None
            else load_association_config()
        )
        prepared_candidates = [
            prepare_identification_input_from_files(
                args.observation,
                catalog_path,
                orbital_path,
                affiliation_path,
            )
            for catalog_path, orbital_path, affiliation_path in args.candidate
        ]
        result = predict_with_ml(prepared_candidates, artifact, config)
        prediction = result["prediction"]
    except ObjectIdentificationInputError as exc:
        print(f"Object-identification ML inference error: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(prediction, indent=2)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(
            f"Prediction written to: {args.output.resolve()} "
            f"(mode={prediction['inference_assurance']['mode']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
