"""Command-line workflow for prototype collision-risk assessment."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .geometry import assess_closest_approach
from .validation import (
    ConjunctionInputError,
    load_conjunction_input,
    parse_timestamp,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Assess prototype closest-approach geometry, collision "
            "probability, and risk from one conjunction input."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to a conjunction-assessment input JSON object.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path; omit to write the assessment to stdout.",
    )
    parser.add_argument(
        "--generated-at",
        help=(
            "Optional timezone-aware assessment timestamp for reproducible "
            "runs; defaults to the current UTC time."
        ),
    )
    return parser.parse_args(argv)


def _generated_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parse_timestamp(value, "--generated-at")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        assessment = assess_closest_approach(
            load_conjunction_input(args.input),
            generated_at=_generated_at(args.generated_at),
        )
        rendered = json.dumps(assessment, indent=2) + "\n"
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            print(f"Collision-risk assessment written to: {args.output.resolve()}")
            print(
                "Assessment: "
                f"{assessment['assessment_status']} "
                f"(risk={assessment['risk']['level']}, "
                f"probability={assessment['probability']['status']})"
            )
    except ConjunctionInputError as exc:
        print(
            f"Collision-risk assessment error [{exc.code}]: {exc}",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"Collision-risk assessment error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
