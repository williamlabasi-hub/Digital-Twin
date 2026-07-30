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
