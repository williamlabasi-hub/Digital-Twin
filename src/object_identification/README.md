# Object Identification

Status: **Prototype - non-operational**

Object-identification development begins with the versioned classification and
evidence contract:

[`docs/requirements/object_identification/IDENTIFICATION_CONTRACT.md`](../../docs/requirements/object_identification/IDENTIFICATION_CONTRACT.md)

A prototype position-and-velocity association rule is implemented for contract
and pipeline integration testing. It is uncalibrated and non-operational; no
trained classifier, synthetic generator, or operational prediction interface
is implemented yet.

Version `0.1.0` JSON Schemas now define:

- tracking observations;
- authoritative object-catalog records;
- orbital state records;
- authority-controlled affiliation records;
- object-identification predictions.

Validated examples are stored under `tests/fixtures/object_identification/`.

## Prepare identification evidence

The first executable layer validates the four inputs, checks identifiers,
coordinate frames, validity windows, and temporal ordering, then writes a
normalized candidate-evidence record. It does not score or classify the
candidate.

```cmd
python -m src.object_identification.input_pipeline ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --catalog tests\fixtures\object_identification\object-catalog-record.example.json ^
  --orbital tests\fixtures\object_identification\orbital-state-record.example.json ^
  --affiliation tests\fixtures\object_identification\affiliation-record.example.json ^
  --output data\processed\object_identification\prepared-evidence.json
```

## Run prototype association

The first association method uses position and velocity residuals plus
measurement quality. Its score is an uncalibrated similarity value, not a
probability. The scales and threshold in
`config/object-identification-association.json` are prototype assumptions.

When both an observation and candidate provide position and velocity
covariance, scoring uses their combined covariance and Mahalanobis distance.
Covariance must be a symmetric, positive-definite 3x3 matrix. If either side
lacks complete covariance, the scorer explicitly falls back to the configured
position and velocity scales.

One or more candidates can be evaluated. Results are sorted by score, retain
candidate provenance, and withhold identity when multiple threshold-clearing
candidates fall within the configured ambiguity margin.

```cmd
python -m src.object_identification.association ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --catalog tests\fixtures\object_identification\object-catalog-record.example.json ^
  --orbital tests\fixtures\object_identification\orbital-state-record.example.json ^
  --affiliation tests\fixtures\object_identification\affiliation-record.example.json ^
  --output data\processed\object_identification\prediction.json
```

For catalog-wide ranking, repeat `--candidate` with each catalog, orbital, and
affiliation record triplet:

```cmd
python -m src.object_identification.association ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --candidate catalog-a.json orbit-a.json affiliation-a.json ^
  --candidate catalog-b.json orbit-b.json affiliation-b.json ^
  --output data\processed\object_identification\ranked-prediction.json
```

### Run the clear-match demonstration

```cmd
python -m src.object_identification.association ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\clear-best.catalog.json tests\fixtures\object_identification\multi_candidate\clear-best.orbital.json tests\fixtures\object_identification\multi_candidate\clear-best.affiliation.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\clear-mid.catalog.json tests\fixtures\object_identification\multi_candidate\clear-mid.orbital.json tests\fixtures\object_identification\multi_candidate\clear-mid.affiliation.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\clear-far.catalog.json tests\fixtures\object_identification\multi_candidate\clear-far.orbital.json tests\fixtures\object_identification\multi_candidate\clear-far.affiliation.json ^
  --output outputs\verification\clear-ranked-prediction.json
```

### Run the ambiguity demonstration

```cmd
python -m src.object_identification.association ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\clear-best.catalog.json tests\fixtures\object_identification\multi_candidate\clear-best.orbital.json tests\fixtures\object_identification\multi_candidate\clear-best.affiliation.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\ambiguous-near.catalog.json tests\fixtures\object_identification\multi_candidate\ambiguous-near.orbital.json tests\fixtures\object_identification\multi_candidate\ambiguous-near.affiliation.json ^
  --output outputs\verification\ambiguous-ranked-prediction.json
```
