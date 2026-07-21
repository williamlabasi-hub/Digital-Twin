# Satellite health Random Forest model card

## Model

- Artifact: `satellite_health_model.joblib`
- Task: four-class satellite health classification
- Classes: `Healthy`, `Warning`, `Degraded`, `Critical`
- Algorithm: scikit-learn `RandomForestClassifier`
- Trees: 200
- Random state: 42
- Class weighting: balanced
- Python: 3.14.6
- pandas: 3.0.3
- scikit-learn: 1.9.0
- joblib: 1.5.3
- NumPy: 2.4.6

## Features

The model consumes solar current, bus and payload temperatures, reaction-wheel
speed, downlink rate, battery voltage/current, seconds since command, spacecraft
mode, and recent command name/status. The preprocessing pipeline and classifier
are saved together, and the exact feature list is embedded in the artifact.

## Training data

This prototype is trained on 100 synthetic records from:

- `data/raw/telemetry/HealthTelemetry1.json`
- `data/raw/command_history/CommandHistory1.json`

The generator deliberately creates separable classes and correlates command
behavior with the target. Metrics demonstrate software execution only; they do
not estimate operational performance.

## Intended use

- Digital-twin interface development
- Synthetic scenario testing
- Health-report pipeline demonstration
- Downstream COA interface development

## Restrictions

This model is not flight-qualified, safety-certified, probability-calibrated,
or validated on real telemetry. Do not use it for autonomous commanding or
safe-mode entry.

## Adapter assumptions

- Flight-computer temperature maps to legacy bus temperature.
- Maximum absolute wheel speed maps to the legacy wheel-speed feature.
- Absolute battery current maps to the unsigned legacy current feature.

## Reproduction

From the repository root:

```cmd
python src/health/train_health_model.py
python -m unittest discover -s tests/health -v
```

## Artifact security

Joblib uses pickle-based serialization and may execute code while loading. Load
this artifact only from the trusted repository and verify its SHA-256 checksum.
