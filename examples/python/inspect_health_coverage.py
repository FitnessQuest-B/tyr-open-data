"""Count available stored observations in a bounded read of a TYR v92 export."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from read_export import MAX_ROWS, open_export


def inspect(path, limit):
    with open_export(path) as export:
        profile = export.inspection()
        results = {}
        for table, fields in (
            ("daily_sleep", ("total_minutes", "deep_minutes")),
            ("daily_steps", ("total_steps",)),
        ):
            capability = profile["projections"][table]
            result = {"capability": capability}
            if capability["status"] == "available":
                rows = export.rows(table, limit=limit)["rows"]
                active = [row for row in rows if row["deleted_at"] is None]
                result.update(
                    rows_inspected=len(rows),
                    active_rows=len(active),
                    value_counts={field: sum(row[field] is not None for row in active) for field in fields},
                )
            results[table] = result

    return {
        "source_app_schema_version": profile["source_app_schema_version"],
        "owner_status": profile["owner_status"],
        "foreign_key_violations": profile["foreign_key_violations"],
        "row_limit_per_projection": limit,
        "projections": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_ROWS:
        parser.error(f"--limit must be between 1 and {MAX_ROWS}")
    try:
        result = inspect(args.export, args.limit)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, "A compatible closed TYR v92 export is required.\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
