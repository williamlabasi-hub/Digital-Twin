# COA evidence integration contract

The canonical Version 0.1 COA evidence schema is packaged at
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

Collision-risk evidence and its adapter remain future work. They will be added
as an explicit contract revision rather than accepted as an unvalidated,
unstructured payload.
