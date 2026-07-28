import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.object_identification.input_pipeline import (
    ObjectIdentificationInputError,
    main,
    prepare_identification_input,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "object_identification"
)


def load_fixture(name: str):
    return json.loads((FIXTURES_ROOT / name).read_text(encoding="utf-8"))


class ObjectIdentificationInputPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observation = load_fixture("tracking-observation.example.json")
        self.catalog = load_fixture("object-catalog-record.example.json")
        self.orbital = load_fixture("orbital-state-record.example.json")
        self.affiliation = load_fixture("affiliation-record.example.json")

    def prepare(self):
        return prepare_identification_input(
            self.observation,
            self.catalog,
            self.orbital,
            self.affiliation,
            prepared_at=datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc),
        )

    def test_valid_records_produce_normalized_unclassified_evidence(self) -> None:
        result = self.prepare()

        self.assertEqual(result["observation"]["track_id"], "TRACK-0091")
        self.assertEqual(
            result["candidate"]["canonical_object_id"], "CAT-2001"
        )
        self.assertEqual(result["candidate"]["affiliation"], "other")
        self.assertTrue(result["preparation_status"]["valid"])
        self.assertFalse(
            result["preparation_status"]["classification_performed"]
        )
        self.assertNotIn("classification", result)

    def test_schema_violation_is_rejected_before_integration(self) -> None:
        self.observation["measurement_quality"] = 2.0

        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "schema validation failed"
        ):
            self.prepare()

    def test_mismatched_canonical_identity_is_rejected(self) -> None:
        self.affiliation["canonical_object_id"] = "CAT-DIFFERENT"

        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "does not match catalog"
        ):
            self.prepare()

    def test_mismatched_coordinate_frames_are_rejected(self) -> None:
        self.orbital["coordinate_frame"] = "TEME"

        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "coordinate frames do not match"
        ):
            self.prepare()

    def test_future_orbital_state_is_rejected(self) -> None:
        self.orbital["timestamp"] = "2026-07-27T19:00:00Z"

        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "later than the observation"
        ):
            self.prepare()

    def test_expired_affiliation_is_rejected(self) -> None:
        self.affiliation["affiliation_expires_at"] = "2026-07-27T18:00:00Z"

        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "not effective"
        ):
            self.prepare()

    def test_catalog_outside_validity_window_is_rejected(self) -> None:
        self.catalog["valid_from"] = "2026-07-27T19:30:00Z"

        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "not valid"
        ):
            self.prepare()

    def test_cli_writes_prepared_json(self) -> None:
        output_path = (
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / "_prepared_cli_test.json"
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
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(
                result["preparation_status"]["classification_performed"]
            )
        finally:
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
