import copy
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from coa import (  # noqa: E402
    COADecisionSupportError,
    adapt_collision_risk,
    adapt_health_report,
    adapt_object_identification,
    build_coa_report,
)


def health_source() -> dict:
    return {
        "report_generated_at": "2026-07-29T20:00:00Z",
        "satellite_id": "CAT-25544",
        "timestamp": "2026-07-29T19:59:00Z",
        "prediction": "Healthy",
        "model_assurance": {
            "decision": "accepted",
            "accepted": True,
            "method": "training_profile_bounds_v1",
            "reasons": [],
        },
        "overall_health": {
            "status": "Healthy",
            "method": "maximum_severity",
            "contributors": [],
            "ml_status": "Healthy",
            "ml_accepted": True,
            "subsystem_statuses": {
                "power": "Healthy",
                "thermal": "Healthy",
            },
        },
        "subsystem_health": {
            "power": {
                "status": "Healthy",
                "confidence": 0.9,
                "fault_codes": [],
            },
            "thermal": {
                "status": "Healthy",
                "confidence": 0.9,
                "fault_codes": [],
            },
        },
        "fault_hypotheses": [],
        "data_quality": {
            "status": "complete",
            "missing_model_values": [],
            "notes": [],
        },
        "recommendations": [],
        "recommendation_scope": "preliminary_health_advisory_not_operator_coa",
        "health_trend": {
            "previous_health_status": "Healthy",
            "trend": "stable",
        },
    }


def object_id_source() -> dict:
    return {
        "schema_version": "0.1.0",
        "contract_version": "0.1.0",
        "record_id": "OID-OBS-001",
        "generated_at": "2026-07-29T20:00:00Z",
        "observation_id": "OBS-001",
        "observation_timestamp": "2026-07-29T19:59:30Z",
        "canonical_object_id": "CAT-40002",
        "identity_status": "known",
        "affiliation": "other",
        "classification": "known_other",
        "match_score": 0.91,
        "match_score_interpretation": "prototype_similarity",
        "catalog_provenance": {
            "catalog_source": "TLE_API",
            "catalog_record_id": "TLE_API-40002",
            "catalog_record_valid_at": "2026-07-29T19:55:00Z",
        },
        "affiliation_provenance": {
            "affiliation_authority": "PROTOTYPE_OPERATOR",
            "affiliation_source_record_id": "AFF-40002",
            "affiliation_effective_at": "2026-01-01T00:00:00Z",
            "affiliation_expires_at": None,
        },
        "candidate_selection": {
            "decision_basis": "clear_match",
            "candidate_count": 3,
            "ambiguity_margin": 0.05,
            "best_to_second_score_gap": 0.7,
        },
        "candidate_rankings": [],
        "data_quality": {"status": "complete", "issues": []},
        "inference_assurance": {
            "mode": "rule_fallback",
            "abstained": True,
            "abstention_reason": "feature_outside_synthetic_training_domain",
            "artifact_version": "0.1.0",
            "model_name": "random_forest",
        },
        "rationale": ["Clear match under the prototype rule."],
        "use_designation": "prototype_non_operational",
    }


def collision_source(name: str = "high-risk-assessment.example.json") -> dict:
    return json.loads(
        (
            REPOSITORY_ROOT
            / "tests"
            / "fixtures"
            / "collision_risk"
            / name
        ).read_text(encoding="utf-8")
    )


def evidence_set() -> list[dict]:
    return [
        adapt_health_report(health_source()),
        adapt_object_identification(object_id_source()),
        adapt_collision_risk(collision_source()),
    ]


class COADecisionSupportTests(unittest.TestCase):
    def test_packaged_report_schema_is_valid(self) -> None:
        schema = json.loads(
            files("coa")
            .joinpath("coa-report.schema.json")
            .read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)

    def test_complete_evidence_produces_review_only_advisories(self) -> None:
        report = build_coa_report(
            evidence_set(),
            generated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(report["status"], "advisory_ready")
        self.assertEqual(report["assessment"]["collision_risk_level"], "high")
        self.assertIn(
            "ASSESS_MANEUVER_OPTIONS",
            {item["code"] for item in report["advisories"]},
        )
        self.assertEqual(
            report["decision_scope"],
            "operator_advisory_only_no_command_authority",
        )
        self.assertEqual(
            set(report["blocked_actions"]),
            {
                "autonomous_maneuver",
                "autonomous_spacecraft_command",
                "threat_designation_from_proximity",
            },
        )

    def test_degraded_collision_evidence_limits_report(self) -> None:
        records = evidence_set()
        collision = records[2]
        collision["decision_support"]["usability"] = "degraded"
        collision["data_quality"]["status"] = "degraded"

        report = build_coa_report(records)

        self.assertEqual(report["status"], "limited")
        self.assertEqual(
            report["advisories"][0]["code"],
            "IMPROVE_DEGRADED_EVIDENCE",
        )

    def test_withheld_evidence_blocks_advisory_selection(self) -> None:
        source = object_id_source()
        source["canonical_object_id"] = None
        source["identity_status"] = "unknown"
        source["affiliation"] = "unknown"
        source["classification"] = "unknown"
        source["catalog_provenance"] = None
        source["affiliation_provenance"] = None
        source["candidate_selection"]["decision_basis"] = "ambiguous"
        records = evidence_set()
        withheld = adapt_object_identification(source)
        withheld["subject"]["subject_id"] = "CAT-40002"
        records[1] = withheld

        report = build_coa_report(records)

        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertEqual(
            [item["code"] for item in report["advisories"]],
            ["RESOLVE_WITHHELD_EVIDENCE"],
        )

    def test_critical_health_adds_constraint_review(self) -> None:
        source = health_source()
        source["overall_health"]["status"] = "Critical"
        source["overall_health"]["subsystem_statuses"]["power"] = "Critical"
        source["subsystem_health"]["power"]["status"] = "Critical"
        records = evidence_set()
        records[0] = adapt_health_report(source)

        report = build_coa_report(records)

        health_advisory = next(
            item
            for item in report["advisories"]
            if item["code"] == "ASSESS_HEALTH_CONSTRAINTS"
        )
        self.assertEqual(health_advisory["priority"], "urgent")

    def test_subject_mismatch_is_rejected(self) -> None:
        records = evidence_set()
        records[0]["subject"]["subject_id"] = "CAT-WRONG"

        with self.assertRaisesRegex(
            COADecisionSupportError,
            "Health evidence subject",
        ):
            build_coa_report(records)

    def test_requires_exactly_one_record_of_each_type(self) -> None:
        records = evidence_set()
        records[1] = copy.deepcopy(records[0])

        with self.assertRaises(COADecisionSupportError):
            build_coa_report(records)

    def test_naive_generated_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(COADecisionSupportError, "timezone"):
            build_coa_report(
                evidence_set(),
                generated_at=datetime(2026, 7, 30),
            )

    def test_cli_writes_schema_valid_report(self) -> None:
        records = evidence_set()
        root = REPOSITORY_ROOT / "outputs"
        root.mkdir(exist_ok=True)
        inputs = [
            root / f"test-coa-evidence-{index}.json"
            for index in range(len(records))
        ]
        output = root / "test-coa-report.json"
        try:
            for path, record in zip(inputs, records):
                path.write_text(json.dumps(record), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "coa.cli",
                    "--health-evidence",
                    str(inputs[0]),
                    "--object-id-evidence",
                    str(inputs[1]),
                    "--collision-risk-evidence",
                    str(inputs[2]),
                    "--output",
                    str(output),
                    "--generated-at",
                    "2026-07-30T20:00:00Z",
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

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "advisory_ready")
            self.assertEqual(report["generated_at"], "2026-07-30T20:00:00Z")
        finally:
            for path in [*inputs, output]:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
