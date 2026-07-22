import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from health.fault_isolation import isolate_cross_subsystem_faults  # noqa: E402
from health.health_state import apply_alert_persistence  # noqa: E402
from health.model_assurance import assess_model_applicability  # noqa: E402
from health.power_health import aggregate_all_health, assess_power_subsystem  # noqa: E402
from health.subsystem_health import assess_non_power_subsystems  # noqa: E402


class FakeModel:
    health_model_metadata_ = {
        "training_profile": {
            "numerical": {"battery_voltage_v": {"minimum": 20, "maximum": 30}},
            "categorical": {"spacecraft_mode": ["nominal", "safe"]},
        }
    }


class HealthAssuranceTests(unittest.TestCase):
    def test_missing_subsystem_data_is_unknown(self):
        results = assess_non_power_subsystems({"input_data_quality": "complete"})
        self.assertEqual(results["thermal"]["status"], "Unknown")
        self.assertEqual(results["propulsion"]["status"], "Unknown")
        self.assertEqual(assess_power_subsystem({})["status"], "Unknown")

    def test_warning_requires_confirmation_and_clears_with_hysteresis(self):
        state = {}
        first = apply_alert_persistence(
            {"status": "Warning"}, "2026-01-01T00:00:00Z", state
        )
        second = apply_alert_persistence(
            {"status": "Warning"}, "2026-01-01T00:01:00Z", state
        )
        clearing = apply_alert_persistence(
            {"status": "Healthy"}, "2026-01-01T00:02:00Z", state
        )
        cleared = apply_alert_persistence(
            {"status": "Healthy"}, "2026-01-01T00:03:00Z", state
        )
        self.assertEqual(first["persistence"]["alert_state"], "observed")
        self.assertEqual(second["persistence"]["alert_state"], "confirmed")
        self.assertEqual(clearing["persistence"]["alert_state"], "clearing")
        self.assertEqual(cleared["effective_status"], "Healthy")

    def test_critical_alert_confirms_immediately(self):
        result = apply_alert_persistence(
            {"status": "Critical"}, "2026-01-01T00:00:00Z", {}
        )
        self.assertEqual(result["effective_status"], "Critical")
        self.assertEqual(result["persistence"]["alert_state"], "confirmed")

    def test_cross_subsystem_fault_hypothesis(self):
        results = {
            "power": {"status": "Critical", "fault_codes": ["PWR_BATTERY_OVERCURRENT_CRITICAL"]},
            "communications": {"status": "Critical", "fault_codes": []},
            "cdh": {"status": "Critical", "fault_codes": []},
            "thermal": {"status": "Warning", "fault_codes": []},
            "payload": {"status": "Healthy", "fault_codes": []},
            "adcs": {"status": "Healthy", "fault_codes": []},
            "command_control": {"status": "Healthy", "fault_codes": []},
        }
        identifiers = {
            item["hypothesis_id"] for item in isolate_cross_subsystem_faults(results)
        }
        self.assertIn("FI_POWER_COMMUNICATIONS_CASCADE", identifiers)
        self.assertIn("FI_POWER_CDH_CASCADE", identifiers)
        self.assertIn("FI_ELECTRICAL_THERMAL_LOAD", identifiers)

    def test_model_accepts_in_domain_and_abstains_out_of_domain(self):
        accepted = assess_model_applicability(
            FakeModel(), {"battery_voltage_v": 25, "spacecraft_mode": "nominal"}
        )
        rejected = assess_model_applicability(
            FakeModel(), {"battery_voltage_v": 100, "spacecraft_mode": "unknown"}
        )
        self.assertTrue(accepted["accepted"])
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["decision"], "abstained")

    def test_abstained_ml_is_not_an_overall_contributor(self):
        overall = aggregate_all_health(
            "Critical", {"power": {"status": "Healthy"}}, ml_accepted=False
        )
        self.assertEqual(overall["status"], "Healthy")
        self.assertNotIn("ml_classifier", overall["contributors"])


if __name__ == "__main__":
    unittest.main()
