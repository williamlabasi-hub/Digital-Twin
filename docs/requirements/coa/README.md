# COA evidence integration contract

The canonical Version 0.2 COA evidence schema is packaged at
`src/coa/coa-evidence.schema.json`. Each subsystem publishes one evidence
envelope for one subject and observation time. A future COA component may
combine envelopes from health, object identification, collision risk, mission
objectives, and command context.

This contract deliberately contains evidence only. It does not select,
authorize, or recommend an operator course of action.

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
