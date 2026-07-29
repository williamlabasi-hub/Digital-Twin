import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.object_identification.data_gen_adapter import (
    build_identification_records,
    main as adapter_main,
)
from src.object_identification.association import (
    build_ranked_prediction,
    load_association_config,
)
from src.object_identification.input_pipeline import (
    ObjectIdentificationInputError,
)
from src.common.data_gen import orbit_catalog
from src.preprocessing.tle_propagator import (
    TLE_REQUEST_TIMEOUT_SECONDS,
    propagate,
    tle_request,
)


def propagation(
    *,
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
        "altitude": 420.0,
        "latitude": 1.0,
        "longitude": 2.0,
        "velocity_km_s": {
            "radial": 0.01,
            "along": 7.6,
            "cross": 0.02,
        },
        "speed_km_s": 7.6,
        "sunlit": True,
        "time": {
            "year": 2026,
            "month": 7,
            "day": 29,
            "hour": 16,
            "minute": 0,
            "second": 0,
        },
    }


class DataGenAdapterTests(unittest.TestCase):
    def test_data_gen_is_importable_from_repository_package(self) -> None:
        self.assertTrue(callable(orbit_catalog))

    def test_static_tle_propagation_uses_requested_utc_instant(self) -> None:
        tle = {
            "name": "ISS (ZARYA)",
            "line1": (
                "1 25544U 98067A   24001.50000000  .00016717  "
                "00000-0  10270-3 0  9000"
            ),
            "line2": (
                "2 25544  51.6416 339.6058 0007976  35.9128 "
                "324.2381 15.50232710000010"
            ),
        }
        state = propagate(
            tle,
            {
                "year": 2024,
                "month": 1,
                "day": 1,
                "hour": 12,
                "minute": 0,
                "second": 0,
            },
        )

        expected_position_km = [
            6352.032354816216,
            -2400.573448630982,
            -14.805308427854303,
        ]
        for actual, expected in zip(
            state["position_km"],
            expected_position_km,
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_tle_request_enforces_timeout_and_http_success(self) -> None:
        response = Mock()
        response.json.return_value = {
            "name": "ISS",
            "line1": "line 1",
            "line2": "line 2",
        }
        requests_module = Mock()
        requests_module.get.return_value = response

        with patch.dict(sys.modules, {"requests": requests_module}):
            result = tle_request(25544)

        self.assertEqual(result["name"], "ISS")
        requests_module.get.assert_called_once()
        _, kwargs = requests_module.get.call_args
        self.assertEqual(
            kwargs["timeout"],
            TLE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status.assert_called_once_with()

    def setUp(self) -> None:
        self.observation = propagation(
            catalog=90001,
            position=[6628.1, 1045.2, -421.7],
            velocity=[-1.08, 7.31, 1.42],
        )
        self.candidate = propagation(
            catalog=25544,
            position=[6627.9, 1045.6, -421.5],
            velocity=[-1.081, 7.309, 1.421],
        )

    def build(self) -> dict:
        return build_identification_records(
            self.observation,
            self.candidate,
            observation_id="OBS-DATA-GEN-1",
            track_id="TRACK-DATA-GEN-1",
            sensor_id="SIMULATED-SENSOR",
            sensor_type="other",
            data_source="DATA_GEN",
            measurement_quality=0.8,
            catalog_source="TLE_API",
            object_type="payload",
            affiliation="other",
            affiliation_authority="PROTOTYPE_OPERATOR",
            affiliation_source_record_id="AFF-25544",
        )

    def test_builds_schema_valid_cross_record_evidence(self) -> None:
        records = self.build()

        self.assertTrue(records["prepared"]["preparation_status"]["valid"])
        self.assertEqual(
            records["observation"]["position_km"],
            self.observation["position_km"],
        )
        self.assertEqual(
            records["orbital"]["velocity_km_s"],
            self.candidate["cartesian_velocity_km_s"],
        )
        self.assertEqual(
            records["catalog"]["canonical_object_id"],
            "CAT-25544",
        )
        self.assertIn(
            "not inferred",
            records["affiliation"]["review_notes"],
        )

    def test_generated_records_run_through_association(self) -> None:
        records = self.build()

        prediction = build_ranked_prediction(
            [records["prepared"]],
            load_association_config(),
        )

        self.assertEqual(
            prediction["candidate_selection"]["candidate_count"],
            1,
        )
        self.assertEqual(
            prediction["candidate_rankings"][0]["canonical_object_id"],
            "CAT-25544",
        )

    def test_rejects_radial_velocity_in_place_of_cartesian_vector(self) -> None:
        del self.observation["cartesian_velocity_km_s"]

        with self.assertRaisesRegex(
            ObjectIdentificationInputError,
            "three-component Cartesian vector",
        ):
            self.build()

    def test_rejects_mismatched_frames(self) -> None:
        self.candidate["coordinate_frame"] = "TEME"

        with self.assertRaisesRegex(
            ObjectIdentificationInputError,
            "coordinate frames do not match",
        ):
            self.build()

    def test_cli_writes_valid_record_bundle(self) -> None:
        test_root = Path(__file__).resolve().parent
        observation_path = test_root / "_adapter_observation.json"
        candidate_path = test_root / "_adapter_candidate.json"
        output_path = test_root / "_adapter_records.json"
        try:
            observation_path.write_text(
                json.dumps(self.observation),
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(self.candidate),
                encoding="utf-8",
            )

            result = adapter_main(
                [
                    "--observation-input",
                    str(observation_path),
                    "--candidate-input",
                    str(candidate_path),
                    "--output",
                    str(output_path),
                    "--observation-id",
                    "OBS-DATA-GEN-1",
                    "--track-id",
                    "TRACK-DATA-GEN-1",
                    "--sensor-id",
                    "SIMULATED-SENSOR",
                    "--sensor-type",
                    "other",
                    "--data-source",
                    "DATA_GEN",
                    "--measurement-quality",
                    "0.8",
                    "--catalog-source",
                    "TLE_API",
                    "--object-type",
                    "payload",
                    "--affiliation",
                    "other",
                    "--affiliation-authority",
                    "PROTOTYPE_OPERATOR",
                    "--affiliation-source-record-id",
                    "AFF-25544",
                ]
            )

            self.assertEqual(result, 0)
            bundle = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(bundle["prepared"]["preparation_status"]["valid"])
        finally:
            observation_path.unlink(missing_ok=True)
            candidate_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
