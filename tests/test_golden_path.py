"""End-to-end regression coverage for the integrated prototype workflow."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from scripts.run_golden_path import run_golden_path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GoldenPathTests(unittest.TestCase):
    def test_degraded_scenarios_reject_live_orbital_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "deterministic fixture"):
            run_golden_path(
                REPOSITORY_ROOT / "tests" / "_unused_golden_path_output",
                orbital_source="live",
                scenario="ambiguous_identity",
            )

    def test_expected_degraded_scenarios_finish_with_safe_coa_reports(self) -> None:
        scenarios = {
            "ambiguous_identity": {
                "coa_status": "insufficient_evidence",
                "evidence_type": "object_identification",
                "usability": "withheld",
                "collision_status": "complete",
            },
            "missing_covariance": {
                "coa_status": "limited",
                "evidence_type": "collision_risk",
                "usability": "degraded",
                "collision_status": "geometric_only",
            },
            "unavailable_health": {
                "coa_status": "insufficient_evidence",
                "evidence_type": "health",
                "usability": "withheld",
                "collision_status": "complete",
            },
            "stale_evidence": {
                "coa_status": "limited",
                "evidence_type": "object_identification",
                "usability": "degraded",
                "collision_status": "complete",
            },
            "collision_abstained": {
                "coa_status": "insufficient_evidence",
                "evidence_type": "collision_risk",
                "usability": "withheld",
                "collision_status": "abstained",
            },
        }

        temporary_root = REPOSITORY_ROOT / "tests" / "_golden_path_degraded_output"
        try:
            for scenario, expected in scenarios.items():
                with self.subTest(scenario=scenario):
                    output_dir = temporary_root / scenario
                    summary = run_golden_path(
                        output_dir,
                        scenario=scenario,
                        run_id=f"test-{scenario}",
                    )
                    run_dir = Path(summary["run_directory"])

                    self.assertEqual(summary["scenario_mode"], scenario)
                    self.assertEqual(summary["coa_status"], expected["coa_status"])
                    self.assertEqual(
                        summary["evidence_usability"][expected["evidence_type"]],
                        expected["usability"],
                    )
                    self.assertEqual(
                        summary["collision_assessment_status"],
                        expected["collision_status"],
                    )
                    self.assertTrue((run_dir / "coa-report.json").is_file())
                    self.assertTrue((run_dir / "summary.json").is_file())

                    report = json.loads(
                        (run_dir / "coa-report.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(report["status"], expected["coa_status"])
                    self.assertEqual(
                        report["decision_scope"],
                        "operator_advisory_only_no_command_authority",
                    )
                    if expected["coa_status"] == "insufficient_evidence":
                        self.assertEqual(
                            report["candidate_coas"][0]["code"],
                            "COA_RESOLVE_WITHHELD_EVIDENCE",
                        )
        finally:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)

    def test_all_subsystems_produce_aligned_validated_artifacts(self) -> None:
        output_dir = REPOSITORY_ROOT / "tests" / "_golden_path_output"
        try:
            summary = run_golden_path(output_dir, run_id="test-nominal")
            run_dir = Path(summary["run_directory"])

            self.assertEqual(summary["orbital_source"], "fixture")
            self.assertEqual(summary["dashboard_contract_version"], "1.0.0")
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
                {path.name for path in run_dir.iterdir()},
                expected_files,
            )

            coa_report = json.loads(
                (run_dir / "coa-report.json").read_text(encoding="utf-8")
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

            latest = json.loads(
                (output_dir / "latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(latest["run_id"], "test-nominal")
            self.assertEqual(latest["dashboard_contract_version"], "1.0.0")
            self.assertEqual(Path(latest["run_directory"]), run_dir)
            self.assertEqual(
                Path(latest["summary"]),
                run_dir / "summary.json",
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_each_run_is_preserved_and_latest_moves_atomically(self) -> None:
        output_root = REPOSITORY_ROOT / "tests" / "_golden_path_runs_output"
        try:
            first = run_golden_path(output_root, run_id="test-run-one")
            second = run_golden_path(output_root, run_id="test-run-two")

            self.assertTrue(Path(first["run_directory"]).is_dir())
            self.assertTrue(Path(second["run_directory"]).is_dir())
            self.assertNotEqual(first["run_directory"], second["run_directory"])
            latest = json.loads(
                (output_root / "latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(latest["run_id"], "test-run-two")
            self.assertEqual(latest["run_directory"], second["run_directory"])
            self.assertFalse(any(output_root.rglob(".staging-*")))
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_golden_path(output_root, run_id="test-run-two")
            unchanged_latest = json.loads(
                (output_root / "latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(unchanged_latest, latest)
            self.assertFalse(any(output_root.glob(".*.tmp")))
        finally:
            if output_root.exists():
                shutil.rmtree(output_root)

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
        try:
            summary = run_golden_path(
                output_dir,
                orbital_source="live",
                orbit_provider=fake_orbit_provider,
                run_id="test-live",
            )
            run_dir = Path(summary["run_directory"])
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
                (run_dir / "orbital-generation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated["mode"], "live")
            self.assertEqual(generated["primary"]["catalog"], 40003)
            self.assertEqual(len(generated["candidates"]), 3)
            self.assertEqual(summary["identified_secondary_object_id"], "CAT-25544")
            self.assertNotEqual(generated["generated_for"], "2026-07-29T20:01:00Z")
            collision = json.loads(
                (run_dir / "collision-risk.json").read_text(encoding="utf-8")
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
            if output_dir.exists():
                shutil.rmtree(output_dir)


if __name__ == "__main__":
    unittest.main()
