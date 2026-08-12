"""Regression tests for launching package command files directly."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENTRY_POINTS = (
    "src/coa/cli.py",
    "src/collision_risk/cli.py",
    "src/common/telemetry_validation.py",
    "src/health/health_monitor.py",
    "src/health/train_health_model.py",
    "src/object_identification/association.py",
    "src/object_identification/data_gen_adapter.py",
    "src/object_identification/data_gen_pipeline.py",
    "src/object_identification/evaluation.py",
    "src/object_identification/input_pipeline.py",
    "src/object_identification/ml_association.py",
    "src/object_identification/ml_inference.py",
    "scripts/generate_dummy_satellite_data.py",
    "scripts/validate_health_scenarios.py",
)


class EntryPointImportTests(unittest.TestCase):
    def test_entry_points_load_outside_repository(self) -> None:
        for relative_path in ENTRY_POINTS:
            with self.subTest(entry_point=relative_path):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(REPOSITORY_ROOT / relative_path),
                        "--help",
                    ],
                    cwd=REPOSITORY_ROOT / "tests",
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=result.stderr or result.stdout,
                )


if __name__ == "__main__":
    unittest.main()
