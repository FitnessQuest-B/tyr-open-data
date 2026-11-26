# TYR Brain Lab

Brain Lab is an offline Python and SQLite environment for exploratory, individual analysis. It reads compatible closed TYR v92 exports and TYR Open Data 0.1.0 records projections. Start with a generated synthetic file. Use Python 3.10 or later linked to SQLite 3.41.0 or later with JSON support.

## Run the changing-relationship example

From the repository root, generate the synthetic observations and choose a separate private Lab file.

```sh
job=$(mktemp -d)
python3 -B tools/generate_synthetic.py generate changing \
  --agent-root "$job/observations" --truth-root "$job/evaluator" > "$job/bundle.json"
bundle_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$job/bundle.json")
source_file="$job/observations/$bundle_id/records.sqlite"
lab_file="$job/lab/findings.sqlite"

python3 -B brain-lab/lab.py discover "$source_file"
python3 -B brain-lab/lab.py describe "$source_file" --metric total_sleep_minutes \
  --start 2025-01-06 --end 2025-04-24
python3 -B brain-lab/lab.py propose --method late-caffeine-sleep \
  --start 2025-01-06 --end 2025-04-24 > "$job/early.json"
python3 -B brain-lab/lab.py analyze "$source_file" "$job/early.json"
python3 -B brain-lab/lab.py init "$source_file" "$lab_file"
python3 -B brain-lab/lab.py record "$source_file" "$lab_file" "$job/early.json" > "$job/first.json"
```

`discover` shows portable measurements and projection availability. `describe` reports sample count, expected days, coverage, source classes and descriptive statistics. `propose` writes a parameterized question plan to stdout. `analyze` uses only the source and prints the result. `record` recomputes it and persists a hypothesis, evaluation, cohort evidence, assessment and knowledge links in the Lab file.

Reassess the same hypothesis on a later window. The original evaluation remains in history.

```sh
hypothesis=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["hypothesis_uuid"])' "$job/first.json")
run_key=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_key"])' "$job/first.json")
python3 -B brain-lab/lab.py propose --method late-caffeine-sleep \
  --start 2025-05-06 --end 2025-09-12 > "$job/later.json"
python3 -B brain-lab/lab.py record "$source_file" "$lab_file" "$job/later.json" --hypothesis "$hypothesis"
python3 -B brain-lab/lab.py inspect "$source_file" "$lab_file" --run "$run_key"
python3 -B brain-lab/lab.py replay "$source_file" "$lab_file" --run "$run_key"
python3 -B brain-lab/lab.py wiki "$source_file" "$lab_file" > "$job/review.md"
```

The default configuration of the changing subject yields `supported` in the earlier interval and `notSupported` with `recheckRequired` in the later interval. A replay recomputes the analysis and compares its result digest. A repeat of the same record request returns the original run. The wiki includes each result’s coverage, interpretation, competing explanations, evaluation UUID and evidence fingerprints.

## Baseline change

```sh
python3 -B brain-lab/lab.py scan-baseline "$source_file" --metric body_weight \
  --start 2025-01-06 --end 2025-09-01
python3 -B brain-lab/lab.py propose --method baseline-change --metric body_weight \
  --start 2025-01-06 --split 2025-04-28 --end 2025-09-01 \
  --minimum-change-milli 1000 > "$job/body-weight.json"
python3 -B brain-lab/lab.py analyze "$source_file" "$job/body-weight.json"
```

All date windows use civil labels and exclusive end dates. A meaningful-change threshold is expressed in thousandths of the documented metric unit. The caffeine method uses the two timing groups within training-day and weekend strata, with common support. It pairs the caffeine date with the next wake date. It excludes after-midnight dose times, missing sleep clock fields and doses at or after an identifiable overnight bedtime. Stored clock labels leave some travel and elapsed-time uncertainty. The baseline method compares observed means on each side of the declared split. A scan ranks eligible weekly splits as exploratory candidates and does not save a finding.

## Source and write isolation

Use a closed Settings export or projected file. Source connections use SQLite read-only mode, `query_only` and an explicit read transaction. The Lab uses the existing allowlisted adapter for native v92 files and checks the exact projected schema for generated data. It rechecks source identity and bytes before recording. Steps and HR projections with effective routing remain unavailable for Lab methods. The caffeine and body-weight workflows use stored nutrition, training and weight fields from daily snapshots, with the routing limitation carried into the interpretation.

The Lab initializer creates a separate private file and binds it to the source SHA-256, local owner and profile. It mirrors only active intervention and period identities when those projections are available. The writer verifies the Lab schema before opening a writable connection, registers the restricted Brain validator only in the verified transaction, and uses an SQLite authorizer to block arbitrary schema, attachment and core or identity writes during analyses. The CLI accepts versioned plans and has no SQL execution command. Filesystem permissions still matter. Keep the source mount read-only and give untrusted processes access only to the intended input or CLI. Keep Lab files and outputs outside the candidate checkout.

If an export changes, pass the new file to `status` to detect a stale binding. The old Lab cannot record, inspect, replay or render against the changed export. A new export requires a separate Lab. Existing reports and the old Lab are local files under the owner’s retention and deletion control. The workflow does not poll other files or delete source-linked research records automatically.

## Interpretation and scope

Coverage uses observed eligible days over the expected calendar window. For caffeine cohorts, expected group membership is unknown on unlogged days, so the per-group denominator remains NULL. The leave-one-14-day-block-out range is a sensitivity diagnostic, with no confidence level. Sparse samples, missing common support or a result crossing the meaningful-change boundary yield `inconclusive`. The adjustment includes recorded workouts and weekend, while dose variation, unmeasured influences and informative logging can remain. Baseline scans use the same data both to choose and to estimate candidate splits. Seek later or independent data before treating a candidate as established.

The roughly 90-day idea is represented as a window-length indicator for review. It does not determine metric adequacy or trigger recommendations. The Lab registers exploratory analyses and permits a later non-overlapping reassessment within the same bound export. All workflows use local deterministic methods. The [offline benchmark](../benchmark/README.md) exercises these methods and optional mock provider adapters.

The [Brain contract](../docs/brain/README.md) and [table dictionary](../docs/brain/tables.md) describe the portable tables. The Lab adds a [source binding and append-only run ledger](lab_metadata.sql) to its own initialized file. The shipped [empty schema fixture](../schema/versions/0.1.0/brain-lab.sql) remains the portable Brain structure for inspection and schema verification.
