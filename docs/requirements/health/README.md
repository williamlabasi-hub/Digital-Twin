# Health report contract

[`health_predictions.schema.json`](../../../src/health/schemas/health_predictions.schema.json)
is the authoritative structural contract for the Version 1.1 output produced
by `src/health/health_monitor.py`.

Runtime reports are written under `data/outputs/health/` and are excluded from
version control. The committed dashboard fixture at
`demo/data/health_predictions.json` is validated by the health test suite.
Model probabilities are uncalibrated Random Forest vote fractions, and
recommendations are preliminary health advisories, not COAs.

