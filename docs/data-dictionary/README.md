# TYR v92 data dictionary

This dictionary covers all 32 records projections in TYR Open Data 0.1.0. It describes the columns exposed by the v92 export adapter and the matching empty records database. Use SQLite column names throughout.

| Domain | Reference |
|---|---|
| Owner key, body measurements, workouts, exercise and cardio | [Body measurements and training](body-and-training.md) |
| Daily and hourly steps, heart rate, sleep and HRV | [Activity, heart rate and sleep](health.md) |
| Food and supplement reference data, intake ledger and nutrient snapshots | [Nutrition and supplements](nutrition.md) |
| Intervention definitions, periods, outcomes, daily snapshots and rolling statistics | [Interventions and derived summaries](interventions-and-summaries.md) |
| Hypotheses, evaluations, evidence, assessments, context and knowledge links | [Brain table dictionary](../brain/tables.md) |

## How to read the entries

- **SQLite type and NULL allowed** describe the projected declarations. A primary-key `INTEGER` is a row identifier. Some nullable columns are required under particular conditions. The DDL defines those conditions.
- Numeric bounds described as **app checks** or **app input rules** come from the v92 source. The projected fixture enforces the selected checks in its own SQL. Historical records can have a wider value set. Analytical eligibility can be stricter than either schema.
- Identifiers are local to a file and table unless the field explicitly encodes a typed UUID. Reference rows can include user-owned labels. A foreign key preserves a structural link. A polymorphic or logical relationship needs its stated key, type and ownership context.
- SQLite stores status flags as integers, normally 0 and 1. `NULL`, the absence of a row, an explicit zero, a deletion timestamp and an unavailable projection are distinct states. Inspect the source profile before treating a missing row as an observation.
- Import and device provenance can differ within one owner’s history. Derived rows and estimates inherit uncertainty from their inputs. Use the [measurement guide](../measurements/README.md) for the unit, date, coverage and source conventions.

For full structural details, use the [versioned records SQL](../../schema/versions/0.1.0/records.sql), [machine-readable column inventory](../../schema/versions/0.1.0/inventory.json), [compatibility manifest](../../schema/versions/0.1.0/manifest.json) and [foreign-key inventory](../../schema/versions/0.1.0/foreign-keys.md). These are the sources for defaults, key actions and the exact projection allowlist.
