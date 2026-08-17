# Integrated operator dashboard

This dependency-free browser dashboard presents the latest validated
golden-path run across Health, Object Identification, Collision Risk, and COA
decision support. It displays prototype evidence and operator review options;
it cannot authorize or execute commands or maneuvers.

## Run

From the repository root:

```powershell
python demo\start_demo.py
```

The launcher first publishes a new deterministic golden-path run, then serves
the dashboard at `http://127.0.0.1:8000/demo/`. Use `--scenario` to demonstrate
an expected degraded-evidence mode, or `--skip-run` to display the current
latest run without generating another one.

The browser reads `/api/dashboard`. The server validates `latest.json` and the
referenced summary against dashboard contract Version 1.0.0, constrains all
artifact paths to the published run, and returns the detailed Health, identity,
collision, and COA artifacts. Missing, invalid, or unsupported data produces a
visible compatibility error rather than guessed display values.

## Suggested presentation flow

1. Identify `SAT-001` and the associated secondary track.
2. Review the four subsystem status cards.
3. Explain why degraded or withheld evidence limits the COA result.
4. Review the ordered candidate COAs and their planning-only scope.
5. End at operator review and the visible no-command-authority boundary.
