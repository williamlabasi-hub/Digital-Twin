# Object Identification Contract

Status: **Accepted for prototype development - non-operational**  
Contract version: **0.1.0**  
Component: **Object Identification**

Review date: **2026-07-27**  
Review outcome: **Approved as the baseline for schema and prototype software
development. Operational approval remains pending.**

## Purpose

This contract defines what the digital twin means by object identity and
affiliation. It establishes the public classification states, evidence and
provenance requirements, confidence semantics, and component boundaries before
schemas, matching logic, synthetic data, or machine-learning models are built.

This prototype must not be used for operational threat designation, targeting,
collision avoidance, or autonomous command decisions.

## Classification model

Object identification is hierarchical and contains two separate decisions:

1. **Identity status** - whether the observation can be associated with an
   authoritative catalog identity.
2. **Affiliation** - the approved affiliation of that known identity.

The public composite classification is derived from those two decisions.

| Identity status | Affiliation | Public classification | Meaning |
|---|---|---|---|
| `known` | `blue` | `known_blue` | Catalog identity is established and an approved authority labels it blue. |
| `known` | `red` | `known_red` | Catalog identity is established and an approved authority labels it red. |
| `known` | `other` | `known_other` | Catalog identity is established but is neither approved blue nor approved red. |
| `unknown` | `unknown` | `unknown` | Available evidence does not establish an authoritative identity. |

No other combination is valid.

## Required invariants

1. An `unknown` identity must have `unknown` affiliation.
2. A `known` identity must have `blue`, `red`, or `other` affiliation.
3. Low confidence, missing data, unusual behavior, proximity, maneuvering, or
   collision risk must not automatically produce `known_red`.
4. `known_other` includes cataloged commercial, civil, allied, neutral, and
   otherwise unassigned objects unless an approved authority maps them to blue
   or red.
5. Model confidence is not identity status and is not affiliation.
6. Affiliation must come from an approved source; it must not be inferred from
   mission priority, protected-object status, radar cross section, orbit, or
   command history alone.
7. Every known classification must retain the catalog match and affiliation
   provenance used to produce it.
8. Conflicting authoritative sources must produce an unresolved result for
   operator review; the system must not silently select the most severe label.

## Evidence required for a known identity

An object may be marked `known` only when all of the following are present:

- a stable canonical object identifier;
- an authoritative catalog source and catalog record identifier;
- a time-valid catalog record;
- observation-to-catalog association evidence;
- a match score or equivalent quality measure;
- the matching method and its version;
- no unresolved identity conflict.

The operational match threshold is **TBD** and must be evaluated using
representative validation data. A prototype threshold must be explicitly
marked as an unvalidated assumption.

If the evidence is insufficient, stale beyond an approved limit, internally
inconsistent, or below the approved match threshold, identity status is
`unknown`.

When multiple catalog candidates are evaluated, they must be ranked using the
same versioned method and threshold. Identity must also remain `unknown` when
two or more threshold-clearing candidates fall within the configured ambiguity
margin. Ranked alternatives retain their catalog provenance so an operator can
review the decision without treating an ambiguous top score as a known match.

## Affiliation authority

Affiliation is catalog or policy metadata applied only after identity is
established.

Each affiliation decision requires:

- `affiliation`;
- `affiliation_authority`;
- `affiliation_source_record_id`;
- `affiliation_effective_at`;
- optional `affiliation_expires_at`;
- optional review notes.

The approved affiliation authorities, precedence rules, expiration rules, and
conflict-resolution process are **TBD**.

## Confidence semantics

The component reports separate measures:

- **Match confidence** - strength of the observation-to-catalog association.
- **Affiliation confidence** - confidence that the selected affiliation record
  is current and applicable.
- **Data quality** - completeness, validity, freshness, and consistency of the
  input evidence.

No value may be presented as a calibrated probability unless calibration has
been measured on independent representative data. Random Forest vote fractions
or similarity scores must be labeled by their actual interpretation.

## Minimum prediction record

Every prediction record must contain:

- contract/schema version;
- record generation timestamp;
- observation identifier and timestamp;
- canonical object identifier, or `null` when unknown;
- `identity_status`;
- `affiliation`;
- derived public `classification`;
- match score and score interpretation;
- threshold and threshold version;
- catalog and affiliation provenance;
- matching method and version;
- candidate-selection basis and ranked alternatives when catalog-wide matching
  is performed;
- data-quality status and issues;
- human-readable rationale;
- model or rule artifact metadata;
- explicit prototype/operational-use designation.

## Component boundaries

Object identification answers:

- Is this observation associated with a known catalog object?
- If known, what approved affiliation is associated with that identity?

Object identification does **not** independently answer:

- Is the object hostile or threatening?
- Will the object collide with another object?
- What course of action should an operator take?
- Should a maneuver or command be executed?

Those decisions belong to threat/risk assessment, collision assessment,
operator recommendations, and command-and-control components. They may consume
object-identification output while preserving its confidence and provenance.

## Initial evidence sources

The prototype may integrate:

- radar or optical tracking observations;
- TLE or other orbital-element records;
- propagated state vectors;
- authoritative object catalogs;
- sensor and observation metadata;
- approved affiliation catalogs;
- optional tracking-command context.

"Red telemetry" is not assumed to be directly available from external objects.
External objects are identified from observations and authoritative reference
data.

## Decisions required before model development

1. Name the authoritative identity catalog or catalogs.
2. Name the authoritative affiliation source or sources.
3. Define blue, red, and other for the intended mission and authority.
4. Define catalog precedence and conflict resolution.
5. Define observation-to-catalog matching tolerances and freshness limits.
6. Define prototype and operational confidence terminology.
7. Define the review path for unknown and conflicting records.
8. Approve the output schema and downstream consumers.
