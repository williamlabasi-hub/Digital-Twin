# Health ML capstone demo

This browser-based dashboard presents a committed Version 1.1 health-report
fixture without changing its decisions. It reads the validated report at
`demo/data/health_predictions.json` and provides four-class scenario selection,
timeline playback, subsystem status, model assurance, evidence, command
context, telemetry, and preliminary advisories.

## Run

From the repository root:

```powershell
python demo\start_demo.py
```

Open `http://127.0.0.1:8000/demo/`. Use the four status buttons for a controlled presentation or **Run timeline** for automatic playback. The left and right arrow keys also move between records.

## Suggested 3-minute presentation flow

1. Start on **Healthy** and explain the telemetry-to-decision pipeline.
2. Select **Warning**, then point to the subsystem grid and observed evidence.
3. Select **Critical** and contrast the ML confidence with model assurance.
4. Open telemetry details to show traceability back to measurements.
5. Close on the validation boundary: 100 synthetic scenarios pass, but hardware-in-the-loop validation remains pending.

## Refresh the underlying result

```powershell
python src\health\health_monitor.py
python scripts\validate_health_scenarios.py
Copy-Item data\outputs\health\health_predictions.json demo\data\health_predictions.json
```

The copy step intentionally promotes a validated runtime result into the
versioned demo fixture. Review the generated report before committing it.

The dashboard server is dependency-free and uses only Python's standard
library.
