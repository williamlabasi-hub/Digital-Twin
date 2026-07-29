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
