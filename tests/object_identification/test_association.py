import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.object_identification.association import (
    AssociationConfig,
    build_prediction,
    calculate_association_score,
    load_association_config,
    main,
)
from src.object_identification.input_pipeline import (
    ObjectIdentificationInputError,
    prepare_identification_input,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "object_identification"
)


def load_fixture(name: str):
    return json.loads((FIXTURES_ROOT / name).read_text(encoding="utf-8"))


class ObjectAssociationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observation = load_fixture("tracking-observation.example.json")
        self.catalog = load_fixture("object-catalog-record.example.json")
        self.orbital = load_fixture("orbital-state-record.example.json")
        self.affiliation = load_fixture("affiliation-record.example.json")
        self.config = load_association_config()

    def prepared(self):
        return prepare_identification_input(
            self.observation,
            self.catalog,
            self.orbital,
            self.affiliation,
            prepared_at=datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc),
        )

    def prediction(self):
        return build_prediction(
            self.prepared(),
            self.config,
            generated_at=datetime(2026, 7, 27, 19, 1, tzinfo=timezone.utc),
        )

    def test_close_candidate_is_known_other(self) -> None:
        prediction = self.prediction()

        self.assertEqual(prediction["identity_status"], "known")
        self.assertEqual(prediction["affiliation"], "other")
        self.assertEqual(prediction["classification"], "known_other")
        self.assertEqual(prediction["canonical_object_id"], "CAT-2001")
        self.assertGreaterEqual(
            prediction["match_score"], self.config.match_threshold
        )

    def test_distant_candidate_is_unknown_without_provenance(self) -> None:
        self.orbital["position_km"][0] += 50
        prediction = self.prediction()

        self.assertEqual(prediction["identity_status"], "unknown")
        self.assertEqual(prediction["affiliation"], "unknown")
        self.assertEqual(prediction["classification"], "unknown")
        self.assertIsNone(prediction["canonical_object_id"])
        self.assertIsNone(prediction["catalog_provenance"])
        self.assertIsNone(prediction["affiliation_provenance"])

    def test_low_measurement_quality_can_reject_geometric_match(self) -> None:
        self.observation["measurement_quality"] = 0.2
        prediction = self.prediction()

        self.assertEqual(prediction["classification"], "unknown")

    def test_score_components_are_bounded_and_exposed(self) -> None:
        metrics = calculate_association_score(self.prepared(), self.config)

        self.assertGreaterEqual(metrics["match_score"], 0)
        self.assertLessEqual(metrics["match_score"], 1)
        self.assertGreaterEqual(metrics["position_residual_km"], 0)
        self.assertGreaterEqual(metrics["velocity_residual_km_s"], 0)

    def test_invalid_config_scale_is_rejected(self) -> None:
        path = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_invalid_association_config.json"
        )
        value = json.loads(
            (
                REPOSITORY_ROOT
                / "config"
                / "object-identification-association.json"
            ).read_text(encoding="utf-8")
        )
        value["position_scale_km"] = 0
        try:
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                ObjectIdentificationInputError, "greater than zero"
            ):
                load_association_config(path)
        finally:
            path.unlink(missing_ok=True)

    def test_threshold_is_inclusive(self) -> None:
        metrics = calculate_association_score(self.prepared(), self.config)
        exact_config = AssociationConfig(
            version="test",
            validation_status="prototype_unvalidated",
            position_scale_km=self.config.position_scale_km,
            velocity_scale_km_s=self.config.velocity_scale_km_s,
            match_threshold=metrics["match_score"],
        )

        prediction = build_prediction(self.prepared(), exact_config)

        self.assertEqual(prediction["identity_status"], "known")

    def test_cli_writes_schema_valid_prediction(self) -> None:
        output_path = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_association_cli_test.json"
        )
        try:
            return_code = main(
                [
                    "--observation",
                    str(FIXTURES_ROOT / "tracking-observation.example.json"),
                    "--catalog",
                    str(FIXTURES_ROOT / "object-catalog-record.example.json"),
                    "--orbital",
                    str(FIXTURES_ROOT / "orbital-state-record.example.json"),
                    "--affiliation",
                    str(FIXTURES_ROOT / "affiliation-record.example.json"),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(return_code, 0)
            prediction = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(prediction["classification"], "known_other")
        finally:
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
