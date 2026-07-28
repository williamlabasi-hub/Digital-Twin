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

```cmd
python -m src.object_identification.association ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --catalog tests\fixtures\object_identification\object-catalog-record.example.json ^
  --orbital tests\fixtures\object_identification\orbital-state-record.example.json ^
  --affiliation tests\fixtures\object_identification\affiliation-record.example.json ^
  --output data\processed\object_identification\prediction.json
```
