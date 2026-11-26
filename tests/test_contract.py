import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from create_empty import create_empty
from read_export import Export, UnsupportedExport, open_export
from schema_support import MIN_SQLITE_VERSION, check_empty, columns, foreign_keys, load_contract, schema_objects, unique_keys

FILES = {
    "records": "tyr-open-data-0.1.0.sqlite",
    "brain-lab": "tyr-brain-lab-0.1.0.sqlite",
}
PROFILE_TABLES = {
    "user", "body_measurement_point", "body_measurement", "body_weight", "exercise_table",
    "workout_sessions", "exercise_sets", "cardio_activities", "cardio_activity_summaries",
    "cardio_recovery_tests", "daily_steps", "hourly_steps", "daily_heart_rate", "hourly_heart_rate",
    "daily_sleep", "sleep_segments", "morning_hrv", "food_sources", "foods", "food_nutrients",
    "food_portions", "nutrients", "supplements", "supplement_nutrients", "log_entries",
    "log_entry_nutrients", "interventions", "intervention_periods", "intervention_outcome_metric",
    "intervention_supplements", "daily_snapshot", "baseline_metric",
}
LAB_TABLES = {
    "brain_assessment", "brain_context_event", "brain_evaluation", "brain_evaluation_evidence",
    "brain_hypothesis", "brain_hypothesis_intervention", "brain_hypothesis_metric",
    "brain_memory_link", "brain_memory_node", "interventions", "intervention_periods",
}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        job = tempfile.TemporaryDirectory()
        self.addCleanup(job.cleanup)
        self.job = Path(job.name)


class EmptyDatabaseTests(TemporaryCase):
    def test_rebuilds_empty_files_with_exact_schema_and_pinned_binary_reproduction(self):
        _, contract = load_contract()
        receipt = json.loads((ROOT / "databases/empty/manifest.json").read_text())
        for kind, filename in FILES.items():
            with self.subTest(kind=kind):
                expected = contract["artifacts"][kind]
                paths = [ROOT / "databases/empty" / filename, self.job / filename, self.job / f"second-{filename}"]
                for path in paths[1:]:
                    create_empty(kind, path)
                for path in paths:
                    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                        check_empty(db, expected)
                        self.assertEqual(db.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                self.assertEqual(file_hash(paths[0]), receipt["sha256"][filename])
                self.assertEqual(file_hash(paths[1]), file_hash(paths[2]))
                if sqlite3.sqlite_version == receipt["sqlite_version"]:
                    self.assertEqual(file_hash(paths[0]), file_hash(paths[1]))

    def test_existing_destination_is_preserved(self):
        file = self.job / "existing.sqlite"
        file.write_bytes(b"keep existing bytes")
        with self.assertRaises(FileExistsError):
            create_empty("records", file)
        self.assertEqual(file.read_bytes(), b"keep existing bytes")

    def test_unsupported_sqlite_fails_before_creating_an_artifact(self):
        destination = self.job / "unsupported.sqlite"
        with patch("sqlite3.sqlite_version_info", (3, 40, 1)), patch("sqlite3.sqlite_version", "3.40.1"):
            with self.assertRaisesRegex(ValueError, "SQLite 3.41.0 or later is required"):
                create_empty("brain-lab", destination)
        self.assertFalse(destination.exists())

    def test_projection_shape_and_scope_match_manifest(self):
        folder, contract = load_contract()
        self.assertEqual(tuple(map(int, contract["sqlite_minimum"].split("."))), MIN_SQLITE_VERSION)
        inventory = json.loads((folder / "inventory.json").read_text())
        self.assertEqual(set(contract["export_projections"]), PROFILE_TABLES)
        self.assertEqual(set(inventory["records"]), PROFILE_TABLES)
        self.assertEqual(set(inventory["brain-lab"]), LAB_TABLES)
        for kind, filename in FILES.items():
            with closing(sqlite3.connect((ROOT / "databases/empty" / filename).as_uri() + "?mode=ro", uri=True)) as db:
                self.assertEqual(
                    {obj["name"] for obj in schema_objects(db) if obj["kind"] == "table"} - {"sqlite_sequence"},
                    PROFILE_TABLES if kind == "records" else LAB_TABLES,
                )
                for table, shape in inventory[kind].items():
                    self.assertEqual(columns(db, table), shape["columns"])
                    self.assertEqual(foreign_keys(db, table), shape["foreign_keys"])
                    if kind == "records":
                        expected = contract["export_projections"][table]
                        for column, source in expected["required_shape"].items():
                            self.assertEqual({key: shape["columns"][column][key] for key in source}, source)
                        self.assertEqual(shape["foreign_keys"], expected["foreign_keys"])
                        for key in expected["unique_keys"]:
                            self.assertIn(key, unique_keys(db, table))
                        self.assertEqual(list(columns(db, table)), expected["columns"])

    def test_records_keys_and_checks(self):
        path = self.job / "records.sqlite"
        create_empty("records", path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute('INSERT INTO user VALUES (1)')
            db.execute('INSERT INTO body_measurement_point VALUES (1, ?, ?)', ("synthetic", "Fixture"))
            for point, value in ((1, -1), (99, 5)):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO body_measurement VALUES (1, 1, NULL, ?, ?, 123)', (point, value))
            db.execute('INSERT INTO daily_steps VALUES (1, 1, 123, 20, ?, NULL)', ("manual",))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO daily_steps VALUES (2, 1, 123, 21, ?, NULL)', ("manual",))


class ReadAdapterTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.path = self.job / "owner export #1.sqlite"
        create_empty("records", self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                PRAGMA application_id=0;
                PRAGMA user_version=92;
                ALTER TABLE user ADD COLUMN email TEXT;
                ALTER TABLE body_weight ADD COLUMN note TEXT;
                CREATE TABLE health_interpretation_routes(user_id INTEGER, data_type TEXT);
                CREATE TABLE unified_health_routes(user_id INTEGER, data_type TEXT);
                INSERT INTO user VALUES (1,'fixture@example.invalid');
                INSERT INTO body_weight VALUES (1,1,72.5,2,'manual',NULL,'private marker');
                INSERT INTO body_weight VALUES (2,2,79,2,'manual',NULL,'unowned row');
                INSERT INTO exercise_table (id, name_key, system_created, category, equipment_type, per_dumbbell)
                  VALUES (1,'fixture_exercise',1,'fixture','fixture',0);
                INSERT INTO workout_sessions VALUES (1,1,1,2,NULL,'manual',100,NULL);
                INSERT INTO workout_sessions VALUES (2,2,1,2,NULL,'manual',100,NULL);
                INSERT INTO exercise_sets (id,session_id,exercise_id,set_index,source,confidence)
                  VALUES (1,1,1,0,'manual',100), (2,2,1,0,'manual',100);
                INSERT INTO daily_steps VALUES (1,1,10,42,'manual',NULL);
                INSERT INTO hourly_steps VALUES (1,1,8,21,NULL);
            ''')

    def execute(self, sql):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(sql)

    def test_single_owner_allowlist_and_source_preservation(self):
        before = file_hash(self.path)
        with open_export(self.path) as export:
            self.assertEqual(export.inspection()["foreign_key_violations"], 2)
            self.assertEqual(export.rows("user")["rows"], [{"id": 1}])
            record, = export.rows("body_weight")["rows"]
            self.assertEqual(record["weight_kg"], 72.5)
            self.assertIsNone(record["deleted_at"])
            self.assertNotIn("note", record)
            exercise, = export.rows("exercise_sets")["rows"]
            self.assertEqual(exercise["session_id"], 1)
            self.assertEqual(export.rows("exercise_sets", offset=1)["rows"], [])
            with self.assertRaisesRegex(UnsupportedExport, "Unknown projection"):
                export.rows("health_interpretation_routes")
            with self.assertRaises(ValueError):
                export.rows("body_weight", limit=-1)
        self.assertEqual(file_hash(self.path), before)
        self.assertEqual({item.name for item in self.job.iterdir()}, {self.path.name})

    def test_projection_authorizer_leaves_the_read_connection_usable(self):
        _, manifest = load_contract()
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            self.assertEqual(Export(db, manifest).rows("user")["rows"], [{"id": 1}])
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 92)

    def test_routes_are_limited_including_children_and_summaries(self):
        self.execute("INSERT INTO unified_health_routes VALUES (1,'steps')")
        with open_export(self.path) as export:
            self.assertEqual(export.inspection()["projections"]["daily_snapshot"]["status"], "limited")
            self.assertEqual(export.inspection()["projections"]["daily_heart_rate"]["status"], "available")
            with self.assertRaisesRegex(UnsupportedExport, "--allow-partial"):
                export.rows("hourly_steps")
            self.assertEqual(export.rows("hourly_steps", allow_partial=True)["rows"][0]["steps"], 21)

    def test_python_example_respects_route_limits_and_preserves_the_export(self):
        self.execute("INSERT INTO unified_health_routes VALUES (1,'steps')")
        self.execute("""INSERT INTO daily_sleep
            (id, user_id, date, total_minutes, stage_quality, source)
            VALUES (1, 1, 10, 420, 'unavailable', 'manual')""")
        before = file_hash(self.path)
        command = [sys.executable, "-B", str(ROOT / "examples/python/inspect_health_coverage.py"),
                   str(self.path), "--limit", "1"]
        reply = subprocess.run(command, check=True, capture_output=True, text=True)
        report = json.loads(reply.stdout)
        sleep = report["projections"]["daily_sleep"]
        self.assertEqual(sleep["value_counts"], {"total_minutes": 1, "deep_minutes": 0})
        self.assertEqual(sleep["rows_inspected"], 1)
        steps = report["projections"]["daily_steps"]
        self.assertEqual(steps["capability"]["status"], "limited")
        self.assertNotIn("value_counts", steps)
        self.assertEqual(file_hash(self.path), before)
        self.assertEqual({item.name for item in self.job.iterdir()}, {self.path.name})

    def test_missing_route_metadata_is_unknown(self):
        self.execute("DROP TABLE unified_health_routes")
        with open_export(self.path) as export:
            report = export.inspection()["projections"]["daily_steps"]
            self.assertEqual(report["routes"], ["steps:unknown"])
            self.assertEqual(report["status"], "limited")

    def test_missing_ownership_dependency_is_unavailable(self):
        self.execute("DROP TABLE workout_sessions")
        with open_export(self.path) as export:
            with self.assertRaisesRegex(UnsupportedExport, "owner join unavailable"):
                export.rows("exercise_sets")

    def test_invalid_version_and_wal_are_rejected(self):
        self.execute("PRAGMA user_version=91")
        with self.assertRaisesRegex(UnsupportedExport, "version 91"), open_export(self.path):
            self.fail("unsupported version admitted")
        self.execute("PRAGMA journal_mode=WAL")
        with self.assertRaisesRegex(UnsupportedExport, "DELETE journal"), open_export(self.path):
            self.fail("live WAL source admitted")

    def test_projected_database_and_multiple_owners_are_rejected(self):
        public_file = self.job / "public.sqlite"
        create_empty("records", public_file)
        with self.assertRaises(UnsupportedExport), open_export(public_file):
            self.fail("projection admitted as TYR export")
        self.execute("INSERT INTO user (id) VALUES (2)")
        with self.assertRaisesRegex(UnsupportedExport, "single local owner"), open_export(self.path):
            self.fail("multiple owners admitted")


class BrainSchemaTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        file = self.job / "lab.sqlite"
        create_empty("brain-lab", file)
        self.db = sqlite3.connect(file, isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")

    def test_period_belongs_to_bound_intervention(self):
        self.db.executescript('''
            INSERT INTO interventions VALUES (1,'synthetic-alpha'), (2,'synthetic-beta');
            INSERT INTO intervention_periods VALUES (1,2,'synthetic-period');
            INSERT INTO brain_hypothesis
                (id,uuid,title,statement,domain,hypothesis_type,claim_type,origin_type,registered_at,registration_mode)
              VALUES (1,'00000000-0000-4000-8000-000000000001','Fixture','Fixture','test','descriptive',
                'descriptive','user',1,'retrospective');
        ''')
        insert = '''INSERT INTO brain_hypothesis_intervention
            (uuid,hypothesis_id,intervention_id,intervention_period_id,relationship_role)
            VALUES ('00000000-0000-4000-8000-000000000002',1,?,1,'exposure')'''
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(insert, (1,))
        self.db.execute(insert, (2,))

    def test_evaluation_write_fails_without_native_validator(self):
        with self.assertRaisesRegex(sqlite3.OperationalError, "tyr_brain_specification_valid"):
            self.db.execute("EXPLAIN INSERT INTO brain_evaluation DEFAULT VALUES")

    def test_evidence_rejects_bad_units_and_orphan_commit(self):
        insert = '''INSERT INTO brain_evaluation_evidence
            (uuid,evaluation_id,metric_key,metric_role,cohort_role,source_type,window_start,window_end,sample_count,canonical_unit)
            VALUES ('00000000-0000-4000-8000-000000000002',9,'total_steps','outcome','baseline','aggregate',1,2,1,?)'''
        with self.assertRaisesRegex(sqlite3.IntegrityError, "canonical"):
            self.db.execute(insert, ("minutes",))
        self.db.execute("BEGIN")
        self.db.execute(insert, ("steps",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("COMMIT")
        self.db.execute("ROLLBACK")
        self.assertEqual(self.db.execute("SELECT count(*) FROM brain_evaluation_evidence").fetchone(), (0,))


if __name__ == "__main__":
    unittest.main()
