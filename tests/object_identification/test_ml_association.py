import json
import unittest
from copy import deepcopy
from pathlib import Path

import joblib

from src.object_identification.association import load_association_config
from src.object_identification.evaluation import generate_synthetic_cases
from src.object_identification.ml_association import (
    FEATURE_NAMES,
    load_ml_artifact,
    predict_with_ml,
    save_ml_artifacts,
    split_scenarios,
    train_ml_association,
)
from src.object_identification.ml_inference import main as inference_main


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ObjectIdentificationMlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_association_config()
        cls.artifact, cls.report = train_ml_association(
            case_count=60,
            seed=20260728,
            config=cls.config,
        )

    def test_scenario_split_has_no_case_leakage(self) -> None:
        cases = generate_synthetic_cases(case_count=30, seed=19)
        split = split_scenarios(cases, seed=19)
        groups = [
            {case["case_id"] for case in split.training},
            {case["case_id"] for case in split.calibration},
            {case["case_id"] for case in split.test},
        ]

        self.assertTrue(groups[0].isdisjoint(groups[1]))
        self.assertTrue(groups[0].isdisjoint(groups[2]))
        self.assertTrue(groups[1].isdisjoint(groups[2]))
        self.assertEqual(sum(len(group) for group in groups), 30)

    def test_training_compares_models_and_uses_held_out_scenarios(self) -> None:
        self.assertEqual(set(self.report["models"]), {
            "logistic_regression",
            "random_forest",
        })
        self.assertIn(self.report["selected_model"], self.report["models"])
        self.assertIn("rule_baseline", self.report)
        self.assertEqual(
            self.report["rule_baseline"]["name"],
            "covariance-aware-transparent-association",
        )
        self.assertEqual(
            self.report["scenario_split"]["split_unit"],
            "complete_scenario",
        )
        self.assertEqual(tuple(self.artifact["feature_names"]), FEATURE_NAMES)
        for result in self.report["models"].values():
            for metric in (
                "precision",
                "recall",
                "f1",
                "false_positive_rate",
                "brier_score",
            ):
                self.assertGreaterEqual(result[metric], 0)
                self.assertLessEqual(result[metric], 1)

    def test_in_domain_prediction_uses_ml(self) -> None:
        case = generate_synthetic_cases(
            case_count=30, seed=20260728
        )[0]

        prediction = predict_with_ml(
            case["prepared_candidates"],
            self.artifact,
            self.config,
        )

        self.assertEqual(prediction["mode"], "ml")
        self.assertFalse(prediction["abstained"])
        self.assertEqual(
            prediction["prediction"]["inference_assurance"]["mode"],
            "machine_learning",
        )
        self.assertEqual(
            prediction["prediction"]["matching_method"]["method_type"],
            "machine_learning",
        )

    def test_out_of_domain_prediction_abstains_to_rule_fallback(self) -> None:
        case = deepcopy(
            generate_synthetic_cases(case_count=30, seed=20260728)[0]
        )
        case["prepared_candidates"][0]["orbital_state"][
            "position_km"
        ][0] += 10000

        prediction = predict_with_ml(
            case["prepared_candidates"],
            self.artifact,
            self.config,
        )

        self.assertEqual(prediction["mode"], "rule_fallback")
        self.assertTrue(prediction["abstained"])
        self.assertIn("prediction", prediction)

    def test_artifact_and_report_round_trip(self) -> None:
        output_directory = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_ml_output"
        )
        artifact_path = output_directory / "object-identification-ml.joblib"
        report_path = (
            output_directory / "object-identification-ml-report.json"
        )
        try:
            save_ml_artifacts(
                self.artifact,
                self.report,
                output_directory,
            )
            loaded = joblib.load(artifact_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(
                loaded["model_name"], report["selected_model"]
            )
            self.assertEqual(
                loaded["use_designation"],
                "synthetic_prototype_non_operational",
            )
            self.assertEqual(
                tuple(loaded["allowed_uncertainty_statuses"]),
                ("combined_covariance",),
            )
            compatible = load_ml_artifact(artifact_path)
            self.assertEqual(compatible["artifact_version"], "0.1.0")
        finally:
            artifact_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
            if output_directory.exists():
                output_directory.rmdir()

    def test_inference_cli_writes_schema_valid_prediction(self) -> None:
        output_directory = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_ml_inference_output"
        )
        artifact_path = output_directory / "object-identification-ml.joblib"
        report_path = (
            output_directory / "object-identification-ml-report.json"
        )
        prediction_path = output_directory / "prediction.json"
        fixtures = (
            REPOSITORY_ROOT / "tests" / "fixtures" / "object_identification"
        )
        multi = fixtures / "multi_candidate"
        try:
            save_ml_artifacts(
                self.artifact,
                self.report,
                output_directory,
            )
            return_code = inference_main(
                [
                    "--artifact",
                    str(artifact_path),
                    "--observation",
                    str(fixtures / "tracking-observation.example.json"),
                    "--candidate",
                    str(multi / "clear-best.catalog.json"),
                    str(multi / "clear-best.orbital.json"),
                    str(multi / "clear-best.affiliation.json"),
                    "--candidate",
                    str(multi / "clear-mid.catalog.json"),
                    str(multi / "clear-mid.orbital.json"),
                    str(multi / "clear-mid.affiliation.json"),
                    "--candidate",
                    str(multi / "ambiguous-near.catalog.json"),
                    str(multi / "ambiguous-near.orbital.json"),
                    str(multi / "ambiguous-near.affiliation.json"),
                    "--output",
                    str(prediction_path),
                ]
            )

            self.assertEqual(return_code, 0)
            prediction = json.loads(
                prediction_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                prediction["inference_assurance"]["mode"],
                "rule_fallback",
            )
            self.assertTrue(
                prediction["inference_assurance"]["abstained"]
            )
            self.assertEqual(
                prediction["inference_assurance"]["abstention_reason"],
                "uncertainty_status_outside_synthetic_training_domain",
            )
        finally:
            artifact_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
            prediction_path.unlink(missing_ok=True)
            if output_directory.exists():
                output_directory.rmdir()

    def test_incompatible_feature_contract_is_rejected(self) -> None:
        output_directory = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_incompatible_ml_output"
        )
        artifact_path = output_directory / "object-identification-ml.joblib"
        incompatible = deepcopy(self.artifact)
        incompatible["feature_names"] = ("unexpected_feature",)
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
            joblib.dump(incompatible, artifact_path)
            with self.assertRaisesRegex(
                ValueError, "feature contract is incompatible"
            ):
                load_ml_artifact(artifact_path)
        finally:
            artifact_path.unlink(missing_ok=True)
            if output_directory.exists():
                output_directory.rmdir()


if __name__ == "__main__":
    unittest.main()
