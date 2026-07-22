# Health subsystem

The health subsystem validates Version 0.1 housekeeping telemetry, combines it
with the latest preceding command for the same satellite, and generates a
four-class health report.

## Canonical telemetry model

The saved model is trained directly on canonical housekeeping field names.
`health_monitor.prepare_dataset` validates envelope records, flattens selected
canonical fields without changing their meaning, and performs timestamp-aware
command-history alignment. Legacy flat telemetry is rejected.

The model consumes signed `battery_current_a` and all three signed
reaction-wheel speed channels directly. Synthetic health labels are stored in
`data/raw/telemetry/HealthLabels1.json`, separate from schema-valid telemetry,
and are joined only during training.

## Explainable power health

`power_health.py` independently evaluates battery voltage, signed current,
solar-array current, and time-based rates. It returns subsystem status, stable
fault codes, observed evidence, prototype thresholds, confidence, context
limitations, and trend values. The report conservatively combines this result
with the ML classifier using maximum severity while preserving both inputs.

All power thresholds are prototype assumptions. Low solar current is not
isolated as a hardware fault without eclipse state and array configuration.
Synthetic label sidecars include a `fault_scenario` for repeatable nominal,
warning, degraded, and critical power tests.

Run the health data generation and training workflow from the repository root:

```cmd
python scripts\generate_dummy_satellite_data.py
python src\health\train_health_model.py
```

Run verification with:

```cmd
python tests\common\test_telemetry_validation.py -v
python tests\health\test_telemetry_adapter.py -v
python tests\health\test_health_monitor.py -v
```
