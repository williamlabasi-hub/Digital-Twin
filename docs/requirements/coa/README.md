# COA evidence and decision-support contracts

The canonical Version 0.2 COA evidence schema is packaged at
`src/coa/coa-evidence.schema.json`. Each subsystem publishes one evidence
envelope for one subject and observation time.

Implemented adapters:

- `coa.adapt_health_report`
- `coa.adapt_health_predictions`
- `coa.adapt_object_identification`
- `coa.adapt_collision_risk`

Collision-risk adaptation preserves complete, geometry-only, and abstained
states. Complete assessments are usable prototype evidence, geometry-only
assessments are degraded evidence, and abstained assessments are withheld.
Collision probability is carried in the payload and is never represented as
decision-support confidence.

## Prototype decision support

`coa.build_coa_report` combines exactly one health, object-identification, and
collision-risk envelope. The health subject must match the collision primary
object, and the object-identification subject must match the secondary object.
Its output is validated against `src/coa/coa-report.schema.json`.

The engine produces deterministic operator advisories:

- withheld evidence blocks advisory selection;
- degraded evidence produces a limited report and requests better evidence;
- usable evidence produces risk-dependent monitoring, escalation, or
  maneuver-planning-review advisories;
- degraded or critical health adds a health-constraint review.

The engine cannot command a spacecraft, authorize a maneuver, or infer hostile
intent from proximity or affiliation. All artifacts are explicitly marked
prototype, unvalidated, and non-operational.

Run the engine from Command Prompt after producing the three evidence files:

```bat
set PYTHONPATH=src
python -m coa.cli ^
  --health-evidence outputs\coa\health-evidence.json ^
  --object-id-evidence outputs\coa\object-id-evidence.json ^
  --collision-risk-evidence outputs\collision-risk\coa-evidence.json ^
  --output outputs\coa\coa-report.json ^
  --generated-at 2026-07-30T20:00:00Z
```
