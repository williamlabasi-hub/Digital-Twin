# Operator dashboard handoff contract

Status: **Version 1.0.0 frozen for prototype development**

The operator dashboard has one stable discovery path:

1. Read `outputs/golden-path/latest.json`.
2. Require `dashboard_contract_version` `1.0.0`.
3. Read the referenced `summary` artifact.
4. Require the same dashboard contract version in the summary.
5. Follow paths under `artifacts` only when detailed subsystem evidence is
   needed.

The packaged JSON Schemas are:

- `src/common/dashboard_contracts/latest-run.schema.json`
- `src/common/dashboard_contracts/golden-path-summary.schema.json`

## Version 1 guarantees

Consumers may depend on:

- stable field names and value types defined by the schemas;
- explicit null identity when no canonical secondary identity is available;
- one usability state for each required evidence type;
- enumerated health, identity, collision, and COA states;
- ordered candidate COA and advisory code arrays;
- absolute paths to the complete run artifacts; and
- `latest.json` referring only to a completely published run.

The dashboard must not derive command authority from any status or COA code.
Detailed rationale, constraints, probability evidence, timestamps, and
provenance remain authoritative in the referenced subsystem and COA artifacts.

## Change rules

- Adding, removing, renaming, or changing the meaning or type of a required
  field is a breaking change and requires a new major contract version.
- Adding an enum value requires consumer review and at least a minor version
  update.
- Fixes that do not change the accepted JSON shape may use a patch version.
- The runner, schemas, tests, documentation, and dashboard must be updated in
  the same change whenever the contract version changes.
- Dashboard code must reject unsupported contract versions with a visible
  compatibility error rather than silently guessing.

## Validation

The golden-path runner validates both artifacts before publication with
`common.dashboard_contracts.validate_dashboard_contract`. Contract tests also
check that packaged schemas are valid and that missing required fields or
unsupported versions are rejected.
