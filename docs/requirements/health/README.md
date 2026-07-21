# Health report contract

`health_predictions.schema.json` is the authoritative structural contract for
the Version 1.1 output produced by `src/health/health_monitor.py`.

The example at `data/outputs/health/health_predictions.json` is validated by
the health test suite. Model probabilities are uncalibrated Random Forest vote
fractions, and recommendations are preliminary health advisories—not COAs.

