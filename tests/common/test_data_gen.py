import contextlib
import io
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from common.data_gen import closeApproach, design_close_approach_orbit  # noqa: E402


class CloseApproachOrbitTests(unittest.TestCase):
    TARGET_ELEMENTS = (7000.0, 0.0, 0.0, 0.0, 0.0)

    def test_circular_coplanar_orbits_recover_radial_separation(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = closeApproach(
                target_elems=self.TARGET_ELEMENTS,
                a0=7020.0,
                e0=0.0,
                i0=0.0,
                d_desired=20.0,
                verbose=False,
                use_auto=False,
                grid_n=24,
                direct_seed_count=2,
                max_refine_candidates=2,
            )

        self.assertTrue(result["solutions"])
        self.assertAlmostEqual(
            result["solutions"][0]["achieved_moid_km"], 20.0, places=6
        )
        self.assertNotIn("outside the roughly achievable range", output.getvalue())

    def test_wrapper_applies_requested_candidate_offsets(self) -> None:
        result = design_close_approach_orbit(
            self.TARGET_ELEMENTS,
            desired_distance_km=20.0,
            a_offset_km=20.0,
            inclination_offset_deg=0.0,
            verbose=False,
            use_auto=False,
            grid_n=24,
            direct_seed_count=2,
            max_refine_candidates=2,
        )

        self.assertEqual(result["target_elems"], self.TARGET_ELEMENTS)
        self.assertEqual(result["a0"], 7020.0)
        self.assertEqual(result["i0"], 0.0)
        self.assertAlmostEqual(
            result["solutions"][0]["achieved_moid_km"], 20.0, places=6
        )

    def test_wrapper_rejects_unsupported_target_shape(self) -> None:
        with self.assertRaisesRegex(TypeError, "Unsupported target type"):
            design_close_approach_orbit((1.0, 2.0), verbose=False)


if __name__ == "__main__":
    unittest.main()
