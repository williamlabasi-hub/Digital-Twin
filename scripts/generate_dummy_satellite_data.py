import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import math


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parent

HEALTH_CLASSES = [
    "Healthy",
    "Warning",
    "Degraded",
    "Critical",
]

POWER_SCENARIO_BY_HEALTH = {
    "Healthy": "nominal_power",
    "Warning": "battery_undervoltage_warning",
    "Degraded": "combined_power_degradation",
    "Critical": "critical_power_failure",
}

SATELLITE_IDS = [
    "SAT-001",
    "SAT-002",
    "SAT-003",
    "SAT-004",
]

COMMANDS_BY_HEALTH = {
    "Healthy": [
        "maintain_attitude",
        "collect_payload_data",
        "downlink_data",
        "charge_battery",
    ],
    "Warning": [
        "reduce_payload_load",
        "adjust_attitude",
        "restart_payload",
        "switch_to_backup_radio",
    ],
    "Degraded": [
        "enter_safe_mode",
        "reset_flight_computer",
        "disable_payload",
        "reduce_power_consumption",
    ],
    "Critical": [
        "emergency_shutdown",
        "enter_emergency_mode",
        "isolate_battery",
        "disable_nonessential_systems",
    ],
}

COMMAND_STATUS_WEIGHTS = {
    "Healthy": {
        "successful": 0.90,
        "failed": 0.03,
        "timed_out": 0.03,
        "cancelled": 0.04,
    },
    "Warning": {
        "successful": 0.70,
        "failed": 0.12,
        "timed_out": 0.10,
        "cancelled": 0.08,
    },
    "Degraded": {
        "successful": 0.50,
        "failed": 0.23,
        "timed_out": 0.17,
        "cancelled": 0.10,
    },
    "Critical": {
        "successful": 0.30,
        "failed": 0.35,
        "timed_out": 0.25,
        "cancelled": 0.10,
    },
}

FEATURE_RANGES = {
    "Healthy": {
        "battery_state_of_charge_pct": (70.0, 100.0),
        "battery_voltage": (27.0, 29.5),
        "battery_current": (3.0, 5.0),
        "solar_panel_current": (4.5, 7.0),
        "bus_temperature_c": (15.0, 32.0),
        "payload_temperature_c": (18.0, 36.0),
        "reaction_wheel_rpm": (2200, 4700),
        "downlink_rate_kbps": (750, 1200),
        "mode": ["nominal"],
    },
    "Warning": {
        "battery_state_of_charge_pct": (25.0, 55.0),
        "battery_voltage": (24.8, 27.3),
        "battery_current": (4.8, 6.5),
        "solar_panel_current": (2.5, 5.0),
        "bus_temperature_c": (30.0, 52.0),
        "payload_temperature_c": (32.0, 58.0),
        "reaction_wheel_rpm": (4200, 6800),
        "downlink_rate_kbps": (400, 850),
        "mode": ["nominal", "safe"],
    },
    "Degraded": {
        "battery_state_of_charge_pct": (12.0, 35.0),
        "battery_voltage": (21.8, 25.2),
        "battery_current": (6.0, 8.2),
        "solar_panel_current": (1.0, 3.0),
        "bus_temperature_c": (48.0, 72.0),
        "payload_temperature_c": (55.0, 78.0),
        "reaction_wheel_rpm": (6200, 8800),
        "downlink_rate_kbps": (100, 450),
        "mode": ["safe", "recovery"],
    },
    "Critical": {
        "battery_state_of_charge_pct": (2.0, 14.0),
        "battery_voltage": (18.0, 22.5),
        "battery_current": (7.8, 10.0),
        "solar_panel_current": (0.0, 1.5),
        "bus_temperature_c": (68.0, 92.0),
        "payload_temperature_c": (74.0, 98.0),
        "reaction_wheel_rpm": (8200, 10500),
        "downlink_rate_kbps": (0, 150),
        "mode": ["recovery", "emergency"],
    },
}



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate dummy telemetry and command history JSON for satellite health modeling."
    )
    parser.add_argument(
        "--telemetry-output",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "raw" / "telemetry" / "HealthTelemetry1.json",
        help="Path to write the generated telemetry JSON file.",
    )
    parser.add_argument(
        "--command-history-output",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "raw" / "command_history" / "CommandHistory1.json",
        help="Path to write the generated command history JSON file.",
    )
    parser.add_argument(
        "--labels-output",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "raw" / "telemetry" / "HealthLabels1.json",
        help="Path to write training labels kept outside canonical telemetry.",
    )
    parser.add_argument(
        "--records-per-satellite",
        type=int,
        default=25,
        help="Number of telemetry records to generate per satellite.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2026-01-01T00:00:00Z",
        help="Start timestamp for generated records in ISO 8601 UTC.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-07-21T23:59:59Z",
        help="End timestamp for generated records in ISO 8601 UTC.",
    )

    args = parser.parse_args()

    if args.records_per_satellite < 4:
        parser.error(
            "--records-per-satellite must be at least 4."
        )

    return args



def isoformat_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )



def sample_command_status(health_status: str) -> str:
    choices = list(COMMAND_STATUS_WEIGHTS[health_status].keys())
    weights = list(COMMAND_STATUS_WEIGHTS[health_status].values())
    return random.choices(choices, weights=weights, k=1)[0]



def sample_feature_value(feature_name: str, health_status: str) -> Any:
    value = FEATURE_RANGES[health_status][feature_name]
    if isinstance(value, tuple):
        if feature_name in {"reaction_wheel_rpm", "downlink_rate_kbps"}:
            return int(random.uniform(*value))
        return round(random.uniform(*value), 2)

    if isinstance(value, list):
        return random.choice(value)

    raise ValueError(f"Unsupported feature type for {feature_name}: {type(value)}")



def generate_telemetry_record(
    satellite_id: str,
    timestamp: datetime,
    health_status: str,
) -> dict[str, Any]:

    battery_voltage = sample_feature_value("battery_voltage", health_status)
    battery_current = sample_feature_value("battery_current", health_status)
    solar_current = sample_feature_value("solar_panel_current", health_status)
    eclipse_state = "sunlight"
    if health_status == "Healthy" and random.random() < 0.2:
        eclipse_state = "eclipse"
        solar_current = round(random.uniform(0.0, 0.3), 2)
    computer_temperature = sample_feature_value("bus_temperature_c", health_status)
    wheel_speed = sample_feature_value("reaction_wheel_rpm", health_status)
    return {
        "schema_version": "0.1.0",
        "satellite_id": satellite_id,
        "timestamp": isoformat_utc(timestamp),
        "source": "synthetic_health_generator",
        "spacecraft_mode": sample_feature_value("mode", health_status),
        "operational_context": {
            "eclipse_state": eclipse_state,
            "solar_array_configuration": "deployed",
            "battery_current_sign_convention": "positive_discharge",
        },
        "telemetry": {
            "battery_voltage_v": battery_voltage,
            "battery_current_a": round(random.choice((-1, 1)) * battery_current, 2),
            "battery_state_of_charge_pct": sample_feature_value(
                "battery_state_of_charge_pct", health_status
            ),
            "solar_array_voltage_v": round(battery_voltage + random.uniform(1, 5), 2),
            "solar_array_current_a": solar_current,
            "flight_computer_temperature_c": computer_temperature,
            "payload_temperature_c": sample_feature_value("payload_temperature_c", health_status),
            "gyro_x_rate_deg_s": round(random.uniform(-2, 2), 3),
            "gyro_y_rate_deg_s": round(random.uniform(-2, 2), 3),
            "gyro_z_rate_deg_s": round(random.uniform(-2, 2), 3),
            "magnetometer_x_ut": round(random.uniform(-45, 45), 2),
            "magnetometer_y_ut": round(random.uniform(-45, 45), 2),
            "magnetometer_z_ut": round(random.uniform(-45, 45), 2),
            "reaction_wheel_1_speed_rpm": wheel_speed,
            "reaction_wheel_2_speed_rpm": -round(wheel_speed * random.uniform(0.7, 1.0)),
            "reaction_wheel_3_speed_rpm": round(wheel_speed * random.uniform(0.5, 0.9)),
            "downlink_rate_kbps": sample_feature_value("downlink_rate_kbps", health_status),
            "memory_usage_pct": round(random.uniform(20, 85), 2),
            "command_queue_depth": random.randint(0, 12),
        },
    }



def generate_command_record(
    satellite_id: str,
    command_timestamp: datetime,
    health_status: str,
) -> dict[str, Any]:
    return {
        "satellite_id": satellite_id,
        "timestamp": isoformat_utc(command_timestamp),
        "command_name": random.choice(COMMANDS_BY_HEALTH[health_status]),
        "command_status": sample_command_status(health_status),
    }



def parse_iso_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)



def generate_dummy_data(
    records_per_satellite: int,
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    start_dt = parse_iso_datetime(start_date)
    end_dt = parse_iso_datetime(end_date)

    if start_dt >= end_dt:
        raise ValueError("start-date must be earlier than end-date")

    telemetry_records: list[dict[str, Any]] = []
    command_records: list[dict[str, Any]] = []
    label_records: list[dict[str, Any]] = []

    for satellite_id in SATELLITE_IDS:
        current_time = start_dt

        health_schedule = (
            HEALTH_CLASSES
            * math.ceil(records_per_satellite / len(HEALTH_CLASSES))
        )[:records_per_satellite]

        random.shuffle(health_schedule)

        for health_status in health_schedule:

            record_time = current_time + timedelta(
                seconds=random.randint(3600, 86400),
            )
            if record_time > end_dt:
                record_time = end_dt

            telemetry_record = generate_telemetry_record(
                    satellite_id=satellite_id,
                    timestamp=record_time,
                    health_status=health_status,
                )
            telemetry_records.append(telemetry_record)
            label_records.append({
                "satellite_id": satellite_id,
                "timestamp": telemetry_record["timestamp"],
                "health_status": health_status,
                "fault_scenario": POWER_SCENARIO_BY_HEALTH[health_status],
            })

            command_time = record_time - timedelta(
                minutes=random.randint(5, 120)
            )
            if command_time < start_dt:
                command_time = start_dt

            command_records.append(
                generate_command_record(
                    satellite_id=satellite_id,
                    command_timestamp=command_time,
                    health_status=health_status,
                )
            )

            current_time = record_time

    telemetry_records.sort(key=lambda record: (record["satellite_id"], record["timestamp"]))
    command_records.sort(key=lambda record: (record["satellite_id"], record["timestamp"]))

    label_records.sort(key=lambda record: (record["satellite_id"], record["timestamp"]))
    return telemetry_records, command_records, label_records



def write_json_file(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(records, file, indent=2)



def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    telemetry_records, command_records, label_records = generate_dummy_data(
        records_per_satellite=args.records_per_satellite,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    write_json_file(args.telemetry_output, telemetry_records)
    write_json_file(args.command_history_output, command_records)
    write_json_file(args.labels_output, label_records)

    print("\nDummy Data Generation Complete")
    print("------------------------------")
    print(f"Telemetry Records: {len(telemetry_records)}")
    print(f"Command Records:   {len(command_records)}")
    print(f"Label Records:     {len(label_records)}")

    print("\nHealth Status Counts")

    counts = {}

    for record in label_records:
        status = record["health_status"]
        counts[status] = counts.get(status, 0) + 1

    for status in HEALTH_CLASSES:
        print(f"{status:<10} {counts.get(status,0)}")



if __name__ == "__main__":
    main()
