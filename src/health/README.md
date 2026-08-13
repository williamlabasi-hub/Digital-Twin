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

## Complete subsystem health

`subsystem_health.py` adds explainable assessments for:

- Thermal: flight-computer and radiator temperature levels and rates.
- Payload: payload temperature level and rate.
- ADCS: body-rate magnitude and individual reaction-wheel speeds.
- Communications: downlink performance interpreted with pass state.
- C&DH: memory utilization and corrected-error counter growth.
- Propulsion: propellant estimate and thruster-state consistency.
- Timing: clock drift and synchronization offset.
- Command and control: command-queue depth and recent command failures.

Every subsystem returns status, confidence, fault codes, evidence, trends,
context notes, and limitations. Overall health uses maximum severity across the
ML classifier and all subsystem results. This is intentionally conservative
and preserves each contributor for operator review.

Missing subsystem telemetry produces `Unknown`, never `Healthy`. Warning and
degraded alerts require two consecutive samples for confirmation and two
healthy samples to clear; critical alerts confirm immediately. Reports include
alert duration and lifecycle state.

Cross-subsystem fault isolation emits candidate hypotheses with supporting
subsystems rather than claiming a confirmed root cause. The model artifact also
contains numerical ranges and categorical values observed during training.
Inference outside that profile is marked `abstained` and excluded from overall
health aggregation, while the raw classifier output remains available for
diagnostic review.

## Run the health monitor

From the repository root, process the versioned telemetry and command-history
fixtures with the saved model:

```cmd
python src\health\health_monitor.py ^
  --output outputs\health\health-predictions.json ^
  --history outputs\health\health-history.json
```

The source-checkout command does not require installation or a `PYTHONPATH`
change. It validates the generated report against the packaged health schema.

Run the synthetic fault-injection validation harness with:

```cmd
python scripts\validate_health_scenarios.py
```

Hardware-in-the-loop work remains pending as documented in
`docs/requirements/health/VALIDATION_PLAN.md`.

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
