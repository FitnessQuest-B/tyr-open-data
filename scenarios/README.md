# Define a synthetic scenario

Copy [starter.json](starter.json) to an evaluator-owned location and pass it to the generator with `--config`. The configuration format is version 1. Values are fictional simulation parameters. The generator cannot take an export as an observation source.

Each member of `scenarios` has a unique short key, an unsigned 64-bit integer `seed`, an ISO calendar `start_date`, a length of 180–365 days, and a list of `phases`. Index days from zero. The first phase starts at day zero and later start indices must be strictly increasing. Each phase carries its values forward to the next change.

| Optional phase parameter | Meaning |
|---|---|
| `sleep_minutes`, `sleep_noise` | Baseline duration and triangular noise width, in whole minutes |
| `late_effect_minutes` | Additive difference in following-night duration for a late dose, in whole minutes |
| `late_probability_quiet`, `late_probability_training` | Late-assignment probabilities for days without and with training |
| `weight_delta_kg` | Shift from the subject’s starting weight baseline, in kg |
| `offset_minutes` | Fictional fixed offset east of UTC, in whole minutes |
| `wake_minute`, `wake_jitter` | Wake-clock centre and triangular noise width, in whole minutes |
| `missing` | Per-domain observation omission probabilities for `nutrition`, `sleep`, `steps`, `heart_rate`, `hrv` or `weight` |

An optional `blackouts` list can set a missingness window regardless of the draws. Each entry has `from_day` inclusive, `until_day` exclusive and distinct names in `domains`. Sleep settings and sleep blackouts are indexed by the exposure day. The stored sleep row is assigned to the following wake date. Other blackout domains use their stored civil date.

The components separate scenario validation and the daily model, SQLite observation writing, and packaging. A contribution can add a parameterized scenario while reusing the storage layer. If a proposal adds a new causal mechanism or measurement, update the simulation, evaluator truth encoding and tests together. Test a known seed, coverage edge cases and the exact separation of observations from answers.
