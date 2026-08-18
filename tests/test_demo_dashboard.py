from __future__ import annotations

import json
import shutil
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from demo.start_demo import (
    DashboardDataError,
    dashboard_handler,
    load_dashboard_payload,
)
from scripts.run_golden_path import run_golden_path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DashboardLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_root = REPOSITORY_ROOT / "tests" / "_dashboard_demo_output"
        cls.summary = run_golden_path(cls.output_root, run_id="dashboard-demo-test")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.output_root.exists():
            shutil.rmtree(cls.output_root)

    def setUp(self) -> None:
        latest = {
            "dashboard_contract_version": "1.0.0",
            "run_id": "dashboard-demo-test",
            "run_directory": self.summary["run_directory"],
            "summary": self.summary["artifacts"]["summary"],
            "published_at": "2026-08-17T16:00:00Z",
        }
        (self.output_root / "latest.json").write_text(
            json.dumps(latest), encoding="utf-8"
        )

    def test_loader_returns_validated_summary_and_detail_artifacts(self) -> None:
        payload = load_dashboard_payload(self.output_root)

        self.assertEqual(payload["summary"]["run_id"], "dashboard-demo-test")
        self.assertEqual(
            set(payload["details"]), {"health", "identity", "collision", "coa"}
        )
        self.assertEqual(
            payload["details"]["coa"]["decision_scope"],
            "operator_advisory_only_no_command_authority",
        )

    def test_api_serves_the_validated_dashboard_payload(self) -> None:
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), dashboard_handler(self.output_root)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/dashboard",
                timeout=5,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
            self.assertEqual(body["summary"]["run_id"], "dashboard-demo-test")
            self.assertEqual(
                set(body["details"]), {"health", "identity", "collision", "coa"}
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_loader_rejects_artifact_reference_outside_published_run(self) -> None:
        latest_path = self.output_root / "latest.json"
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest["summary"] = str((REPOSITORY_ROOT / "README.md").resolve())
        latest_path.write_text(json.dumps(latest), encoding="utf-8")

        with self.assertRaisesRegex(DashboardDataError, "outside"):
            load_dashboard_payload(self.output_root)

    def test_api_reports_unsupported_contract_version(self) -> None:
        latest_path = self.output_root / "latest.json"
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest["dashboard_contract_version"] = "2.0.0"
        latest_path.write_text(json.dumps(latest), encoding="utf-8")

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), dashboard_handler(self.output_root)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as caught:
                urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/dashboard",
                    timeout=5,
                )
            self.assertEqual(caught.exception.code, 409)
            body = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertEqual(
                body["error"]["code"], "dashboard_version_unsupported"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
