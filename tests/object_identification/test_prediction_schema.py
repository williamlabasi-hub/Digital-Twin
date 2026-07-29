import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from src.object_identification.association import PREDICTION_SCHEMA_PATH


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "object_identification"
    / "unknown-prediction.example.json"
)


class ObjectIdentificationPredictionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            PREDICTION_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        cls.example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def errors(self, record):
        return list(self.validator.iter_errors(record))

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_unknown_example_is_valid(self) -> None:
        self.assertEqual(self.errors(self.example), [])

    def test_unknown_identity_cannot_be_red(self) -> None:
        record = copy.deepcopy(self.example)
        record["affiliation"] = "red"
        record["classification"] = "known_red"

        self.assertTrue(self.errors(record))

    def test_known_identity_requires_catalog_and_affiliation_provenance(self) -> None:
        record = copy.deepcopy(self.example)
        record["identity_status"] = "known"
        record["affiliation"] = "blue"
        record["classification"] = "known_blue"
        record["canonical_object_id"] = "CAT-1001"

        self.assertTrue(self.errors(record))

    def test_known_other_with_provenance_is_valid(self) -> None:
        record = copy.deepcopy(self.example)
        record["identity_status"] = "known"
        record["affiliation"] = "other"
        record["classification"] = "known_other"
        record["canonical_object_id"] = "CAT-2001"
        record["catalog_provenance"] = {
            "catalog_source": "PROTOTYPE_CATALOG",
            "catalog_record_id": "CAT-2001",
            "catalog_record_valid_at": "2026-07-27T18:59:00Z"
        }
        record["affiliation_provenance"] = {
            "affiliation_authority": "PROTOTYPE_AUTHORITY",
            "affiliation_source_record_id": "AFF-2001",
            "affiliation_effective_at": "2026-01-01T00:00:00Z",
            "affiliation_expires_at": None
        }

        self.assertEqual(self.errors(record), [])


if __name__ == "__main__":
    unittest.main()
