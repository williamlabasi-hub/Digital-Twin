import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_ROOT = (
    REPOSITORY_ROOT / "docs" / "requirements" / "object_identification"
)
FIXTURES_ROOT = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "object_identification"
)

SCHEMA_FIXTURE_PAIRS = {
    "tracking-observation.schema.json": "tracking-observation.example.json",
    "object-catalog-record.schema.json": "object-catalog-record.example.json",
    "orbital-state-record.schema.json": "orbital-state-record.example.json",
    "affiliation-record.schema.json": "affiliation-record.example.json",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ObjectIdentificationInputSchemaTests(unittest.TestCase):
    def validator(self, schema_name: str) -> Draft202012Validator:
        schema = load_json(REQUIREMENTS_ROOT / schema_name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def fixture(self, fixture_name: str):
        return load_json(FIXTURES_ROOT / fixture_name)

    def test_all_input_examples_match_their_schemas(self) -> None:
        for schema_name, fixture_name in SCHEMA_FIXTURE_PAIRS.items():
            with self.subTest(schema=schema_name):
                errors = list(
                    self.validator(schema_name).iter_errors(
                        self.fixture(fixture_name)
                    )
                )
                self.assertEqual(errors, [])

    def test_tracking_quality_must_be_between_zero_and_one(self) -> None:
        record = self.fixture("tracking-observation.example.json")
        record["measurement_quality"] = 1.1

        self.assertTrue(
            list(
                self.validator("tracking-observation.schema.json").iter_errors(
                    record
                )
            )
        )

    def test_tracking_state_vectors_must_have_three_components(self) -> None:
        record = self.fixture("tracking-observation.example.json")
        record["position_km"] = [1.0, 2.0]

        self.assertTrue(
            list(
                self.validator("tracking-observation.schema.json").iter_errors(
                    record
                )
            )
        )

    def test_affiliation_record_cannot_designate_unknown(self) -> None:
        record = self.fixture("affiliation-record.example.json")
        record["affiliation"] = "unknown"

        self.assertTrue(
            list(
                self.validator("affiliation-record.schema.json").iter_errors(
                    record
                )
            )
        )

    def test_catalog_record_requires_provenance(self) -> None:
        record = self.fixture("object-catalog-record.example.json")
        del record["catalog_source"]

        self.assertTrue(
            list(
                self.validator("object-catalog-record.schema.json").iter_errors(
                    record
                )
            )
        )

    def test_unexpected_input_fields_are_rejected(self) -> None:
        record = self.fixture("orbital-state-record.example.json")
        record["uncontrolled_note"] = "not part of the interface"

        self.assertTrue(
            list(
                self.validator("orbital-state-record.schema.json").iter_errors(
                    record
                )
            )
        )

    def test_fixture_identity_and_orbital_references_are_consistent(self) -> None:
        catalog = self.fixture("object-catalog-record.example.json")
        orbit = self.fixture("orbital-state-record.example.json")
        affiliation = self.fixture("affiliation-record.example.json")

        self.assertEqual(
            catalog["canonical_object_id"], orbit["subject_id"]
        )
        self.assertEqual(
            catalog["canonical_object_id"], affiliation["canonical_object_id"]
        )
        self.assertEqual(
            catalog["orbital_record_id"], orbit["orbital_record_id"]
        )

    def test_multi_candidate_demo_records_are_valid_and_consistent(self) -> None:
        demo_root = FIXTURES_ROOT / "multi_candidate"
        for catalog_path in demo_root.glob("*.catalog.json"):
            prefix = catalog_path.name.removesuffix(".catalog.json")
            orbital_path = demo_root / f"{prefix}.orbital.json"
            affiliation_path = demo_root / f"{prefix}.affiliation.json"
            with self.subTest(candidate=prefix):
                catalog = load_json(catalog_path)
                orbital = load_json(orbital_path)
                affiliation = load_json(affiliation_path)
                self.assertEqual(
                    list(
                        self.validator(
                            "object-catalog-record.schema.json"
                        ).iter_errors(catalog)
                    ),
                    [],
                )
                self.assertEqual(
                    list(
                        self.validator(
                            "orbital-state-record.schema.json"
                        ).iter_errors(orbital)
                    ),
                    [],
                )
                self.assertEqual(
                    list(
                        self.validator(
                            "affiliation-record.schema.json"
                        ).iter_errors(affiliation)
                    ),
                    [],
                )
                self.assertEqual(
                    catalog["canonical_object_id"], orbital["subject_id"]
                )
                self.assertEqual(
                    catalog["canonical_object_id"],
                    affiliation["canonical_object_id"],
                )
                self.assertEqual(
                    catalog["orbital_record_id"], orbital["orbital_record_id"]
                )


if __name__ == "__main__":
    unittest.main()
