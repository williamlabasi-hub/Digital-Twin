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
object. Usable or degraded object-identification evidence must match the
secondary object; withheld identification evidence may retain its observation
ID because it cannot assert a canonical identity. Its output is validated
against `src/coa/coa-report.schema.json`.

The engine produces deterministic operator advisories:

- withheld evidence blocks advisory selection;
- invalid data quality is always withheld;
- degraded evidence produces a limited report and requests better evidence;
- evidence older than 24 hours or separated by more than 15 minutes limits the
  report, while evidence dated after the report is rejected;
- usable evidence produces risk-dependent monitoring, escalation, or
  maneuver-planning-review advisories;
- warning, degraded, or critical health adds a proportional health-constraint
  review.

Version 0.2 formalizes these rules as a deterministic decision tree. Every
report includes the evaluated branch trace and structured candidate COAs. A
candidate COA contains a stable code, priority, disposition, rationale, review
actions, constraints, and an explicit operator-approval requirement. The tree
does not learn from operational decisions and cannot issue commands.

Decision order:

1. Withheld required evidence stops response selection and produces an
   evidence-resolution prerequisite.
2. Degraded evidence adds an evidence-improvement prerequisite.
3. Collision risk selects routine monitoring, increased monitoring, refined
   tracking and planning review, urgent response review, or an evidence request.
4. Warning, degraded, or critical primary-spacecraft health adds a
   health-constraint review at watch, priority, or urgent priority.

Every report also contains a compact operator summary listing the selection
basis, selected COA codes, and the required operator action.

The engine cannot command a spacecraft, authorize a maneuver, or infer hostile
intent from proximity or affiliation. All artifacts are explicitly marked
prototype, unvalidated, and non-operational.

Run the engine from Command Prompt after producing the three evidence files:

```bat
python src\coa\cli.py ^
  --health-evidence outputs\coa\health-evidence.json ^
  --object-id-evidence outputs\coa\object-id-evidence.json ^
  --collision-risk-evidence outputs\collision-risk\coa-evidence.json ^
  --output outputs\coa\coa-report.json ^
  --generated-at 2026-07-30T20:00:00Z
```

This source-checkout command does not require installation or a `PYTHONPATH`
change.
