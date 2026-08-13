# SDA Satellite Digital Twin

[![Tests](https://github.com/williamlabasi-hub/Digital-Twin/actions/workflows/tests.yml/badge.svg)](https://github.com/williamlabasi-hub/Digital-Twin/actions/workflows/tests.yml)

## Overview

The SDA Satellite Digital Twin is a modular software framework that models, monitors, analyzes, and predicts satellite behavior using artificial intelligence and machine learning.

## Team

- William Labasi
- Landon Jobe
- Jake Labasi

## Current Modules

- Orbital Propagation
- Health Status Monitoring
- Collision Risk Assessment
- Object Identification
- Operator Recommendations

## Languages

- Python

## Status

- Under Development

## Quick start

From a fresh clone, create an isolated Python environment and install the
project from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the complete automated test suite:

```powershell
python -m unittest discover -s tests -t . -v
```

Generated reports are written under `outputs/` or the module-specific data
output folders and are intentionally excluded from version control.

Development and branch conventions are documented in `CONTRIBUTING.md`.

## Integrated golden path

Run the versioned synthetic Health, Object Identification, Collision Risk, and
COA workflow end to end:

```powershell
python scripts\run_golden_path.py
```

Use Landon's live TLE retrieval and propagation stage with:

```powershell
python scripts\run_golden_path.py --orbital-source live
```

The validated artifacts are written under `outputs/golden-path/`. See
[`docs/GOLDEN_PATH.md`](docs/GOLDEN_PATH.md) for the scenario boundaries and
artifact inventory.

## Capstone health demo

Launch the presentation-ready health ML dashboard from the repository root:

```powershell
python demo\start_demo.py
```

Then open `http://127.0.0.1:8000/demo/`. The dashboard uses the committed,
schema-validated fixture under `demo/data/`; see `demo/README.md` for the
suggested presentation flow and refresh procedure.
