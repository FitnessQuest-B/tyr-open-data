# Synthetic TYR records

Generate the starter observations from the repository root with Python 3.10 or later linked to SQLite 3.41.0 or later with JSON support. The generator uses the standard library and creates each file from blank versioned SQL. It accepts scenario parameters and a seed. It never opens a personal database or imports commercial reference data.

```sh
job=$(mktemp -d)
python3 -B tools/generate_synthetic.py generate stable \
  --agent-root "$job/agent" --truth-root "$job/evaluator"
```

Use the returned opaque ID in place of `BUNDLE_ID`.

```sh
python3 -B tools/generate_synthetic.py verify-agent "$job/agent/BUNDLE_ID"
sqlite3 -readonly "$job/agent/BUNDLE_ID/records.sqlite" .tables
```

The observation file uses the Open Data 0.1.0 projected schema. Query it with SQLite or Python using read-only access. The v92 export adapter is for the native TYR application export profile, which has a different SQLite identity. The supplied records [coverage SQL](../../examples/sql/daily_coverage.sql) also works on a generated observation file.

## Starter subjects

| Scenario key | Span | Design |
|---|---:|---|
| `stable` | 210 days | Stable comparison series with a zero late-caffeine effect by construction. |
| `caffeine_timing` | 224 days | Same caffeine amount at two clock times. Late assignment is more frequent on training days, and training also affects simulated sleep. |
| `changing` | 252 days | The embedded timing effect ends after a regime change, with a shift in weight and sleep baselines and a deliberate evidence blackout around the change. |
| `travel_gaps` | 238 days | Explicit clock offset transitions, variable wake times, uneven logging and deliberate gaps. The model applies a zero direct late-dose effect. |

Each subject includes fictitious food, supplement and exercise references, logs and nutrient snapshots, activity, weight, workout sets, cardio bouts and sleep records. Daily snapshots expose selected, simplified derived columns and use calculation version 0. There are no app rolling-baseline rows. Hourly step rows are partial samples and do not sum to daily steps. Missing observations stay absent in source tables and NULL in the relevant snapshot columns.

Nutrition uses its civil day key. In these scenarios, use the next stored sleep wake date when asking about the relationship between that day’s caffeine and the following night. The first observed date has no preceding exposure in the fixture. The final exposure has no following outcome inside the fixture window. The simulated offset schedule is explicit and requires no installed timezone dataset.

## Keep ground truth out of an agent run

The two output roots must be disjoint and separate from this checkout. The generator places just `records.sqlite` in the agent bundle. It places `truth.json` under the same opaque ID in the evaluator root. The latter includes the seed, phase-specific parameters and effects, confounders, noise, observation gaps, observed group sizes and database hashes. These values describe the simulation.

For a blind run, mount only the single verified bundle and the approved analysis instructions. Keep the scenario configuration, generator source, seed, evaluator root, local review mapping and other bundles outside the agent’s filesystem and conversation. Run the generator in the evaluator workspace. Use a fresh held-out seed with `--seed`, which replaces the public starter seed. The starter seeds in this checkout are suitable for development and review. The package verifier checks layout, SQLite identity and integrity. The mount or process boundary controls filesystem access.

## Reproduce or add a scenario

Use the same scenario configuration, seed and generator version to reproduce the observations. Logical hashes cover named rows in primary-key order and the projected schema. Database bytes are reproducible with the same pinned Python and SQLite runtime. Opaque IDs are randomly allocated for packaging. Use `--bundle-id` with a previously recorded 32-character lowercase hexadecimal ID and fresh output roots if the evaluator JSON must also reproduce byte for byte.

See the [scenario configuration](../../scenarios/README.md) and [starter definitions](../../scenarios/starter.json).
