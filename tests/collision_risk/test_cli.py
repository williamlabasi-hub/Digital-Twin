import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "collision_risk"
    / "conjunction-assessment-input.example.json"
)


class CollisionRiskCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "collision_risk.cli",
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
            },
            check=False,
            capture_output=True,
            text=True,
        )

    def test_cli_writes_complete_schema_valid_assessment(self) -> None:
        output_path = (
            REPOSITORY_ROOT
            / "tests"
            / "collision_risk"
            / "_assessment_output.json"
        )
        try:
            completed = self.run_cli(
                "--input",
                str(FIXTURE_PATH),
                "--output",
                str(output_path),
                "--generated-at",
                "2026-07-29T20:01:00Z",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["assessment_status"], "complete")
            self.assertEqual(
                result["generated_at"],
                "2026-07-29T20:01:00Z",
            )
            self.assertEqual(result["probability"]["status"], "computed")
            self.assertIn("assessment written to", completed.stdout)
        finally:
            output_path.unlink(missing_ok=True)

    def test_cli_writes_assessment_to_stdout(self) -> None:
        completed = self.run_cli(
            "--input",
            str(FIXTURE_PATH),
            "--generated-at",
            "2026-07-29T20:01:00Z",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["request_id"], "CONJ-2026-001")

    def test_cli_writes_assessment_and_coa_evidence(self) -> None:
        output_path = (
            REPOSITORY_ROOT
            / "tests"
            / "collision_risk"
            / "_dual_assessment_output.json"
        )
        coa_output_path = (
            REPOSITORY_ROOT
            / "tests"
            / "collision_risk"
            / "_dual_coa_output.json"
        )
        try:
            completed = self.run_cli(
                "--input",
                str(FIXTURE_PATH),
                "--output",
                str(output_path),
                "--coa-output",
                str(coa_output_path),
                "--generated-at",
                "2026-07-29T20:01:00Z",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            assessment = json.loads(
                output_path.read_text(encoding="utf-8")
            )
            evidence = json.loads(
                coa_output_path.read_text(encoding="utf-8")
            )
            self.assertEqual(assessment["assessment_status"], "complete")
            self.assertEqual(evidence["contract_version"], "0.2.0")
            self.assertEqual(evidence["evidence_type"], "collision_risk")
            self.assertEqual(
                evidence["decision_support"]["usability"],
                "usable",
            )
            self.assertEqual(
                evidence["source"]["source_record_id"],
                assessment["assessment_id"],
            )
            self.assertIn("COA evidence written to", completed.stdout)
        finally:
            output_path.unlink(missing_ok=True)
            coa_output_path.unlink(missing_ok=True)

    def test_coa_output_preserves_assessment_stdout_json(self) -> None:
        coa_output_path = (
            REPOSITORY_ROOT
            / "tests"
            / "collision_risk"
            / "_stdout_coa_output.json"
        )
        try:
            completed = self.run_cli(
                "--input",
                str(FIXTURE_PATH),
                "--coa-output",
                str(coa_output_path),
                "--generated-at",
                "2026-07-29T20:01:00Z",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            assessment = json.loads(completed.stdout)
            self.assertEqual(assessment["assessment_status"], "complete")
            self.assertIn("COA evidence written to", completed.stderr)
        finally:
            coa_output_path.unlink(missing_ok=True)

    def test_cli_rejects_missing_input_file(self) -> None:
        completed = self.run_cli(
            "--input",
            str(REPOSITORY_ROOT / "_missing_conjunction.json"),
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("INPUT_FILE_NOT_FOUND", completed.stderr)

    def test_cli_rejects_naive_generated_timestamp(self) -> None:
        completed = self.run_cli(
            "--input",
            str(FIXTURE_PATH),
            "--generated-at",
            "2026-07-29T20:01:00",
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("requires a timezone", completed.stderr)


if __name__ == "__main__":
    unittest.main()
