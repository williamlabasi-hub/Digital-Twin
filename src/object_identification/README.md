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

## Evaluate prototype thresholds

The deterministic synthetic evaluation generates balanced known, unknown, and
ambiguous scenarios, sweeps match thresholds and ambiguity margins, and writes
JSON and CSV reports:

```cmd
python -m src.object_identification.evaluation ^
  --cases 60 ^
  --seed 20260728 ^
  --output-directory outputs\object_identification\evaluation
```

The report includes precision, recall, false-match rate, missed-match rate,
unknown accuracy, and ambiguity accuracy. Recommendation logic first checks a
1% maximum false-match-rate and 80% minimum-recall target. If no evaluated
configuration meets both, it reports that limitation and selects the
lowest-false-match configuration retaining at least 70% recall.

This is a reproducible engineering evaluation using synthetic cases. It does
not constitute operational calibration or validation.

## Train the synthetic ML prototype

The ML trainer generates labeled scenarios, splits complete scenarios before
candidate feature rows are constructed, compares logistic regression with a
Random Forest, calibrates each model on a separate scenario split, and evaluates
the selected artifact on held-out scenarios:

```cmd
python -m src.object_identification.ml_association ^
  --cases 300 ^
  --seed 20260728 ^
  --output-directory outputs\object_identification\ml
```

Generated artifacts:

- `object-identification-ml.joblib` - selected model, separate probability
  calibrator, feature contract, and synthetic-domain bounds;
- `object-identification-ml-report.json` - split sizes, model comparisons,
  held-out metrics, versions, selection rule, and limitations.

The model uses residual, covariance-normalized distance, measurement quality,
rule score, candidate count, rule rank, and score-gap features. Inference
abstains when any feature is outside the synthetic training domain and returns
the transparent rule-based prediction as a fallback.

The calibrated value is a synthetic candidate-match score, not an operational
probability. Representative independent labeled data is required before model
approval.

## Run ML inference

After training, run the saved artifact against one observation and one or more
candidate triplets:

```cmd
python -m src.object_identification.ml_inference ^
  --artifact outputs\object_identification\ml\object-identification-ml.joblib ^
  --observation tests\fixtures\object_identification\tracking-observation.example.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\clear-best.catalog.json tests\fixtures\object_identification\multi_candidate\clear-best.orbital.json tests\fixtures\object_identification\multi_candidate\clear-best.affiliation.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\clear-mid.catalog.json tests\fixtures\object_identification\multi_candidate\clear-mid.orbital.json tests\fixtures\object_identification\multi_candidate\clear-mid.affiliation.json ^
  --candidate tests\fixtures\object_identification\multi_candidate\ambiguous-near.catalog.json tests\fixtures\object_identification\multi_candidate\ambiguous-near.orbital.json tests\fixtures\object_identification\multi_candidate\ambiguous-near.affiliation.json ^
  --output outputs\object_identification\ml\inference-prediction.json
```

The artifact loader rejects incompatible artifact, feature-contract, or
dependency versions. A compatible artifact uses ML only when every candidate
feature is inside the synthetic training domain. Otherwise, the output remains
schema-valid and records `rule_fallback`, `abstained: true`, and the abstention
reason under `inference_assurance`.
