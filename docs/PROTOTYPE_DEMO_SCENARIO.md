# Prototype demonstration scenario

## Purpose

This document freezes the deterministic scenario used to build, test, and
present the operator-facing prototype. The prototype demonstrates how Health,
Object Identification, Collision Risk, and COA decision support exchange
validated evidence. It is not an operational conjunction-response system.

## Operator story

The operator is monitoring primary spacecraft `SAT-001`. A simulated tracking
observation is associated with catalog object `CAT-25544`. The primary
spacecraft is assessed as Healthy, and the fixture collision assessment reports
moderate prototype risk.

Although the subsystem results are available, the evidence is not sufficiently
current and synchronized for action authorization. The COA engine therefore
returns a limited report that asks the operator to improve the evidence, refine
tracking, and begin a planning-only maneuver review. No command or maneuver is
authorized.

## Frozen fixture inputs

- Health telemetry: `data/raw/telemetry/HealthTelemetry1.json`
- Command history: `data/raw/command_history/CommandHistory1.json`
- Health model: `data/processed/health/models/satellite_health_model.joblib`
- Orbital observation and candidates:
  `tests/fixtures/object_identification/data_gen/`
- Conjunction input:
  `tests/fixtures/collision_risk/conjunction-assessment-input.example.json`
- Scenario time: `2026-07-29T20:01:00Z`

These inputs are versioned synthetic fixtures. Changing any frozen input or the
scenario time requires reviewing and updating the expected results below.

## Expected operator-visible results

| Display area | Expected result |
| --- | --- |
| Primary spacecraft | `SAT-001` |
| Primary health | `Healthy` |
| Identified secondary | `CAT-25544` |
| Identification decision | `clear_match` / known identity |
| Secondary affiliation | `other` |
| Collision assessment | complete |
| Prototype collision risk | moderate |
| COA status | limited |
| Evidence limitation | stale health evidence and unsynchronized subsystem observations |

The prototype must display the following candidate COAs in order:

1. `COA_IMPROVE_DEGRADED_EVIDENCE` -- prerequisite
2. `COA_REFINE_TRACKING` -- recommended for operator review
3. `COA_MANEUVER_PLANNING_REVIEW` -- planning only

Every candidate must state that operator approval is required. The interface
must not present any candidate as an executable spacecraft command.

## Required safety messages

The operator-facing prototype must make these boundaries visible:

- Inputs, thresholds, and results are prototype and non-operational.
- Evidence timestamps do not represent one synchronized operational event.
- Refined evidence is required before selecting an executable response.
- Proximity or affiliation does not establish hostile intent.
- The system cannot authorize or execute spacecraft commands or maneuvers.

## Demonstration sequence

1. Show the primary spacecraft and Healthy subsystem result.
2. Show the observation associated with `CAT-25544` and its provenance.
3. Show the moderate fixture collision assessment and its evidence basis.
4. Explain why the COA report is limited despite the Healthy spacecraft state.
5. Review the three candidate COAs and their constraints.
6. End at operator review; do not simulate command execution as an authorized
   outcome.

## Acceptance check

From the repository root, run:

```powershell
python scripts\run_golden_path.py
python -m unittest tests.test_golden_path -v
```

Resolve `outputs/golden-path/latest.json` after the run. The referenced
`summary.json` must match the expected values in this document, and the COA
report in the same run directory must retain
`operator_advisory_only_no_command_authority` as its decision scope. A failed
or interrupted run must not replace the latest reference.

The degraded integration modes documented in `GOLDEN_PATH.md` must also finish
with valid COA and summary artifacts. Ambiguous identity, unavailable health,
and collision abstention must return `insufficient_evidence`; missing
covariance and stale evidence must return `limited`.
