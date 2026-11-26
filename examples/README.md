# Read-only examples

The SQL files use the shipped projected schema. The Python example uses the allowlisted adapter for a closed TYR v92 Settings export. Run the examples from the repository root.

## SQLite

```sh
sqlite3 -readonly -header -column databases/empty/tyr-open-data-0.1.0.sqlite < examples/sql/daily_coverage.sql
sqlite3 -readonly -header -column databases/empty/tyr-brain-lab-0.1.0.sqlite < examples/sql/brain_evidence.sql
```

The coverage query shows how to keep a seven-day calendar denominator and count actual stored values. Set the example owner ID and bounds in the query when working with an authorized projected file. On the shipped empty database it reports seven expected days, zero observations and an empty mean. The Brain evidence query lists hypotheses, current assessment references, and evaluation and cohort evidence without free text. Its shipped empty database returns no rows.

## Python

```sh
python3 -B examples/python/inspect_health_coverage.py /path/to/closed-TYR-records.sqlite --limit 100
```

This prints the admitted profile and a bounded coverage report for sleep and steps. It skips limited and unavailable projections while preserving their stated reason. Counts describe the inspected rows in primary-key order. They do not estimate calendar coverage. Keep any output about an owner’s records local.

## Agent prompts

Use [read-only evidence questions](agent-prompts/read-only-review.md) to inspect the contract, check coverage, and distinguish a descriptive result from a hypothesis. The same instructions work with the shipped empty examples.
