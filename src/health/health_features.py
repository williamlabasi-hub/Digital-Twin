"""Shared feature contract for health-model training and inference."""

NUMERICAL_FEATURES = [
    "solar_panel_current",
    "bus_temperature_c",
    "payload_temperature_c",
    "reaction_wheel_rpm",
    "downlink_rate_kbps",
    "battery_voltage",
    "battery_current",
    "seconds_since_last_command",
]

CATEGORICAL_FEATURES = [
    "mode",
    "recent_command_name",
    "recent_command_status",
]

MODEL_FEATURES = NUMERICAL_FEATURES + CATEGORICAL_FEATURES
HEALTH_CLASSES = ("Healthy", "Warning", "Degraded", "Critical")

