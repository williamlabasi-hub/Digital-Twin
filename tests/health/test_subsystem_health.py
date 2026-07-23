import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from health.power_health import aggregate_all_health  # noqa: E402
from health.subsystem_health import assess_non_power_subsystems  # noqa: E402


class SubsystemHealthTests(unittest.TestCase):
    def base_row(self):
        return {
            "timestamp": "2026-01-01T01:00:00Z",
            "flight_computer_temperature_c": 30,
            "payload_temperature_c": 30,
            "radiator_temperature_c": 20,
            "gyro_x_rate_deg_s": 0.1,
            "gyro_y_rate_deg_s": 0.1,
            "gyro_z_rate_deg_s": 0.1,
            "reaction_wheel_1_speed_rpm": 3000,
            "reaction_wheel_2_speed_rpm": -3000,
            "reaction_wheel_3_speed_rpm": 2500,
            "downlink_rate_kbps": 800,
            "communications_pass_state": "active",
            "memory_usage_pct": 40,
            "memory_corrected_error_count": 0,
            "propellant_remaining_pct": 80,
            "thruster_firing": False,
            "thruster_pulse_width_ms": 0,
            "time_sync_offset_ms": 2,
            "clock_drift_us_day": 3,
            "command_queue_depth": 2,
            "latest_command_status": "successful",
            "input_data_quality": "complete",
        }

    def assess(self, **updates):
        row = self.base_row()
        row.update(updates)
        return assess_non_power_subsystems(row)

    def test_nominal_record_keeps_all_subsystems_healthy(self):
        results = self.assess()
        self.assertEqual(
            set(results),
            {"thermal", "payload", "adcs", "communications", "cdh", "propulsion", "timing", "command_control"},
        )
        self.assertTrue(all(result["status"] == "Healthy" for result in results.values()))

    def test_thermal_and_payload_overtemperature(self):
        results = self.assess(
            flight_computer_temperature_c=95,
            payload_temperature_c=90,
        )
        self.assertEqual(results["thermal"]["status"], "Critical")
        self.assertEqual(results["payload"]["status"], "Critical")

    def test_adcs_wheel_overspeed(self):
        result = self.assess(reaction_wheel_2_speed_rpm=-10000)["adcs"]
        self.assertEqual(result["status"], "Critical")
        self.assertIn("ADCS_WHEEL_OVERSPEED_CRITICAL", result["fault_codes"])

    def test_low_downlink_outside_pass_is_not_fault(self):
        result = self.assess(
            downlink_rate_kbps=0, communications_pass_state="inactive"
        )["communications"]
        self.assertEqual(result["status"], "Healthy")
        self.assertTrue(result["context_notes"])

    def test_low_downlink_during_pass_is_critical(self):
        result = self.assess(
            downlink_rate_kbps=50, communications_pass_state="active"
        )["communications"]
        self.assertEqual(result["status"], "Critical")

    def test_memory_propellant_timing_and_command_faults(self):
        results = self.assess(
            memory_usage_pct=98,
            propellant_remaining_pct=3,
            time_sync_offset_ms=1200,
            command_queue_depth=60,
        )
        self.assertEqual(results["cdh"]["status"], "Critical")
        self.assertEqual(results["propulsion"]["status"], "Critical")
        self.assertEqual(results["timing"]["status"], "Critical")
        self.assertEqual(results["command_control"]["status"], "Critical")

    def test_corrected_memory_error_delta_is_detected(self):
        previous = self.base_row()
        previous["timestamp"] = "2026-01-01T00:00:00Z"
        row = self.base_row()
        row["memory_corrected_error_count"] = 3
        result = assess_non_power_subsystems(row, previous)["cdh"]
        self.assertIn("CDH_CORRECTED_ERRORS_INCREASING", result["fault_codes"])

    def test_aggregate_uses_most_severe_subsystem(self):
        subsystems = self.assess(time_sync_offset_ms=1200)
        subsystems["power"] = {"status": "Healthy"}
        overall = aggregate_all_health("Healthy", subsystems)
        self.assertEqual(overall["status"], "Critical")
        self.assertIn("timing", overall["contributors"])


if __name__ == "__main__":
    unittest.main()
