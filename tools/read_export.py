"""Inspect an offline TYR v92 export or read an approved projection as JSON."""

import argparse
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from schema_support import columns, foreign_keys, load_contract, quote, require_sqlite, unique_keys

ROUTES = ("health_interpretation_routes", "unified_health_routes")
RECOVERY_SUFFIXES = ("-wal", "-shm", "-journal")
MAX_ROWS = 1000


class UnsupportedExport(ValueError):
    pass


def ordinary_tables(db):
    return {name for schema, name, kind, *_ in db.execute("PRAGMA table_list")
            if schema == "main" and kind == "table"}


def projection_issue(db, table, profile):
    actual = columns(db, table)
    for name, requirement in profile["required_shape"].items():
        col = actual.get(name)
        if col is None or any(col[key] != value for key, value in requirement.items()):
            return f"required column shape differs: {name}"
    if not all(key in foreign_keys(db, table) for key in profile["foreign_keys"]):
        return "required foreign key differs"
    present_unique = unique_keys(db, table)
    if not all(key in present_unique for key in profile["unique_keys"]):
        return "required unique key differs"
    sql = db.execute("SELECT sql FROM sqlite_schema WHERE name=? AND type='table'", (table,)).fetchone()[0]
    for check in profile["checks"]:
        if check not in sql:
            return "required check differs"
    return None


def route_states(db, actual, owner):
    route_columns = {"user_id": "INTEGER", "data_type": "TEXT"}
    if any(table not in actual for table in ROUTES):
        return {kind: "unknown" for kind in ("steps", "heart_rate")}
    for table in ROUTES:
        shape = columns(db, table)
        if any(shape.get(col, {}).get("type") != kind or shape[col]["hidden"]
               for col, kind in route_columns.items()):
            return {kind: "unknown" for kind in ("steps", "heart_rate")}
    if owner is None:
        return {kind: "absent" for kind in ("steps", "heart_rate")}
    return {
        kind: "present" if any(db.execute(
            f"SELECT 1 FROM {quote(table)} WHERE user_id=? AND data_type=? LIMIT 1", (owner, kind)
        ).fetchone() is not None for table in ROUTES) else "absent"
        for kind in ("steps", "heart_rate")
    }


def check_export_file(path):
    if not path.is_file():
        raise UnsupportedExport("Expected a standalone SQLite file")
    with path.open("rb") as handle:
        header = handle.read(100)
    if len(header) != 100 or header[:16] != b"SQLite format 3\0":
        raise UnsupportedExport("Expected a standalone SQLite file")
    if header[18:20] != b"\x01\x01" or any(path.with_name(path.name + suffix).exists() for suffix in RECOVERY_SUFFIXES):
        raise UnsupportedExport("Use a closed standalone TYR Settings export in DELETE journal mode")


class Export:
    """A single read transaction over an inert v92 owner export."""

    def __init__(self, db, manifest):
        self._db = db
        self._profiles = manifest["export_projections"]
        self.version = db.execute("PRAGMA user_version").fetchone()[0]
        if self.version != manifest["source_app_schema_version"]:
            raise UnsupportedExport(f"Unsupported TYR application schema version {self.version}")
        if db.execute("PRAGMA application_id").fetchone()[0] != 0:
            raise UnsupportedExport("Expected a TYR application export")
        actual = ordinary_tables(db)
        if "user" not in actual or projection_issue(db, "user", self._profiles["user"]):
            raise UnsupportedExport("Missing TYR local owner key")
        owners = db.execute('SELECT id FROM "user" LIMIT 2').fetchall()
        if len(owners) > 1 or (owners and (type(owners[0][0]) is not int or owners[0][0] <= 0)):
            raise UnsupportedExport("Expected a single local owner or uninitialized export")
        self._owner = owners[0][0] if owners else None
        try:
            self._fk_violations = sum(1 for _ in db.execute("PRAGMA foreign_key_check"))
        except sqlite3.DatabaseError:
            self._fk_violations = None

        routes = route_states(db, actual, self._owner)
        self._capabilities = {}
        for table, profile in self._profiles.items():
            issue = projection_issue(db, table, profile) if table in actual else "required table missing"
            self._capabilities[table] = {"status": "unavailable", "reason": issue} if issue else {"status": "available"}
            if not issue:
                affected = [f"{kind}:{routes[kind]}" for kind in profile.get("route_types", []) if routes[kind] != "absent"]
                if affected:
                    self._capabilities[table] = {
                        "status": "limited", "reason": "effective routed history is outside this projection", "routes": affected,
                    }
        for table, profile in self._profiles.items():
            parent = profile.get("owner_parent")
            while parent:
                parent_table = parent["table"]
                if self._capabilities[parent_table]["status"] == "unavailable":
                    self._capabilities[table] = {"status": "unavailable", "reason": "owner join unavailable"}
                    break
                parent = self._profiles[parent_table].get("owner_parent")

    def inspection(self):
        return {
            "source_app_schema_version": self.version,
            "owner_status": "single" if self._owner is not None else "uninitialized",
            "foreign_key_violations": self._fk_violations,
            "projections": self._capabilities,
        }

    def _query(self, table):
        profile = self._profiles[table]
        allowed = {table: set(profile["columns"])}
        joins = []
        level = 0
        scope = profile
        while parent := scope.get("owner_parent"):
            alias = f"t{level}"
            level += 1
            parent_table = parent["table"]
            allowed.setdefault(parent_table, set()).add("id")
            joins.append(f'JOIN {quote(parent_table)} t{level} ON {alias}.{quote(parent["column"])} = t{level}."id"')
            scope = self._profiles[parent_table]
            if scope.get("owner_parent"):
                allowed[parent_table].add(scope["owner_parent"]["column"])
        owner_scoped = "user_id" in scope["columns"]
        if owner_scoped and level:
            allowed[parent_table].add("user_id")
        select = ", ".join(f"t0.{quote(col)}" for col in profile["columns"])
        order = ", ".join(f"t0.{quote(col)}" for col in profile["primary_key"])
        where = f' WHERE t{level}."user_id" = ?' if owner_scoped else ""
        join_sql = " " + " ".join(joins) if joins else ""
        sql = f"SELECT {select} FROM {quote(table)} t0{join_sql}{where} ORDER BY {order} LIMIT ? OFFSET ?"
        return sql, [self._owner] if owner_scoped else [], allowed

    def rows(self, table, limit=100, offset=0, allow_partial=False):
        if table not in self._profiles:
            raise UnsupportedExport("Unknown projection")
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= MAX_ROWS or not 0 <= offset < 2**63:
            raise ValueError("Invalid row limit or offset")
        capability = self._capabilities[table]
        if capability["status"] == "unavailable":
            raise UnsupportedExport(f'{table}: {capability["reason"]}')
        if capability["status"] == "limited" and not allow_partial:
            raise UnsupportedExport(f"{table}: effective routed history is unavailable; use --allow-partial for storage rows")
        sql, bindings, allowed = self._query(table)

        def authorizer(action, relation, col, database, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and trigger is None:
                if database == "main" and col in allowed.get(relation, ()):
                    return sqlite3.SQLITE_OK
                # SQLite also authorizes a table access with an empty column
                # name when a query can use its rowid without loading fields.
                if not col and database in (None, "main") and relation in allowed:
                    return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        self._db.set_authorizer(authorizer)
        try:
            cursor = self._db.execute(sql, [*bindings, limit, offset])
            profile = self._profiles[table]
            keys = profile["columns"]
            types = {"INTEGER": (int,), "REAL": (int, float), "TEXT": (str,)}
            result = []
            for row in cursor:
                for col, value in zip(keys, row, strict=True):
                    if value is None:
                        continue
                    if type(value) not in types[profile["required_shape"][col]["type"]] or (
                        type(value) is float and not math.isfinite(value)
                    ):
                        raise UnsupportedExport(f"Unexpected value type in {table}.{col}")
                result.append(dict(zip(keys, row, strict=True)))
            return {"projection": table, "capability": capability, "rows": result}
        finally:
            # Python 3.10 treats None as a callback that fails every statement.
            self._db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)


@contextmanager
def open_export(path):
    try:
        require_sqlite()
    except ValueError as error:
        raise UnsupportedExport(str(error)) from error
    path = Path(path).resolve(strict=True)
    check_export_file(path)
    _, manifest = load_contract()
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, cached_statements=0)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        yield Export(db, manifest)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(required=True, dest="command")
    subcommands.add_parser("inspect").add_argument("file", type=Path)
    read = subcommands.add_parser("read")
    read.add_argument("file", type=Path)
    read.add_argument("projection")
    read.add_argument("--limit", type=int, default=100)
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    try:
        with open_export(args.file) as export:
            if args.command == "inspect":
                result = export.inspection()
            else:
                result = export.rows(args.projection, args.limit, args.offset, args.allow_partial)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True))
    except sqlite3.Error:
        parser.exit(1, "The SQLite export could not be read under the v92 contract.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
