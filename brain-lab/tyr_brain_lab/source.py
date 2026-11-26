"""Open supported closed records without exposing write access."""

import hashlib
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from read_export import Export, MAX_ROWS, check_export_file
from schema_support import load_contract, quote, require_sqlite, schema_objects

CONTRACT_VERSION = "0.1.0"
SOURCE_TABLES = (
    "user", "daily_snapshot", "daily_sleep", "daily_steps", "daily_heart_rate",
    "morning_hrv", "interventions", "intervention_periods",
)


def file_hash(path):
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
        return checksum.hexdigest()


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _verified_hash(path):
    before = _identity(path)
    checksum = file_hash(path)
    if before != _identity(path):
        raise ValueError("Source changed while it was being read")
    return checksum, before


class Source:
    def __init__(self, path, db, contract, checksum, identity):
        self.path = path
        self._identity = identity
        self._db = db
        self._profiles = contract["export_projections"]
        self._cache = {}
        application = db.execute("PRAGMA application_id").fetchone()[0]
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if application == 0:
            self._adapter = Export(db, contract)
            inspection = self._adapter.inspection()
            owners = self._adapter.rows("user", limit=2)["rows"]
            profile = "tyr_v92_export"
        else:
            expected = contract["artifacts"]["records"]
            if (application != expected["application_id"] or version != expected["file_schema_version"]
                    or schema_objects(db) != expected["objects"]):
                raise ValueError("Source is outside the supported TYR records profiles")
            self._adapter = None
            self._db.row_factory = sqlite3.Row
            owners = self._db.execute('SELECT id FROM "user" ORDER BY id LIMIT 2').fetchall()
            violations = self._db.execute("PRAGMA foreign_key_check").fetchone()
            inspection = {
                "projections": {table: {"status": "available"} for table in self._profiles},
                "foreign_key_violations": 0 if violations is None else "present",
            }
            profile = "open_data_projection"
        if len(owners) > 1 or (owners and (type(owners[0]["id"]) is not int or owners[0]["id"] <= 0)):
            raise ValueError("The Lab uses a single local owner for each source")
        self.owner = owners[0]["id"] if owners else None
        self.capabilities = inspection["projections"]
        self.manifest = {
            "sha256": checksum, "profile": profile, "sqlite_user_version": version,
            "contract_version": contract["specification_version"], "owner_key": self.owner,
            "foreign_key_violations": inspection["foreign_key_violations"],
        }

    def assert_unchanged(self):
        check_export_file(self.path)
        checksum, identity = _verified_hash(self.path)
        if identity != self._identity or checksum != self.manifest["sha256"]:
            raise ValueError("Source changed during the Lab operation")

    def rows(self, table, *, snapshot_columns=False):
        if table not in SOURCE_TABLES:
            raise ValueError("The Lab analysis cannot read this source table")
        # Routed steps and HR do not affect the caffeine, training and weight
        # fields requested by Lab methods from a stored daily snapshot.
        partial = table == "daily_snapshot" and snapshot_columns
        status = self.capabilities[table]["status"]
        if status != "available" and not (partial and status == "limited"):
            raise ValueError(f"{table} projection is {status}")
        if table not in self._cache:
            if self._adapter:
                rows = []
                while True:
                    page = self._adapter.rows(table, limit=MAX_ROWS, offset=len(rows), allow_partial=partial)["rows"]
                    rows.extend(page)
                    if len(page) < MAX_ROWS:
                        break
            else:
                profile = self._profiles[table]
                fields = ", ".join(map(quote, profile["columns"]))
                order = ", ".join(map(quote, profile["primary_key"]))
                scoped = "user_id" in profile["columns"]
                where = ' WHERE "user_id"=?' if scoped else ""
                params = (self.owner,) if scoped else ()
                rows = [dict(row) for row in self._db.execute(
                    f"SELECT {fields} FROM {quote(table)}{where} ORDER BY {order}", params
                )]
                for row in rows:
                    for key, value in row.items():
                        kind = profile["required_shape"][key]["type"]
                        expected = {"INTEGER": (int,), "REAL": (int, float), "TEXT": (str,)}[kind]
                        if value is not None and (type(value) not in expected
                                                  or (type(value) is float and not math.isfinite(value))):
                            raise ValueError(f"Unexpected stored value type in {table}.{key}")
            self._cache[table] = rows
        return self._cache[table]

    def intervention_identities(self):
        if any(self.capabilities[table]["status"] != "available" for table in ("interventions", "intervention_periods")):
            return [], []
        interventions = [(row["id"], row["uuid"]) for row in self.rows("interventions") if not row["is_deleted"]]
        known = {item[0] for item in interventions}
        periods = [
            (row["id"], row["intervention_id"], row["uuid"]) for row in self.rows("intervention_periods")
            if not row["is_deleted"] and row["deleted_at"] is None and row["intervention_id"] in known
        ]
        return interventions, periods


@contextmanager
def open_source(path):
    require_sqlite()
    path = Path(path).resolve(strict=True)
    check_export_file(path)
    checksum, identity = _verified_hash(path)
    _, contract = load_contract(CONTRACT_VERSION)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, cached_statements=0)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        source = Source(path, db, contract, checksum, identity)
        if _identity(path) != identity:
            raise ValueError("Source changed before it could be opened")
        yield source
        source.assert_unchanged()
    finally:
        db.close()
