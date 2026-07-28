import json
import unittest
from copy import deepcopy
from pathlib import Path

import joblib

from src.object_identification.association import load_association_config
from src.object_identification.evaluation import generate_synthetic_cases
from src.object_identification.ml_association import (
    FEATURE_NAMES,
    predict_with_ml,
    save_ml_artifacts,
    split_scenarios,
    train_ml_association,
)


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
            prediction["use_designation"],
            "synthetic_prototype_non_operational",
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
        finally:
            artifact_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
            if output_directory.exists():
                output_directory.rmdir()


if __name__ == "__main__":
    unittest.main()
