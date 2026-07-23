import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from health.power_health import aggregate_health, assess_power_subsystem  # noqa: E402


class PowerHealthTests(unittest.TestCase):
    def base_row(self):
        return {
            "timestamp": "2026-01-01T01:00:00Z",
            "battery_voltage_v": 28.0,
            "battery_current_a": -3.0,
            "battery_state_of_charge_pct": 80.0,
            "solar_array_voltage_v": 32.0,
            "solar_array_current_a": 5.0,
            "eclipse_state": "sunlight",
            "solar_array_configuration": "deployed",
            "battery_current_sign_convention": "positive_discharge",
            "input_data_quality": "complete",
        }

    def test_nominal_power_is_healthy(self):
        result = assess_power_subsystem(self.base_row())
        self.assertEqual(result["status"], "Healthy")
        self.assertEqual(result["fault_codes"], [])

    def test_critical_undervoltage_has_explainable_fault(self):
        row = self.base_row()
        row["battery_voltage_v"] = 20.0
        result = assess_power_subsystem(row)
        self.assertEqual(result["status"], "Critical")
        self.assertIn("PWR_BATTERY_UNDERVOLTAGE_CRITICAL", result["fault_codes"])
        self.assertEqual(result["evidence"][0]["observed_value"], 20.0)

    def test_signed_overcurrent_uses_magnitude(self):
        row = self.base_row()
        row["battery_current_a"] = -9.5
        result = assess_power_subsystem(row)
        self.assertIn("PWR_BATTERY_OVERCURRENT_CRITICAL", result["fault_codes"])

    def test_voltage_decline_is_detected_from_previous_sample(self):
        previous = self.base_row()
        previous["timestamp"] = "2026-01-01T00:00:00Z"
        row = self.base_row()
        row["battery_voltage_v"] = 26.5
        result = assess_power_subsystem(row, previous)
        self.assertAlmostEqual(
            result["trends"]["battery_voltage_rate_v_per_hour"], -1.5
        )
        self.assertIn("PWR_BATTERY_VOLTAGE_DECLINING", result["fault_codes"])

    def test_low_solar_current_in_sunlight_is_critical(self):
        row = self.base_row()
        row["solar_array_current_a"] = 0.2
        result = assess_power_subsystem(row)
        self.assertEqual(result["status"], "Critical")
        self.assertIn("PWR_SOLAR_CURRENT_LOW_IN_SUNLIGHT", result["fault_codes"])

    def test_low_solar_current_during_eclipse_is_not_a_fault(self):
        row = self.base_row()
        row["solar_array_current_a"] = 0.2
        row["eclipse_state"] = "eclipse"
        result = assess_power_subsystem(row)
        self.assertEqual(result["status"], "Healthy")
        self.assertNotIn("PWR_SOLAR_CURRENT_LOW_IN_SUNLIGHT", result["fault_codes"])

    def test_missing_solar_context_reduces_confidence(self):
        row = self.base_row()
        row["solar_array_current_a"] = 0.2
        row["eclipse_state"] = "unknown"
        result = assess_power_subsystem(row)
        self.assertEqual(result["status"], "Warning")
        self.assertLessEqual(result["confidence"], 0.6)
        self.assertTrue(result["context_notes"])

    def test_low_state_of_charge_is_critical(self):
        row = self.base_row()
        row["battery_state_of_charge_pct"] = 10
        result = assess_power_subsystem(row)
        self.assertIn("PWR_BATTERY_SOC_CRITICAL", result["fault_codes"])

    def test_power_proxies_preserve_sign_convention(self):
        result = assess_power_subsystem(self.base_row())
        self.assertEqual(result["power_proxies"]["solar_output_w"], 160.0)
        self.assertEqual(result["power_proxies"]["battery_power_w"], -84.0)
        self.assertEqual(
            result["power_proxies"]["battery_power_interpretation"],
            "positive_discharge",
        )

    def test_degraded_input_caps_confidence(self):
        row = self.base_row()
        row["input_data_quality"] = "degraded"
        result = assess_power_subsystem(row)
        self.assertLessEqual(result["confidence"], 0.4)

    def test_overall_health_uses_maximum_severity(self):
        result = aggregate_health("Healthy", "Critical")
        self.assertEqual(result["status"], "Critical")
        self.assertIn("power_subsystem_rules", result["contributors"])


if __name__ == "__main__":
    unittest.main()
