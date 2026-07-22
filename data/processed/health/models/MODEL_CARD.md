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

The model consumes canonical battery state of charge, solar-array voltage and
current, flight-computer and payload temperatures, all three signed
reaction-wheel speeds, downlink rate, signed battery current, battery voltage,
seconds since command, spacecraft mode, eclipse state, array configuration,
battery-current sign convention, and recent command context. The exact feature
list is embedded in the artifact.

The artifact also embeds observed numerical ranges and categorical values from
training. Inference outside this profile is marked as an abstention and is not
used as an overall-health contributor. This is a simple applicability check,
not a complete statistical out-of-distribution detector.

## Training data

This prototype is trained on 100 synthetic records from:

- `data/raw/telemetry/HealthTelemetry1.json` (schema-valid envelopes)
- `data/raw/telemetry/HealthLabels1.json` (training-only label sidecar)
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

## Contract

The model uses canonical Version 0.1 telemetry names directly and does not
require legacy field mapping. Labels remain outside the telemetry contract.

## Reproduction

From the repository root:

```cmd
python src/health/train_health_model.py
python -m unittest discover -s tests/health -v
```

## Artifact security

Joblib uses pickle-based serialization and may execute code while loading. Load
this artifact only from the trusted repository and verify its SHA-256 checksum.
