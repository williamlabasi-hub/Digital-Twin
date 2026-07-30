# Collision-risk prototype contracts

These Version 0.1 contracts define the interface for a future conjunction and
collision-risk component:

- [`conjunction-assessment-input.schema.json`](../../../src/collision_risk/schemas/conjunction-assessment-input.schema.json)
  describes two object states,
  their provenance, an analysis window, hard-body radii, and optional full
  6x6 Cartesian state covariance.
- [`collision-risk-assessment.schema.json`](../../../src/collision_risk/schemas/collision-risk-assessment.schema.json)
  describes closest-approach geometry,
  collision probability when supported, uncertainty assurance, data quality,
  and explicit abstention.

The state-vector order for covariance is `[x, y, z, vx, vy, vz]`, with
position in kilometres and velocity in kilometres per second. A full matrix is
used so position/velocity cross-correlation is not silently discarded.

The contracts distinguish three assessment states:

- `complete`: closest-approach geometry and collision probability are present.
- `geometric_only`: geometry is present, but probability is unavailable.
- `abstained`: even closest-approach geometry was not accepted.

Risk thresholds and probability methods remain prototype assumptions until
they are independently calibrated and validated. These records are
decision-support evidence only and do not recommend or authorize a maneuver.

The first geometry implementation uses constant linear relative motion. It
requires a common state epoch and coordinate frame, accepts windows no longer
than 15 minutes, and requires any supplied covariance to already use the
state-vector frame. This short limit is an explicit prototype guardrail;
longer screening windows require proper orbital propagation.

When both objects provide positive-definite covariance and hard-body radius,
the prototype propagates each Cartesian covariance to closest approach with a
constant-velocity state transition. It assumes independent object errors,
combines the position covariance, projects it into the plane normal to relative
velocity, and numerically integrates a bivariate Gaussian over the combined
hard-body-radius circle. Probability is withheld when those assumptions cannot
be supported. It is also withheld when unconstrained closest approach lies
outside the requested window; projecting a clamped boundary state would discard
along-track separation and could overstate risk.

Probability method Version `prototype-0.2` diagonalizes the encounter
covariance and uses an adaptive integral in standardized Gaussian coordinates.
This remains stable when covariance is extremely small relative to hard-body
radius.

Prototype risk bands are inclusive at their lower bounds:

| Level | Collision probability |
| --- | ---: |
| Critical | `>= 1e-2` |
| High | `>= 1e-3` |
| Moderate | `>= 1e-4` |
| Low | `>= 1e-6` |
| Negligible | `< 1e-6` |

These Version `prototype-0.1` bands are transparent software assumptions, not
validated operational maneuver thresholds.

## Running the prototype

From the repository root:

```cmd
set PYTHONPATH=src
python -m collision_risk.cli ^
  --input tests/fixtures/collision_risk/conjunction-assessment-input.example.json ^
  --output outputs/collision-risk/assessment.json
```

Installed packages expose the equivalent `collision-risk-assess` command.
Semantic input limitations produce schema-valid abstained assessments, while
malformed inputs or file errors return a nonzero process exit code.
