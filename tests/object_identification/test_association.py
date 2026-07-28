import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from src.object_identification.association import (
    AssociationConfig,
    build_prediction,
    build_ranked_prediction,
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

    def add_covariance(
        self,
        *,
        position_variance_km2: float,
        velocity_variance_km2_s2: float,
        include_orbital: bool = True,
    ) -> None:
        self.observation["position_covariance_km2"] = [
            [position_variance_km2, 0, 0],
            [0, position_variance_km2, 0],
            [0, 0, position_variance_km2],
        ]
        self.observation["velocity_covariance_km2_s2"] = [
            [velocity_variance_km2_s2, 0, 0],
            [0, velocity_variance_km2_s2, 0],
            [0, 0, velocity_variance_km2_s2],
        ]
        if include_orbital:
            self.orbital["position_covariance_km2"] = deepcopy(
                self.observation["position_covariance_km2"]
            )
            self.orbital["velocity_covariance_km2_s2"] = deepcopy(
                self.observation["velocity_covariance_km2_s2"]
            )
        else:
            self.orbital.pop("position_covariance_km2", None)
            self.orbital.pop("velocity_covariance_km2_s2", None)

    def prepared_candidate(
        self,
        candidate_id: str,
        *,
        position_offset_km: float,
        affiliation: str = "other",
    ):
        catalog = deepcopy(self.catalog)
        orbital = deepcopy(self.orbital)
        affiliation_record = deepcopy(self.affiliation)
        catalog["canonical_object_id"] = candidate_id
        catalog["catalog_record_id"] = f"PROTOTYPE-{candidate_id}"
        catalog["orbital_record_id"] = f"ORB-{candidate_id}"
        orbital["subject_id"] = candidate_id
        orbital["orbital_record_id"] = f"ORB-{candidate_id}"
        orbital["position_km"][0] += position_offset_km
        affiliation_record["canonical_object_id"] = candidate_id
        affiliation_record["affiliation"] = affiliation
        affiliation_record[
            "affiliation_source_record_id"
        ] = f"AFF-{candidate_id}"
        return prepare_identification_input(
            deepcopy(self.observation),
            catalog,
            orbital,
            affiliation_record,
            prepared_at=datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc),
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

    def test_complete_covariance_uses_mahalanobis_scoring(self) -> None:
        self.add_covariance(
            position_variance_km2=1.0,
            velocity_variance_km2_s2=0.001,
        )

        metrics = calculate_association_score(self.prepared(), self.config)
        prediction = self.prediction()

        self.assertEqual(
            metrics["scoring_method"],
            "combined-covariance-mahalanobis-similarity",
        )
        self.assertEqual(metrics["uncertainty_status"], "combined_covariance")
        self.assertEqual(
            prediction["matching_method"]["name"],
            "combined-covariance-mahalanobis-similarity",
        )

    def test_noisy_covariance_penalizes_same_residual_less(self) -> None:
        self.add_covariance(
            position_variance_km2=0.01,
            velocity_variance_km2_s2=0.000001,
        )
        precise_score = calculate_association_score(
            self.prepared(), self.config
        )["match_score"]
        self.add_covariance(
            position_variance_km2=4.0,
            velocity_variance_km2_s2=0.001,
        )
        noisy_score = calculate_association_score(
            self.prepared(), self.config
        )["match_score"]

        self.assertGreater(noisy_score, precise_score)

    def test_incomplete_covariance_uses_scale_fallback(self) -> None:
        self.add_covariance(
            position_variance_km2=1.0,
            velocity_variance_km2_s2=0.001,
            include_orbital=False,
        )

        metrics = calculate_association_score(self.prepared(), self.config)

        self.assertEqual(
            metrics["scoring_method"],
            "position-velocity-gaussian-similarity",
        )
        self.assertEqual(metrics["uncertainty_status"], "scale_fallback")

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
            ambiguity_margin=self.config.ambiguity_margin,
            max_ranked_candidates=self.config.max_ranked_candidates,
        )

        prediction = build_prediction(self.prepared(), exact_config)

        self.assertEqual(prediction["identity_status"], "known")

    def test_multiple_candidates_are_ranked_by_score(self) -> None:
        prediction = build_ranked_prediction(
            [
                self.prepared_candidate(
                    "CAT-FAR", position_offset_km=20, affiliation="red"
                ),
                self.prepared_candidate(
                    "CAT-BEST", position_offset_km=0, affiliation="blue"
                ),
                self.prepared_candidate(
                    "CAT-MID", position_offset_km=8, affiliation="other"
                ),
            ],
            self.config,
        )

        self.assertEqual(prediction["canonical_object_id"], "CAT-BEST")
        self.assertEqual(prediction["classification"], "known_blue")
        self.assertEqual(
            prediction["candidate_selection"]["decision_basis"], "clear_match"
        )
        self.assertEqual(
            [
                candidate["canonical_object_id"]
                for candidate in prediction["candidate_rankings"]
            ],
            ["CAT-BEST", "CAT-MID", "CAT-FAR"],
        )

    def test_close_viable_candidates_are_ambiguous(self) -> None:
        prediction = build_ranked_prediction(
            [
                self.prepared_candidate("CAT-A", position_offset_km=0),
                self.prepared_candidate("CAT-B", position_offset_km=0.1),
            ],
            self.config,
        )

        self.assertEqual(prediction["identity_status"], "unknown")
        self.assertEqual(prediction["classification"], "unknown")
        self.assertEqual(
            prediction["candidate_selection"]["decision_basis"], "ambiguous"
        )
        self.assertTrue(
            all(
                candidate["meets_threshold"]
                for candidate in prediction["candidate_rankings"]
            )
        )

    def test_no_candidate_above_threshold_is_unknown(self) -> None:
        prediction = build_ranked_prediction(
            [
                self.prepared_candidate("CAT-A", position_offset_km=30),
                self.prepared_candidate("CAT-B", position_offset_km=40),
            ],
            self.config,
        )

        self.assertEqual(prediction["identity_status"], "unknown")
        self.assertEqual(
            prediction["candidate_selection"]["decision_basis"],
            "no_candidate_above_threshold",
        )

    def test_duplicate_candidate_ids_are_rejected(self) -> None:
        candidate = self.prepared_candidate("CAT-DUP", position_offset_km=0)
        with self.assertRaisesRegex(
            ObjectIdentificationInputError, "duplicate candidate"
        ):
            build_ranked_prediction([candidate, candidate], self.config)

    def test_ranked_results_respect_configured_limit(self) -> None:
        config = AssociationConfig(
            version=self.config.version,
            validation_status=self.config.validation_status,
            position_scale_km=self.config.position_scale_km,
            velocity_scale_km_s=self.config.velocity_scale_km_s,
            match_threshold=self.config.match_threshold,
            ambiguity_margin=self.config.ambiguity_margin,
            max_ranked_candidates=2,
        )
        candidates = [
            self.prepared_candidate(
                f"CAT-{index}", position_offset_km=float(index * 10)
            )
            for index in range(4)
        ]

        prediction = build_ranked_prediction(candidates, config)

        self.assertEqual(
            prediction["candidate_selection"]["candidate_count"], 4
        )
        self.assertEqual(len(prediction["candidate_rankings"]), 2)

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

    def test_cli_ranks_repeated_candidate_groups(self) -> None:
        temp_paths = [
            REPOSITORY_ROOT
            / "tests"
            / "object_identification"
            / f"_multi_candidate_{name}.json"
            for name in ("catalog", "orbital", "affiliation", "output")
        ]
        catalog_path, orbital_path, affiliation_path, output_path = temp_paths
        catalog = deepcopy(self.catalog)
        orbital = deepcopy(self.orbital)
        affiliation = deepcopy(self.affiliation)
        catalog["canonical_object_id"] = "CAT-CLI-FAR"
        catalog["catalog_record_id"] = "PROTOTYPE-CAT-CLI-FAR"
        catalog["orbital_record_id"] = "ORB-CLI-FAR"
        orbital["subject_id"] = "CAT-CLI-FAR"
        orbital["orbital_record_id"] = "ORB-CLI-FAR"
        orbital["position_km"][0] += 25
        affiliation["canonical_object_id"] = "CAT-CLI-FAR"
        affiliation["affiliation_source_record_id"] = "AFF-CLI-FAR"
        try:
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            orbital_path.write_text(json.dumps(orbital), encoding="utf-8")
            affiliation_path.write_text(
                json.dumps(affiliation), encoding="utf-8"
            )
            return_code = main(
                [
                    "--observation",
                    str(FIXTURES_ROOT / "tracking-observation.example.json"),
                    "--candidate",
                    str(catalog_path),
                    str(orbital_path),
                    str(affiliation_path),
                    "--candidate",
                    str(FIXTURES_ROOT / "object-catalog-record.example.json"),
                    str(FIXTURES_ROOT / "orbital-state-record.example.json"),
                    str(FIXTURES_ROOT / "affiliation-record.example.json"),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(return_code, 0)
            prediction = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                prediction["candidate_selection"]["candidate_count"], 2
            )
            self.assertEqual(
                prediction["candidate_rankings"][0]["canonical_object_id"],
                "CAT-2001",
            )
        finally:
            for path in temp_paths:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
