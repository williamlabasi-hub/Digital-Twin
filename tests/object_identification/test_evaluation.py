import csv
import json
import unittest
from pathlib import Path

from src.object_identification.association import load_association_config
from src.object_identification.evaluation import (
    evaluate_sweep,
    generate_synthetic_cases,
    main,
    recommend_configuration,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ObjectIdentificationEvaluationTests(unittest.TestCase):
    def test_generation_is_deterministic_and_balanced(self) -> None:
        first = generate_synthetic_cases(case_count=9, seed=42)
        second = generate_synthetic_cases(case_count=9, seed=42)

        self.assertEqual(
            [
                (
                    case["case_id"],
                    case["ground_truth"],
                    case["prepared_candidates"][0]["observation"][
                        "position_km"
                    ],
                )
                for case in first
            ],
            [
                (
                    case["case_id"],
                    case["ground_truth"],
                    case["prepared_candidates"][0]["observation"][
                        "position_km"
                    ],
                )
                for case in second
            ],
        )
        self.assertEqual(
            [case["ground_truth"] for case in first].count("known"), 3
        )
        self.assertEqual(
            [case["ground_truth"] for case in first].count("unknown"), 3
        )
        self.assertEqual(
            [case["ground_truth"] for case in first].count("ambiguous"), 3
        )

    def test_sweep_reports_bounded_metrics(self) -> None:
        results = evaluate_sweep(
            generate_synthetic_cases(case_count=9, seed=7),
            load_association_config(),
            thresholds=(0.5, 0.7),
            ambiguity_margins=(0.02, 0.05),
        )

        self.assertEqual(len(results), 4)
        for result in results:
            for metric in (
                "precision",
                "recall",
                "false_match_rate",
                "missed_match_rate",
                "unknown_accuracy",
                "ambiguity_accuracy",
            ):
                self.assertGreaterEqual(result[metric], 0)
                self.assertLessEqual(result[metric], 1)

    def test_higher_threshold_reduces_false_matches_with_recall_tradeoff(
        self,
    ) -> None:
        results = evaluate_sweep(
            generate_synthetic_cases(case_count=30, seed=20260728),
            load_association_config(),
            thresholds=(0.4, 0.8),
            ambiguity_margins=(0.05,),
        )
        low, high = results

        self.assertGreaterEqual(
            low["false_match_rate"], high["false_match_rate"]
        )
        self.assertGreaterEqual(low["recall"], high["recall"])

    def test_recommendation_prefers_safety_eligible_result(self) -> None:
        results = [
            {
                "match_threshold": 0.4,
                "ambiguity_margin": 0.02,
                "recall": 1.0,
                "ambiguity_accuracy": 0.5,
                "unknown_accuracy": 0.5,
                "false_match_rate": 0.2,
            },
            {
                "match_threshold": 0.6,
                "ambiguity_margin": 0.05,
                "recall": 0.9,
                "ambiguity_accuracy": 1.0,
                "unknown_accuracy": 1.0,
                "false_match_rate": 0.0,
            },
        ]

        recommendation = recommend_configuration(results)

        self.assertTrue(recommendation["safety_target_met"])
        self.assertEqual(recommendation["match_threshold"], 0.6)

    def test_cli_writes_json_and_csv_reports(self) -> None:
        output_directory = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_evaluation_output"
        )
        json_path = (
            output_directory / "object-identification-evaluation.json"
        )
        csv_path = (
            output_directory
            / "object-identification-threshold-sweep.csv"
        )
        try:
            return_code = main(
                [
                    "--cases",
                    "9",
                    "--seed",
                    "123",
                    "--output-directory",
                    str(output_directory),
                ]
            )

            self.assertEqual(return_code, 0)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(report["case_count"], 9)
            self.assertIn("recommendation", report)
            with csv_path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 15)
        finally:
            json_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)
            output_directory.rmdir()


if __name__ == "__main__":
    unittest.main()
