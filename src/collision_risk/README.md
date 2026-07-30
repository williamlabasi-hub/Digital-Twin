# Collision-risk prototype

This package validates conjunction inputs, computes bounded linear
closest-approach geometry, and calculates prototype 2D encounter-plane
collision probability when compatible covariance and hard-body radii are
available. It emits schema-valid evidence and explicitly withholds unsupported
claims.

From a source checkout:

```cmd
set PYTHONPATH=src
python -m collision_risk.cli --input tests/fixtures/collision_risk/conjunction-assessment-input.example.json --output outputs/collision-risk/assessment.json
```

After installing the package:

```cmd
collision-risk-assess --input conjunction.json --output assessment.json
```

Use `--generated-at 2026-07-29T20:01:00Z` for reproducible output. The
component is a non-operational prototype and does not recommend or authorize
maneuvers.
