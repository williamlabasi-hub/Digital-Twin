"""Shared feature contract for health-model training and inference."""

NUMERICAL_FEATURES = [
    "battery_state_of_charge_pct",
    "solar_array_voltage_v",
    "solar_array_current_a",
    "flight_computer_temperature_c",
    "payload_temperature_c",
    "reaction_wheel_1_speed_rpm",
    "reaction_wheel_2_speed_rpm",
    "reaction_wheel_3_speed_rpm",
    "downlink_rate_kbps",
    "battery_voltage_v",
    "battery_current_a",
    "seconds_since_last_command",
]

CATEGORICAL_FEATURES = [
    "spacecraft_mode",
    "eclipse_state",
    "solar_array_configuration",
    "battery_current_sign_convention",
    "recent_command_name",
    "recent_command_status",
]

MODEL_FEATURES = NUMERICAL_FEATURES + CATEGORICAL_FEATURES
HEALTH_CLASSES = ("Healthy", "Warning", "Degraded", "Critical")

