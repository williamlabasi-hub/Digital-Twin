"""End-to-end regression coverage for the integrated prototype workflow."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.run_golden_path import run_golden_path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GoldenPathTests(unittest.TestCase):
    def test_all_subsystems_produce_aligned_validated_artifacts(self) -> None:
        output_dir = REPOSITORY_ROOT / "tests" / "_golden_path_output"
        output_dir.mkdir(exist_ok=True)
        try:
            for path in output_dir.iterdir():
                path.unlink()
            summary = run_golden_path(output_dir)

            self.assertEqual(summary["orbital_source"], "fixture")
            self.assertEqual(summary["primary_spacecraft_id"], "SAT-001")
            self.assertEqual(
                summary["identified_secondary_object_id"],
                "CAT-25544",
            )
            self.assertEqual(summary["object_identification_decision"], "clear_match")
            self.assertEqual(summary["collision_assessment_status"], "complete")
            self.assertEqual(summary["health_status"], "Healthy")
            self.assertEqual(summary["collision_risk_level"], "moderate")
            self.assertEqual(summary["coa_status"], "limited")
            self.assertEqual(
                summary["candidate_coa_codes"],
                [
                    "COA_IMPROVE_DEGRADED_EVIDENCE",
                    "COA_REFINE_TRACKING",
                    "COA_MANEUVER_PLANNING_REVIEW",
                ],
            )
            self.assertEqual(
                summary["advisory_codes"],
                [
                    "IMPROVE_DEGRADED_EVIDENCE",
                    "REQUEST_REFINED_TRACKING",
                    "BEGIN_MANEUVER_PLANNING_REVIEW",
                ],
            )

            expected_files = {
                "health-report.json",
                "orbital-generation.json",
                "object-identification.json",
                "collision-risk.json",
                "health-evidence.json",
                "object-identification-evidence.json",
                "collision-risk-evidence.json",
                "coa-report.json",
                "summary.json",
            }
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                expected_files,
            )

            coa_report = json.loads(
                (output_dir / "coa-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(coa_report["primary_subject_id"], "SAT-001")
            self.assertEqual(coa_report["secondary_subject_id"], "CAT-25544")
            self.assertEqual(len(coa_report["evidence_summary"]), 3)
            self.assertEqual(
                coa_report["decision_tree"]["policy_version"],
                "prototype-0.2",
            )
            self.assertEqual(
                [item["branch"] for item in coa_report["decision_tree"]["trace"]],
                ["no", "yes", "moderate", "no_constraint"],
            )
            self.assertTrue(
                all(
                    item["requires_operator_approval"]
                    for item in coa_report["candidate_coas"]
                )
            )
            self.assertEqual(
                coa_report["decision_scope"],
                "operator_advisory_only_no_command_authority",
            )
            self.assertEqual(
                coa_report["operator_summary"]["selected_coa_codes"],
                summary["candidate_coa_codes"],
            )

            first_artifacts = {
                path.name: path.read_bytes() for path in output_dir.iterdir()
            }
            self.assertEqual(run_golden_path(output_dir), summary)
            self.assertEqual(
                {path.name: path.read_bytes() for path in output_dir.iterdir()},
                first_artifacts,
            )
        finally:
            for path in output_dir.iterdir():
                path.unlink()
            output_dir.rmdir()

    def test_live_mode_calls_landon_orbit_generation_before_identification(self) -> None:
        fixture_dir = (
            REPOSITORY_ROOT
            / "tests"
            / "fixtures"
            / "object_identification"
            / "data_gen"
        )
        records = {
            25544: "candidate-propagation.example.json",
            25338: "candidate-far.example.json",
            43013: "candidate-near.example.json",
            20580: "candidate-far.example.json",
        }
        calls = []

        def fake_orbit_provider(catalog, propagation_time):
            calls.append((catalog, dict(propagation_time)))
            record = json.loads(
                (fixture_dir / records[catalog]).read_text(encoding="utf-8")
            )
            if catalog == 25544 and len(calls) == 2:
                record = json.loads(
                    (fixture_dir / "observation-propagation.example.json").read_text(
                        encoding="utf-8"
                    )
                )
            return record

        output_dir = REPOSITORY_ROOT / "tests" / "_golden_path_live_output"
        output_dir.mkdir(exist_ok=True)
        try:
            summary = run_golden_path(
                output_dir,
                orbital_source="live",
                orbit_provider=fake_orbit_provider,
            )
            self.assertEqual(
                [call[0] for call in calls],
                [20580, 25544, 25544, 25338, 43013],
            )
            self.assertEqual(summary["orbital_source"], "live")
            self.assertEqual(
                summary["orbital_provider"],
                "src.common.data_gen.orbit_catalog",
            )
            generated = json.loads(
                (output_dir / "orbital-generation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated["mode"], "live")
            self.assertEqual(generated["primary"]["catalog"], 40003)
            self.assertEqual(len(generated["candidates"]), 3)
            self.assertEqual(summary["identified_secondary_object_id"], "CAT-25544")
            self.assertNotEqual(generated["generated_for"], "2026-07-29T20:01:00Z")
            collision = json.loads(
                (output_dir / "collision-risk.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                collision["artifact_metadata"]["validation_status"],
                "prototype_unvalidated",
            )
            self.assertEqual(collision["assessment_status"], "geometric_only")
            self.assertEqual(
                collision["uncertainty_assurance"]["status"],
                "missing_covariance",
            )
            self.assertEqual(collision["primary_object_id"], "SAT-001")
            self.assertEqual(collision["secondary_object_id"], "CAT-25544")
        finally:
            for path in output_dir.iterdir():
                path.unlink()
            output_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
