"""Read a closed native TYR export under an explicitly selected profile."""
import argparse
from datetime import date
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from native_brain_receipts import read_receipt
from read_export import Export, UnsupportedExport, check_export_file
from schema_support import ROOT, load_contract, require_sqlite

PROFILES = {"v92": 92, "v93": 93}


def manifest_for(profile):
    expected = PROFILES[profile]
    _, manifest = load_contract("0.1.0")
    if expected == 93:
        path = ROOT / "schema" / "native-export-profiles" / "v93.1.json"
        delta = json.loads(path.read_text())
        if delta["source_app_schema_version"] != 93:
            raise ValueError("Unexpected native profile")
        manifest["source_app_schema_version"] = 93
        for table, columns in delta["projection_columns"].items():
            projection = manifest["export_projections"][table]
            projection["columns"].extend(columns)
            projection["required_shape"].update({
                name: {"hidden": 0, "not_null": False, "pk": 0, "type": kind}
                for name, kind in columns.items()
            })
    return manifest


@contextmanager
def open_native(path, profile):
    require_sqlite()
    path = Path(path).resolve(strict=True)
    check_export_file(path)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, cached_statements=0)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        export = Export(db, manifest_for(profile))
        details = export.inspection()
        if profile == "v93" and any(details["projections"][table]["status"] == "unavailable"
                                    for table in ("log_entries", "workout_sessions")):
            raise UnsupportedExport("Missing required v93 temporal columns")
        yield path, db, export
    finally:
        db.close()


TEMPORAL_BASES = {
    "provider_supplied", "capture_device_at_observation", "user_selected",
    "import_device", "reference_calendar", "legacy_label", "unknown",
}
PRECISIONS = {"second", "minute", "approximate", "date_only", "unknown"}


def check_temporal_rows(table, rows):
    if table not in ("log_entries", "workout_sessions"):
        return
    prefix = "logged" if table == "log_entries" else "start"
    for row in rows:
        basis = row[f"{prefix}_temporal_basis"]
        precision = row[f"{prefix}_time_precision"]
        offset = row[f"{prefix}_utc_offset_minutes"]
        if ((basis is None) != (precision is None)
                or (basis is not None and basis not in TEMPORAL_BASES)
                or (precision is not None and precision not in PRECISIONS)
                or (offset is not None and (
                    type(offset) is not int or not -840 <= offset <= 840
                    or basis in (None, "unknown", "legacy_label")
                    or precision in ("date_only", "unknown")))):
            raise ValueError("Invalid native temporal provenance")
        if table == "workout_sessions":
            civil = row["assigned_civil_date"]
            assigned = row["assigned_day_basis"]
            if ((civil is None) != (assigned is None)
                    or (civil is not None and (
                        assigned not in TEMPORAL_BASES - {"import_device", "unknown"}
                        or not isinstance(civil, str) or len(civil) != 10
                        or date.fromisoformat(civil).isoformat() != civil))):
                raise ValueError("Invalid workout day assignment")


def identity(path):
    meta = path.stat()
    return meta.st_dev, meta.st_ino, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns


def hash_file(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--profile", choices=PROFILES, required=True)
    cli.add_argument("export", type=Path)
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--projection")
    mode.add_argument("--evaluation-uuid")
    cli.add_argument("--limit", type=int, default=100)
    args = cli.parse_args()
    try:
        owner_path = args.export.resolve(strict=True)
        check_export_file(owner_path)
        first = hash_file(owner_path) if args.evaluation_uuid else None
        token = identity(owner_path)
        with open_native(owner_path, args.profile) as (path, db, export):
            if args.evaluation_uuid:
                result = read_receipt(db, args.evaluation_uuid, PROFILES[args.profile])
                check_export_file(path)
                if first != hash_file(path) or token != identity(path):
                    raise ValueError("Source changed during Brain receipt export")
                result["source_sha256"] = first
                result["packet_version"] = "tyr.native.brain.receipt.v1"
            else:
                result = (export.rows(args.projection, limit=args.limit)
                          if args.projection else export.inspection())
                if args.projection and args.profile == "v93":
                    check_temporal_rows(args.projection, result["rows"])
        result["native_profile"] = {"v92": "v92.1", "v93": "v93.1"}[args.profile]
        print(json.dumps(result, allow_nan=False, sort_keys=True))
    except (OSError, ValueError, sqlite3.Error) as error:
        cli.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
