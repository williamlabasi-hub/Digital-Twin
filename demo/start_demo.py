"""Run and serve the integrated operator-dashboard prototype."""
from __future__ import annotations

import argparse
import http.server
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.dashboard_contracts import (  # noqa: E402
    CONTRACT_VERSION,
    DashboardContractError,
    validate_dashboard_contract,
)
from scripts.run_golden_path import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    SCENARIOS,
    run_golden_path,
)


DETAIL_ARTIFACTS = {
    "health": "health_report",
    "identity": "object_identification",
    "collision": "collision_risk",
    "coa": "coa_report",
}


class DashboardDataError(RuntimeError):
    """A dashboard discovery artifact cannot be loaded safely."""

    def __init__(self, code: str, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DashboardDataError(
            "dashboard_data_missing", f"Required dashboard artifact is missing: {path.name}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise DashboardDataError(
            "dashboard_data_invalid", f"Dashboard artifact is not valid JSON: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise DashboardDataError(
            "dashboard_data_invalid", f"Dashboard artifact must contain a JSON object: {path.name}"
        )
    return value


def _resolve_artifact(path_text: str, allowed_root: Path) -> Path:
    path = Path(path_text).resolve()
    root = allowed_root.resolve()
    if not path.is_relative_to(root):
        raise DashboardDataError(
            "dashboard_path_rejected",
            "Dashboard artifact reference points outside the published output directory.",
        )
    return path


def load_dashboard_payload(output_root: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Load and validate the latest complete run for browser consumption."""

    output_root = Path(output_root).resolve()
    latest = _read_json(output_root / "latest.json")
    try:
        validate_dashboard_contract(latest, "latest")
    except DashboardContractError as exc:
        code = (
            "dashboard_version_unsupported"
            if latest.get("dashboard_contract_version") != CONTRACT_VERSION
            else "dashboard_contract_invalid"
        )
        raise DashboardDataError(code, str(exc), 409) from exc

    run_dir = _resolve_artifact(latest["run_directory"], output_root)
    summary_path = _resolve_artifact(latest["summary"], run_dir)
    summary = _read_json(summary_path)
    try:
        validate_dashboard_contract(summary, "summary")
    except DashboardContractError as exc:
        code = (
            "dashboard_version_unsupported"
            if summary.get("dashboard_contract_version") != CONTRACT_VERSION
            else "dashboard_contract_invalid"
        )
        raise DashboardDataError(code, str(exc), 409) from exc

    if latest["run_id"] != summary["run_id"]:
        raise DashboardDataError(
            "dashboard_run_mismatch", "Latest reference and summary identify different runs."
        )

    details: dict[str, dict[str, Any]] = {}
    for public_name, artifact_key in DETAIL_ARTIFACTS.items():
        artifact_path = _resolve_artifact(summary["artifacts"][artifact_key], run_dir)
        details[public_name] = _read_json(artifact_path)

    return {"latest": latest, "summary": summary, "details": details}


def dashboard_handler(output_root: str | Path) -> type[http.server.SimpleHTTPRequestHandler]:
    """Build a static-file handler with one validated dashboard endpoint."""

    selected_root = Path(output_root)

    class DashboardHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/dashboard":
                super().do_GET()
                return
            try:
                payload = load_dashboard_payload(selected_root)
                self._write_json(200, payload)
            except DashboardDataError as exc:
                self._write_json(
                    exc.status,
                    {"error": {"code": exc.code, "message": str(exc)}},
                )

        def _write_json(self, status: int, value: dict[str, Any]) -> None:
            body = (json.dumps(value, default=str) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the integrated operator dashboard")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scenario", choices=SCENARIOS, default="nominal")
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Serve the current latest run instead of generating a new fixture run.",
    )
    args = parser.parse_args()

    if not args.skip_run:
        summary = run_golden_path(args.output_directory, scenario=args.scenario)
        print(f"Published dashboard run: {summary['run_id']}")

    handler = dashboard_handler(args.output_directory)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Operator dashboard: http://127.0.0.1:{args.port}/demo/")
        print("Press Ctrl+C to stop.")
        server.serve_forever()


if __name__ == "__main__":
    main()
