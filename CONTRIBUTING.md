# Contributing

## Branch workflow

1. Start new development from `dev`.
2. Create a short-lived branch for the change.
3. Keep generated reports and local environments out of commits.
4. Run the full test suite before pushing.
5. Merge validated work into `dev`, then fast-forward `main` for a release.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Validation

Run all tests from the repository root:

```powershell
python -m unittest discover -s tests -t . -v
```

GitHub Actions runs the same suite with the oldest supported Python version
and the current development version. Do not merge a change while either job is
failing.

## Repository hygiene

- Do not commit API keys, credentials, `.env` files, or proprietary data.
- Treat files under `outputs/` and module-specific output directories as
  generated artifacts unless a fixture is intentionally stored under `tests/`.
- Keep changes focused and include regression tests for behavioral changes.
- Document prototype assumptions and validation limits explicitly.
