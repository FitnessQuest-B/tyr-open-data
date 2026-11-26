# Compatibility and schema generation

## Profiles

| Artifact | Identity | Supported use |
|---|---|---|
| TYR Settings export | Application ID 0 and application schema version 92 | Read approved projections from a closed, standalone export. |
| Open Data records | Application ID `TYRD` and file schema version 1 | Create an empty projected database and query it with SQLite or Python. |
| Brain Lab sidecar | Application ID `TYRB` and file schema version 1 | Inspect the nine Brain tables and the two intervention identity relations in a separate database. |

The export adapter compares named projected columns, declared types, nullability, primary keys, approved checks, foreign keys and supported unconditional uniqueness. Physical column order can vary. Private columns, app defaults, indexes used only for app performance, and triggers outside the projected records contract can differ. A missing required owner key prevents admission. The v92 profile covers single-owner and uninitialized app databases. Unknown app versions and active database files with recovery sidecars require a standalone export under an admitted version before use.

The records file preserves source column names, SQLite types, nullability, selected checks, primary keys, retained foreign keys and their actions, and eligible unconditional unique keys. The projection omits app auto-generated defaults, sequence policy, private columns and whole-app triggers. The owner table carries only a local surrogate ID. The application schema stores some polymorphic relations and ownership associations without declared foreign keys. The generated relationship inventory lists physical enforcement. A consumer must interpret polymorphic log entities using `entity_type` and `entity_id`. Some target libraries, including saved meals and recipes, sit outside this profile.

## Reading observations

- Rows are ordered by the declared primary key. Use `--limit` and `--offset` for bounded reads within a stable source file.
- Direct owner keys and approved owner joins scope reads to the local owner. An uninitialized owner has an empty owner-scoped series. Global catalogue rows can still be present.
- `available` establishes that the table shape is supported. The data may contain missing observations, historical gaps and tombstones. Where the schema supports deletion fields, the reader preserves them so consumers can make the intended historical or active-record choice.
- A detected or indeterminate health-history route marks the affected steps, heart rate or summary projection `limited`. The current adapter covers persisted storage rows. It does not combine routes or reconstruct effective day-by-day history. Summary projections can contain app-calculated values, with calculation versions and coverage fields where available.
- File-wide foreign key violations are reported as a count or JSON null if the check cannot be completed. Records are never repaired by the reader. Scope joins exclude orphaned rows where ownership cannot be established.
- Nutrition day keys and observation timestamps have different semantics. A missing value stays SQL NULL and JSON null. See the [table dictionary](../data-dictionary/README.md) and [measurement guide](../measurements/README.md) for field interpretation.

## Build provenance

The private workflow runs TYR's creation and startup machinery at a pinned revision on disposable files. It captures private SQLite metadata and generates approved objects through an explicit table, column, index and trigger allowlist. The empty public files are built by replaying the resulting SQL on blank databases. App seed rows and export rows never enter the empty files.

A v92 fresh file and a reviewed synthetic v91-to-v92 upgrade are checked independently, including copies produced by the actual records snapshot code while committed and uncommitted WAL writes are present. The private probe compares generated output across both schema paths and checks selected results against the blank records schema populated with disposable sentinel rows. A native validator probe tests the Brain sidecar without shipping the production codec.

For a future TYR schema release, update the private capture checkpoint and allowlist, compare key and projection behavior, and explicitly admit new export profiles after test results are reviewed. Generate a version folder with SQL, a compatibility manifest, an inventory and foreign key documentation. Update the active version pointer only after clean replay, reproducibility, and package checks pass. Public consumers can rebuild from that SQL without private source or Flutter.

The file receipt records hashes from a pinned SQLite runtime. Automated verification compares logical structure across runtimes and tests two byte-identical clean builds in the installed runtime. It also compares to the distributed bytes when SQLite versions match.
