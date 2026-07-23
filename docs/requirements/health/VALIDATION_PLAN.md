# Health-system validation plan

## Completed level

The repository provides deterministic synthetic fault injection, automated unit
and integration tests, output-schema validation, model checksum verification,
training-domain applicability checks, and an executable scenario harness:

```cmd
python scripts\validate_health_scenarios.py
```

These checks demonstrate software behavior only.

## Simulator validation

Replace synthetic files with timestamped telemetry from a mission-approved
software simulator. Inject single faults, interacting faults, sensor dropouts,
delays, stale packets, mode transitions, eclipse transitions, and recovery
sequences. Maintain an independent truth file and evaluate detection delay,
false-alert rate, missed detections, fault-isolation accuracy, abstention rate,
and recovery clearing time.

## Hardware-in-the-loop validation

Hardware-in-the-loop is not complete. Required future work includes connecting
the same telemetry contract to representative avionics, power, ADCS, radio,
thermal, timing, and propulsion interfaces; recording authoritative fault truth;
repeating the scenario matrix under nominal and boundary conditions; measuring
latency and resource consumption; and obtaining engineering approval for every
operational threshold.

No repository result may be represented as flight qualification or safety
certification until those activities and independent reviews are complete.
