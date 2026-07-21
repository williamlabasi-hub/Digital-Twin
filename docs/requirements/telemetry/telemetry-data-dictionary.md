# Housekeeping Telemetry Data Dictionary

Status: **Prototype — unvalidated**  
Dictionary version: **0.1.0**  
Authoritative machine-readable source: [`config/housekeeping-telemetry.yaml`](../config/housekeeping-telemetry.yaml)

## Purpose and restrictions

This document defines a preliminary housekeeping telemetry interface for the
SDA satellite digital-twin prototype. It supports interface design, synthetic
data generation, validation, and early machine-learning development.

No range in this document is approved for flight-safety decisions, autonomous
safe-mode entry, or certified operational monitoring. Values marked `TBD` must
be populated from spacecraft, subsystem, component, simulator, or flight
software specifications and reviewed by an authorized engineer.

## Range terminology

- **Physical range:** broad plausibility or sensor-envelope check. A violation
  generally indicates invalid data, a unit error, corruption, or a failed sensor.
- **Operational limits:** spacecraft-specific nominal, warning, and critical
  thresholds. These are intentionally `TBD` in this draft.
- **Stale after:** maximum age proposed before the measurement is reported as
  degraded data quality. These values are also prototype assumptions.
- **Context required:** additional state needed before a measurement can be
  interpreted, such as eclipse state or communications-pass state.

## Record envelope

Each observation uses a common envelope containing `schema_version`,
`satellite_id`, UTC `timestamp`, `source`, optional `sequence_number`,
`spacecraft_mode`, and a `telemetry` object. The structural contract is in
[`schemas/housekeeping-telemetry.schema.json`](../schemas/housekeeping-telemetry.schema.json).

## Parameter summary

| Parameter | Subsystem | Unit | Physical range | Kind | Operational limits | Authority |
|---|---|---:|---:|---|---|---|
| `battery_voltage_v` | Power | V | 0–50 | Direct | TBD | Prototype assumption |
| `battery_current_a` | Power | A | −20–20 | Direct, signed | TBD | Prototype assumption |
| `battery_state_of_charge_pct` | Power | % | 0–100 | Estimated | TBD | Engineering definition pending |
| `solar_array_voltage_v` | Power | V | 0–100 | Direct | TBD | Prototype assumption |
| `solar_array_current_a` | Power | A | 0–20 | Direct | TBD | Prototype assumption |
| `rail_3v3_voltage_v` | Power | V | 0–5 | Direct | TBD | Subsystem specification pending |
| `rail_5v_voltage_v` | Power | V | 0–7 | Direct | TBD | Subsystem specification pending |
| `rail_12v_voltage_v` | Power | V | 0–16 | Direct | TBD | Subsystem specification pending |
| `flight_computer_temperature_c` | Thermal | °C | −100–150 | Direct | TBD | Component specification pending |
| `payload_temperature_c` | Payload | °C | −100–150 | Direct | TBD | Payload specification pending |
| `radiator_temperature_c` | Thermal | °C | −150–150 | Direct | TBD | Thermal model pending |
| `gyro_x_rate_deg_s` | ADCS | °/s | −100–100 | Direct, signed | TBD | Gyro datasheet pending |
| `gyro_y_rate_deg_s` | ADCS | °/s | −100–100 | Direct, signed | TBD | Gyro datasheet pending |
| `gyro_z_rate_deg_s` | ADCS | °/s | −100–100 | Direct, signed | TBD | Gyro datasheet pending |
| `gyro_bias_x_deg_hr` | ADCS | °/hr | −100–100 | Estimated | TBD | ADCS algorithm definition pending |
| `magnetometer_x_ut` | ADCS | μT | −100–100 | Direct component | TBD | NOAA reference + sensor datasheet pending |
| `magnetometer_y_ut` | ADCS | μT | −100–100 | Direct component | TBD | NOAA reference + sensor datasheet pending |
| `magnetometer_z_ut` | ADCS | μT | −100–100 | Direct component | TBD | NOAA reference + sensor datasheet pending |
| `magnetic_field_magnitude_ut` | ADCS | μT | 0–100 | Derived magnitude | TBD | NOAA reference only |
| `sun_sensor_azimuth_deg` | ADCS | ° | [0, 360) | Direct angle | TBD | Sun-sensor datasheet pending |
| `reaction_wheel_1_speed_rpm` | ADCS | rpm | TBD | Direct, signed | TBD | Wheel datasheet pending |
| `reaction_wheel_2_speed_rpm` | ADCS | rpm | TBD | Direct, signed | TBD | Wheel datasheet pending |
| `reaction_wheel_3_speed_rpm` | ADCS | rpm | TBD | Direct, signed | TBD | Wheel datasheet pending |
| `thruster_firing` | Propulsion | boolean | false/true | State | N/A | Propulsion interface pending |
| `thruster_pulse_width_ms` | Propulsion | ms | ≥0; maximum TBD | Direct or commanded | TBD | Propulsion interface pending |
| `memory_usage_pct` | C&DH | % | 0–100 | Derived | TBD | Flight-software interface pending |
| `memory_corrected_error_count` | C&DH | count | ≥0 | Counter | TBD | Flight-software interface pending |
| `onboard_data_generation_rate_kbps` | C&DH | kbps | ≥0; maximum TBD | Derived | TBD | Mission data budget pending |
| `downlink_rate_kbps` | Communications | kbps | ≥0; maximum TBD | Derived | TBD | Link budget pending |
| `propellant_remaining_pct` | Propulsion | % | 0–100 | Estimated | TBD | Propulsion estimator pending |
| `propellant_tank_pressure_bar` | Propulsion | bar | ≥0; maximum TBD | Direct | TBD | Propulsion specification pending |
| `clock_drift_us_day` | Timing | μs/day | TBD | Estimated | TBD | Timing requirements pending |
| `time_sync_offset_ms` | Timing | ms | TBD | Derived, signed | TBD | Timing requirements pending |
| `command_queue_depth` | Command & Control | count | ≥0; maximum TBD | Direct | TBD | Flight-software configuration pending |
| `latest_command_status` | Command & Control | enum | Defined state list | State | Rule-based | Command interface pending |

## Required engineering decisions

1. Confirm the spacecraft power-bus architecture and each monitored supply rail.
2. Define battery-current sign convention.
3. Identify every temperature sensor by component and physical location.
4. Confirm gyro measurement range, bias-estimator units, and coordinate frame.
5. Confirm magnetometer frame, sensor range, calibration state, and expected
   environmental model.
6. Select reaction-wheel hardware and populate signed speed and saturation limits.
7. Separate commanded thruster state from measured valve or firing confirmation.
8. Define memory capacity, reset behavior, and error-counter semantics.
9. Separate onboard generation, storage-write, and downlink data rates.
10. Define propellant estimation method and pressure sensor locations.
11. Define the authoritative spacecraft clock and synchronization requirement.
12. Confirm command lifecycle states and maximum queue depth.

## Sources for this preliminary draft

- [NOAA Geomagnetism FAQ](https://www.ncei.noaa.gov/products/geomagnetism-frequently-asked-questions)
- [NASA Small Spacecraft GNC overview](https://www.nasa.gov/smallsat-institute/sst-soa/guidance-navigation-and-control/)
- [NASA Space Flight System Design and Environmental Test](https://www.nasa.gov/sites/default/files/atoms/files/std8070.1.pdf)

These references provide general context only. Component- and mission-specific
documents must control the final interface and health thresholds.

