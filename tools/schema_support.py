"""SQLite contract introspection shared by generation and verification."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_SQLITE_VERSION = (3, 41, 0)


def require_sqlite():
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        minimum = ".".join(map(str, MIN_SQLITE_VERSION))
        raise ValueError(f"SQLite {minimum} or later is required (found {sqlite3.sqlite_version})")


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def stable_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def columns(db, table):
    return {
        name: {"type": kind.upper(), "not_null": bool(required), "default": default, "pk": pk, "hidden": hidden}
        for _, name, kind, required, default, pk, hidden in db.execute(
            "SELECT * FROM pragma_table_xinfo(?)", (table,)
        )
    }


def foreign_keys(db, table):
    groups = {}
    for id_, _, parent, source, target, update, delete, _ in db.execute(
        "SELECT * FROM pragma_foreign_key_list(?) ORDER BY id, seq", (table,)
    ):
        entry = groups.setdefault(id_, {
            "columns": [], "table": parent, "references": [], "on_update": update, "on_delete": delete,
        })
        entry["columns"].append(source)
        entry["references"].append(target)
    return sorted(groups.values(), key=stable_json)


def unique_keys(db, table):
    """Named-column, unconditional, binary uniqueness, including composite PKs."""
    keys = set()
    for _, name, unique, _, partial in db.execute("SELECT * FROM pragma_index_list(?)", (table,)):
        if not unique or partial:
            continue
        parts = list(db.execute(
            "SELECT name, coll FROM pragma_index_xinfo(?) WHERE key=1 ORDER BY seqno", (name,)
        ))
        if parts and all(col is not None and collation == "BINARY" for col, collation in parts):
            keys.add(tuple(col for col, _ in parts))
    return [list(key) for key in sorted(keys)]


def schema_objects(db):
    return [
        {"kind": kind, "name": name, "table": table, "sha256": digest(sql)}
        for kind, name, table, sql in db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
        )
    ]


def load_contract(version=None):
    if version is None:
        version = json.loads((ROOT / "schema/current.json").read_text())["specification_version"]
    folder = ROOT / "schema/versions" / version
    return folder, json.loads((folder / "manifest.json").read_text())


def check_empty(db, expected):
    if db.execute("PRAGMA application_id").fetchone()[0] != expected["application_id"]:
        raise ValueError("Unexpected SQLite application identifier")
    if db.execute("PRAGMA user_version").fetchone()[0] != expected["file_schema_version"]:
        raise ValueError("Unexpected SQLite file schema version")
    if schema_objects(db) != expected["objects"]:
        raise ValueError("SQLite object manifest mismatch")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign key check failed")
    for obj in expected["objects"]:
        if obj["kind"] == "table" and db.execute(f'SELECT 1 FROM {quote(obj["name"])} LIMIT 1').fetchone():
            raise ValueError(f'Expected an empty table: {obj["name"]}')


def clean_connect(path: Path):
    require_sqlite()
    return closing(sqlite3.connect(path))
