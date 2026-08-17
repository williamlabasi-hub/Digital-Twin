import copy
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from common.dashboard_contracts import (
    DashboardContractError,
    load_dashboard_schema,
    validate_dashboard_contract,
)


class DashboardContractTests(unittest.TestCase):
    def test_packaged_dashboard_schemas_are_valid(self) -> None:
        for kind in ("summary", "latest"):
            with self.subTest(kind=kind):
                Draft202012Validator.check_schema(load_dashboard_schema(kind))

    def test_latest_reference_accepts_version_one(self) -> None:
        latest = {
            "dashboard_contract_version": "1.0.0",
            "run_id": "20260814T170705Z-example",
            "run_directory": "C:/prototype/runs/example",
            "summary": "C:/prototype/runs/example/summary.json",
            "published_at": "2026-08-14T17:07:11Z",
        }

        validate_dashboard_contract(latest, "latest")

        unsupported = copy.deepcopy(latest)
        unsupported["dashboard_contract_version"] = "2.0.0"
        with self.assertRaises(DashboardContractError):
            validate_dashboard_contract(unsupported, "latest")

    def test_missing_dashboard_fields_are_rejected(self) -> None:
        with self.assertRaises(DashboardContractError):
            validate_dashboard_contract({}, "summary")


if __name__ == "__main__":
    unittest.main()
