"""Command-line interface for prototype COA decision support."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "coa"

from .decision_support import (
    COADecisionSupportError,
    build_coa_report,
)
from collision_risk.validation import parse_timestamp


def _load_json_object(path: Path, name: str) -> dict[str, Any]:
    if not path.is_file():
        raise COADecisionSupportError(f"{name} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise COADecisionSupportError(
            f"{name} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise COADecisionSupportError(f"{name} must contain one JSON object.")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine health, object-identification, and collision-risk "
            "evidence into non-operational operator advisories."
        )
    )
    parser.add_argument("--health-evidence", type=Path, required=True)
    parser.add_argument("--object-id-evidence", type=Path, required=True)
    parser.add_argument("--collision-risk-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--generated-at",
        help="Optional timezone-aware timestamp for reproducible output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        generated_at: datetime | None = None
        if args.generated_at is not None:
            generated_at = parse_timestamp(
                args.generated_at,
                "--generated-at",
            )
        report = build_coa_report(
            [
                _load_json_object(args.health_evidence, "health evidence"),
                _load_json_object(
                    args.object_id_evidence,
                    "object-identification evidence",
                ),
                _load_json_object(
                    args.collision_risk_evidence,
                    "collision-risk evidence",
                ),
            ],
            generated_at=generated_at,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
    except (COADecisionSupportError, OSError, ValueError) as exc:
        print(f"COA decision-support error: {exc}", file=sys.stderr)
        return 1

    print(f"COA report written to: {args.output.resolve()}")
    print(
        f"Status: {report['status']} "
        f"(advisories={len(report['advisories'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
