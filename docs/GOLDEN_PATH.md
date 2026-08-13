# Integrated golden path

The golden-path runner exercises Health, Object Identification, Collision Risk,
the three COA evidence adapters, and COA decision support in one repeatable
workflow.

From the repository root:

```cmd
python scripts\run_golden_path.py
```

To retrieve TLEs and propagate them through Landon's `data_gen` implementation
before Object Identification, run:

```cmd
python scripts\run_golden_path.py --orbital-source live
```

Live mode requires network access to the configured public TLE service. Fixture
mode remains the default so local regression tests and CI are deterministic.
Live mode uses the current UTC execution time; fixture mode retains its fixed
scenario epoch.

Artifacts are written to `outputs/golden-path/`:

- one selected Health report for `SAT-001`;
- the orbital-generation inputs and provenance in `orbital-generation.json`;
- the three-candidate Object Identification bundle;
- a complete Collision Risk assessment between `SAT-001` and the identified
  secondary object;
- one validated COA evidence envelope from each subsystem;
- the final validated COA report; and
- a compact `summary.json` for automated inspection.

The COA report includes a Version 0.2 decision-tree trace and structured
candidate COAs. In the committed golden-path scenario, historical Health
evidence is degraded, collision risk is moderate, and the tree produces:

- improve degraded evidence (prerequisite);
- refine tracking (recommended for review); and
- begin maneuver-planning review (planning only).

Every candidate requires operator approval and retains the global prohibition
on autonomous commands and maneuvers.

The default runner uses versioned synthetic inputs. Live orbital mode replaces
the Object Identification propagation fixtures with records produced by
`src.common.data_gen.orbit_catalog` and passes the selected secondary plus a
separately propagated primary proxy into Collision Risk. Hard-body radii and
spacecraft identity mappings remain prototype assumptions, while Health uses
versioned telemetry. Live mode intentionally omits the fixture covariance, so
Collision Risk returns geometry only and withholds probability. The runner does not claim that
subsystem timestamps represent one synchronized operational event. The generated
report remains prototype, non-operational decision support with no command
authority.

Run its regression test with:

```cmd
python -m unittest tests.test_golden_path -v
```
