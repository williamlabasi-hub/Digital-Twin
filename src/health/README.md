
# Health subsystem

The health subsystem combines validated housekeeping telemetry with the latest
preceding command for the same satellite, prepares the legacy Random Forest
features, and generates a health report.

## Version 0.1 telemetry adapter

`telemetry_adapter.py` connects the repository's housekeeping telemetry
contract to the initial model feature contract. `health_monitor.prepare_dataset`
automatically detects Version 0.1 envelope records, validates them, adapts them,
and then performs timestamp-aware command-history alignment. Legacy flat
telemetry remains supported during migration; a single file may not mix the two
record formats.

The adapter currently makes three explicit prototype assumptions:

1. `flight_computer_temperature_c` maps to legacy `bus_temperature_c`.
2. Maximum absolute speed across wheels 1–3 maps to legacy
   `reaction_wheel_rpm`.
3. Absolute battery current maps to the unsigned value used during legacy
   training.

These assumptions are returned with every `AdaptedTelemetry` result and should
be removed when the health model is retrained directly against the approved
housekeeping telemetry contract.

Command-history features are never fabricated by the adapter. They are added
by the existing backward timestamp join after validation and adaptation.

Run the common and health tests from the repository root:

```cmd
python -m unittest discover -s tests/common -v
python -m unittest discover -s tests/health -v
```
