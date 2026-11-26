import hashlib
import json
import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from test_contract import FILES, TemporaryCase, create_empty, load_contract

ROOT = Path(__file__).resolve().parents[1]


def documented_columns(*paths):
    actual = {}
    current = None
    for path in paths:
        for line in path.read_text().splitlines():
            table = re.fullmatch(r"## `([^\x60]+)`", line)
            field = re.fullmatch(r"\| `([^\x60]+)` \| `([^\x60]+)` \| (Yes|No) \| (.+) \|", line)
            if table:
                current = table[1]
                if current in actual:
                    raise AssertionError(f"Duplicate documented table {current}")
                actual[current] = {}
            elif field:
                name, kind, nullable, _ = field.groups()
                if name in actual[current]:
                    raise AssertionError(f"Duplicate documented column {current}.{name}")
                actual[current][name] = (kind, nullable)
    return actual


class DictionaryTests(unittest.TestCase):
    def test_table_dictionary_covers_every_supported_column_and_nullability(self):
        folder, _ = load_contract()
        inventory = json.loads((folder / "inventory.json").read_text())
        dictionary = ROOT / "docs/data-dictionary"
        records = documented_columns(*(dictionary / f"{group}.md" for group in (
            "body-and-training", "health", "nutrition", "interventions-and-summaries",
        )))
        brain = documented_columns(ROOT / "docs/brain/tables.md")
        self.assertEqual(set(records), set(inventory["records"]))
        self.assertEqual(set(brain), set(inventory["brain-lab"]) - {"interventions", "intervention_periods"})
        for family, documented in (("records", records), ("brain-lab", brain)):
            for table, fields in documented.items():
                with self.subTest(table=table):
                    columns = inventory[family][table]["columns"]
                    primary_count = sum(info["pk"] > 0 for info in columns.values())
                    expected = {}
                    for name, info in columns.items():
                        rowid_alias = info["type"] == "INTEGER" and info["pk"] and primary_count == 1
                        nullable = "No" if info["not_null"] or rowid_alias else "Yes"
                        expected[name] = (info["type"], nullable)
                    self.assertEqual(fields, expected)

    def test_documented_brain_units_match_the_generated_trigger(self):
        folder, _ = load_contract()
        ddl = (folder / "brain-lab.sql").read_text()
        expected = dict(re.findall(r"WHEN '([a-z0-9_]+)' THEN '([a-z_]+)'", ddl))
        registry = (ROOT / "docs/measurements/metric-registry.md").read_text()
        documented = dict(re.findall(r"^\| `([a-z0-9_]+)` \| `([a-z_]+)` \|", registry, re.M))
        self.assertEqual(len(expected), 20)
        self.assertEqual(documented, expected)

    def test_local_markdown_links_resolve(self):
        for page in ROOT.rglob("*.md"):
            if ".git" in page.relative_to(ROOT).parts:
                continue
            for target in re.findall(r"\]\(([^)]+)\)", page.read_text()):
                if target.startswith(("https://", "http://", "#")):
                    continue
                self.assertTrue((page.parent / target.split("#", 1)[0]).exists(), f"{page}: {target}")


class SqlExampleTests(TemporaryCase):
    def query(self, path, name):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            prelude, query = (ROOT / "examples/sql" / name).read_text().split(";", 1)
            db.execute(prelude)
            self.assertEqual(db.execute("PRAGMA query_only").fetchone(), (1,))
            return db.execute(query).fetchall()

    def test_shipped_empty_files_have_read_only_example_results(self):
        for kind, example, expected in (
            ("records", "daily_coverage.sql", [(7, 0, 0, None, 0, 0)]),
            ("brain-lab", "brain_evidence.sql", []),
        ):
            path = ROOT / "databases/empty" / FILES[kind]
            before = hashlib.sha256(path.read_bytes()).digest()
            self.assertEqual(self.query(path, example), expected)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_coverage_keeps_missing_values_and_recorded_zero_distinct(self):
        path = self.job / "projected.sqlite"
        create_empty("records", path)
        with closing(sqlite3.connect(path)) as db, db:
            db.executemany(
                """INSERT INTO daily_snapshot (id,user_id,snapshot_date,snapshot_version,calculation_version,
                        total_sleep_minutes,sleep_data_coverage_pct,caffeine_mg,computed_at)
                   VALUES (?,1,?,1,6,?,?,?,0)""",
                [(1, "2025-01-01", 420, 100, 0), (2, "2025-01-02", None, None, None),
                 (3, "2025-01-03", 100, None, 80)],
            )
        self.assertEqual(self.query(path, "daily_coverage.sql"), [(7, 3, 1, 420.0, 2, 1)])


if __name__ == "__main__":
    unittest.main()
