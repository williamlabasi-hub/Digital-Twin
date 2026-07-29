import json
import unittest
from copy import deepcopy
from pathlib import Path

from src.object_identification.data_gen_pipeline import (
    build_data_gen_prediction,
    load_candidate_manifest,
    main as pipeline_main,
)
from src.object_identification.input_pipeline import (
    ObjectIdentificationInputError,
)


TEST_ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = (
    TEST_ROOT.parent
    / "fixtures"
    / "object_identification"
    / "data_gen"
)


def propagation(
    catalog: int,
    position: list[float],
    velocity: list[float],
) -> dict:
    return {
        "name": f"OBJECT {catalog}",
        "catalog": catalog,
        "coordinate_frame": "ECI",
        "position_km": position,
        "cartesian_velocity_km_s": velocity,
        "time": {
            "year": 2026,
            "month": 7,
            "day": 29,
            "hour": 16,
            "minute": 0,
            "second": 0,
        },
    }


def candidate(
    catalog: int,
    position: list[float],
    velocity: list[float],
) -> dict:
    return {
        "propagation": propagation(catalog, position, velocity),
        "catalog_source": "TLE_API",
        "object_type": "payload",
        "affiliation": "other",
        "affiliation_authority": "PROTOTYPE_OPERATOR",
        "affiliation_source_record_id": f"AFF-{catalog}",
    }


class DataGenPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observation = propagation(
            90001,
            [6628.1, 1045.2, -421.7],
            [-1.08, 7.31, 1.42],
        )
        self.arguments = {
            "observation_id": "OBS-PIPELINE-1",
            "track_id": "TRACK-PIPELINE-1",
            "sensor_id": "SIMULATED-SENSOR",
            "sensor_type": "other",
            "data_source": "DATA_GEN_TEST",
            "measurement_quality": 0.9,
        }

    def test_ranks_multiple_candidates_and_selects_clear_match(self) -> None:
        candidates = [
            candidate(
                25544,
                [6627.9, 1045.6, -421.5],
                [-1.081, 7.309, 1.421],
            ),
            candidate(
                40002,
                [6632.1, 1045.2, -421.7],
                [-1.08, 7.31, 1.42],
            ),
            candidate(
                40003,
                [6653.1, 1045.2, -421.7],
                [-1.08, 7.31, 1.42],
            ),
        ]

        bundle = build_data_gen_prediction(
            self.observation,
            candidates,
            **self.arguments,
        )

        prediction = bundle["prediction"]
        self.assertEqual(
            prediction["candidate_selection"]["decision_basis"],
            "clear_match",
        )
        self.assertEqual(
            prediction["candidate_selection"]["candidate_count"],
            3,
        )
        self.assertEqual(prediction["canonical_object_id"], "CAT-25544")
        self.assertEqual(
            [
                ranking["canonical_object_id"]
                for ranking in prediction["candidate_rankings"]
            ],
            ["CAT-25544", "CAT-40002", "CAT-40003"],
        )

    def test_withholds_identity_for_ambiguous_generated_candidates(self) -> None:
        candidates = [
            candidate(
                25544,
                [6627.9, 1045.6, -421.5],
                [-1.081, 7.309, 1.421],
            ),
            candidate(
                40004,
                [6628.0, 1045.55, -421.55],
                [-1.0805, 7.3095, 1.4205],
            ),
        ]

        bundle = build_data_gen_prediction(
            self.observation,
            candidates,
            **self.arguments,
        )

        prediction = bundle["prediction"]
        self.assertEqual(
            prediction["candidate_selection"]["decision_basis"],
            "ambiguous",
        )
        self.assertEqual(prediction["identity_status"], "unknown")
        self.assertIsNone(prediction["canonical_object_id"])

    def test_rejects_duplicate_generated_candidate_identities(self) -> None:
        repeated = candidate(
            25544,
            [6627.9, 1045.6, -421.5],
            [-1.081, 7.309, 1.421],
        )

        with self.assertRaisesRegex(
            ObjectIdentificationInputError,
            "duplicate candidate",
        ):
            build_data_gen_prediction(
                self.observation,
                [repeated, deepcopy(repeated)],
                **self.arguments,
            )

    def test_manifest_paths_are_resolved_relative_to_manifest(self) -> None:
        candidates = load_candidate_manifest(
            FIXTURE_ROOT / "candidate-manifest.example.json"
        )

        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0]["propagation"]["catalog"], 25544)

    def test_cli_writes_multi_candidate_prediction_bundle(self) -> None:
        output_path = TEST_ROOT / "_data_gen_pipeline_output.json"
        try:
            result = pipeline_main(
                [
                    "--observation-input",
                    str(
                        FIXTURE_ROOT
                        / "observation-propagation.example.json"
                    ),
                    "--candidate-manifest",
                    str(
                        FIXTURE_ROOT
                        / "candidate-manifest.example.json"
                    ),
                    "--output",
                    str(output_path),
                    "--observation-id",
                    "OBS-PIPELINE-CLI-1",
                    "--track-id",
                    "TRACK-PIPELINE-CLI-1",
                    "--sensor-id",
                    "SIMULATED-SENSOR",
                    "--sensor-type",
                    "other",
                    "--data-source",
                    "DATA_GEN_TEST",
                    "--measurement-quality",
                    "0.9",
                ]
            )

            self.assertEqual(result, 0)
            bundle = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                bundle["prediction"]["candidate_selection"][
                    "candidate_count"
                ],
                3,
            )
            self.assertEqual(
                bundle["prediction"]["canonical_object_id"],
                "CAT-25544",
            )
        finally:
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
