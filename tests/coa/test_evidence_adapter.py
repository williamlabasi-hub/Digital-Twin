import copy
import json
import subprocess
import sys
import unittest
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from coa.evidence_adapter import (  # noqa: E402
    COAEvidenceAdapterError,
    adapt_health_predictions,
    adapt_health_report,
    adapt_object_identification,
    validate_coa_evidence,
)


def health_report() -> dict:
    return {
        "report_generated_at": "2026-07-29T20:00:00Z",
        "satellite_id": "SAT-001",
        "timestamp": "2026-07-29T19:59:00Z",
        "prediction": "Warning",
        "model_assurance": {
            "decision": "accepted",
            "accepted": True,
            "method": "training_profile_bounds_v1",
            "reasons": [],
        },
        "overall_health": {
            "status": "Warning",
            "method": "maximum_severity",
            "contributors": ["power"],
            "ml_status": "Healthy",
            "ml_accepted": True,
            "subsystem_statuses": {
                "power": "Warning",
                "thermal": "Healthy",
            },
        },
        "subsystem_health": {
            "power": {
                "status": "Warning",
                "confidence": 0.9,
                "fault_codes": ["PWR_LOW_BATTERY_WARNING"],
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
        "recommendations": ["Review the power trend."],
        "recommendation_scope": "preliminary_health_advisory_not_operator_coa",
        "health_trend": {
            "previous_health_status": "Healthy",
            "trend": "worsening",
        },
    }


def object_id_prediction() -> dict:
    return {
        "schema_version": "0.1.0",
        "contract_version": "0.1.0",
        "record_id": "OID-OBS-001",
        "generated_at": "2026-07-29T20:00:00Z",
        "observation_id": "OBS-001",
        "observation_timestamp": "2026-07-29T19:59:30Z",
        "canonical_object_id": "CAT-25544",
        "identity_status": "known",
        "affiliation": "other",
        "classification": "known_other",
        "match_score": 0.91,
        "match_score_interpretation": "prototype_similarity",
        "catalog_provenance": {
            "catalog_source": "TLE_API",
            "catalog_record_id": "TLE_API-25544",
            "catalog_record_valid_at": "2026-07-29T19:55:00Z",
        },
        "affiliation_provenance": {
            "affiliation_authority": "PROTOTYPE_OPERATOR",
            "affiliation_source_record_id": "AFF-25544",
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


class COAEvidenceAdapterTests(unittest.TestCase):
    def test_packaged_schema_is_valid(self) -> None:
        schema = json.loads(
            files("coa")
            .joinpath("coa-evidence.schema.json")
            .read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)

    def test_repository_src_import_style_can_load_packaged_schema(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from src.coa.evidence_adapter import _schema; "
                    "assert _schema()['title'] == 'Course of Action Evidence'"
                ),
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_health_report_becomes_usable_evidence(self) -> None:
        evidence = adapt_health_report(health_report())

        self.assertEqual(evidence["evidence_type"], "health")
        self.assertEqual(evidence["subject"]["subject_id"], "SAT-001")
        self.assertEqual(evidence["decision_support"]["usability"], "usable")
        self.assertIsNone(evidence["decision_support"]["confidence"])
        self.assertEqual(evidence["payload"]["overall_status"], "Warning")
        self.assertEqual(
            evidence["payload"]["fault_codes"],
            ["PWR_LOW_BATTERY_WARNING"],
        )

    def test_unknown_overall_health_is_withheld(self) -> None:
        report = health_report()
        report["overall_health"]["status"] = "Unknown"
        report["overall_health"]["subsystem_statuses"] = {
            "power": "Unknown",
            "thermal": "Unknown",
        }

        evidence = adapt_health_report(report)

        self.assertEqual(evidence["decision_support"]["usability"], "withheld")
        self.assertEqual(
            evidence["decision_support"]["withheld_reason"],
            "overall_health_unknown",
        )

    def test_health_prediction_bundle_adapts_every_report(self) -> None:
        first = health_report()
        second = copy.deepcopy(first)
        second["satellite_id"] = "SAT-002"

        evidence = adapt_health_predictions(
            {
                "schema_version": "1.1.0",
                "report": [first, second],
            }
        )

        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["source"]["source_schema_version"], "1.1.0")
        self.assertEqual(evidence[1]["subject"]["subject_id"], "SAT-002")

    def test_object_id_pipeline_bundle_becomes_usable_evidence(self) -> None:
        prediction = object_id_prediction()
        bundle = {
            "prediction": prediction,
            "inference_assurance": {
                "requested_mode": "machine_learning",
                **prediction["inference_assurance"],
            },
        }

        evidence = adapt_object_identification(bundle)

        self.assertEqual(
            evidence["subject"],
            {
                "subject_id": "CAT-25544",
                "subject_type": "space_object",
                "identity_status": "known",
            },
        )
        self.assertEqual(evidence["decision_support"]["usability"], "usable")
        self.assertEqual(evidence["decision_support"]["confidence"], 0.91)
        self.assertTrue(
            evidence["payload"]["inference_assurance"]["abstained"]
        )

    def test_ambiguous_object_id_is_withheld(self) -> None:
        prediction = object_id_prediction()
        prediction["canonical_object_id"] = None
        prediction["identity_status"] = "unknown"
        prediction["affiliation"] = "unknown"
        prediction["classification"] = "unknown"
        prediction["catalog_provenance"] = None
        prediction["affiliation_provenance"] = None
        prediction["candidate_selection"]["decision_basis"] = "ambiguous"

        evidence = adapt_object_identification(prediction)

        self.assertEqual(evidence["subject"]["subject_id"], "OBS-001")
        self.assertEqual(evidence["subject"]["subject_type"], "observed_track")
        self.assertEqual(evidence["decision_support"]["usability"], "withheld")
        self.assertEqual(
            evidence["decision_support"]["withheld_reason"], "ambiguous"
        )

    def test_contract_rejects_withheld_evidence_without_reason(self) -> None:
        evidence = adapt_health_report(health_report())
        evidence["decision_support"]["usability"] = "withheld"

        with self.assertRaises(COAEvidenceAdapterError):
            validate_coa_evidence(evidence)

    def test_adapter_does_not_mutate_source_record(self) -> None:
        prediction = object_id_prediction()
        original = copy.deepcopy(prediction)

        adapt_object_identification(prediction)

        self.assertEqual(prediction, original)


if __name__ == "__main__":
    unittest.main()
