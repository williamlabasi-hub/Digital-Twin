"""Branch coverage for the deterministic COA policy tree."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from coa.decision_tree import evaluate_coa_decision_tree  # noqa: E402


def evidence_summary(usability: str = "usable") -> list[dict[str, object]]:
    return [
        {
            "evidence_type": evidence_type,
            "usability": usability if evidence_type == "health" else "usable",
        }
        for evidence_type in (
            "health",
            "object_identification",
            "collision_risk",
        )
    ]


class COADecisionTreeTests(unittest.TestCase):
    def test_collision_risk_branches_select_expected_coas(self) -> None:
        expected = {
            "undetermined": "COA_OBTAIN_COLLISION_EVIDENCE",
            "negligible": "COA_ROUTINE_MONITORING",
            "low": "COA_INCREASE_MONITORING",
            "moderate": "COA_REFINE_TRACKING",
            "high": "COA_URGENT_COLLISION_RESPONSE_REVIEW",
            "critical": "COA_URGENT_COLLISION_RESPONSE_REVIEW",
        }
        for risk_level, expected_code in expected.items():
            with self.subTest(risk_level=risk_level):
                result = evaluate_coa_decision_tree(
                    evidence_summary(),
                    risk_level=risk_level,
                    health_status="Healthy",
                )
                self.assertEqual(result["status"], "advisory_ready")
                self.assertIn(
                    expected_code,
                    {item["code"] for item in result["candidate_coas"]},
                )
                self.assertEqual(
                    result["decision_tree"]["trace"][2]["branch"],
                    risk_level,
                )

    def test_degraded_evidence_and_health_add_prerequisites(self) -> None:
        result = evaluate_coa_decision_tree(
            evidence_summary("degraded"),
            risk_level="moderate",
            health_status="Critical",
        )

        self.assertEqual(result["status"], "limited")
        self.assertEqual(
            [item["code"] for item in result["candidate_coas"]],
            [
                "COA_IMPROVE_DEGRADED_EVIDENCE",
                "COA_REFINE_TRACKING",
                "COA_MANEUVER_PLANNING_REVIEW",
                "COA_ASSESS_HEALTH_CONSTRAINTS",
            ],
        )
        self.assertTrue(
            all(
                item["requires_operator_approval"]
                for item in result["candidate_coas"]
            )
        )

    def test_withheld_evidence_stops_at_resolution_prerequisite(self) -> None:
        summary = evidence_summary()
        summary[1]["usability"] = "withheld"

        result = evaluate_coa_decision_tree(
            summary,
            risk_level="critical",
            health_status="Critical",
        )

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(
            [item["code"] for item in result["candidate_coas"]],
            ["COA_RESOLVE_WITHHELD_EVIDENCE"],
        )
        self.assertEqual(len(result["decision_tree"]["trace"]), 1)

    def test_warning_health_adds_watch_level_constraint_review(self) -> None:
        result = evaluate_coa_decision_tree(
            evidence_summary(), risk_level="low", health_status="Warning"
        )
        health_coa = next(
            item for item in result["candidate_coas"]
            if item["code"] == "COA_ASSESS_HEALTH_CONSTRAINTS"
        )
        self.assertEqual(health_coa["priority"], "watch")
        self.assertEqual(result["decision_tree"]["trace"][-1]["branch"], "Warning")


if __name__ == "__main__":
    unittest.main()
