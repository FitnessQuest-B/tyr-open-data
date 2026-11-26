import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from unittest.mock import patch

from test_contract import ROOT, TemporaryCase, create_empty
from generate_synthetic import DEFAULT_CONFIG, generate, hash_file
from synthetic_model import load_scenario

sys.path.insert(0, str(ROOT / "brain-lab"))
from tyr_brain_lab import analysis, codec, store
from tyr_brain_lab.source import open_source

EARLY = ("2025-01-06", "2025-04-24")
LATER = ("2025-05-06", "2025-09-12")
CLI = ROOT / "brain-lab/lab.py"


def caffeine(window=EARLY):
    return analysis.config("late-caffeine-sleep", "total_sleep_minutes", *window)


class CodecTests(unittest.TestCase):
    def test_portable_codec_matches_native_dart_vectors(self):
        path = ROOT / "tests/fixtures/brain-v1-lab-vectors.json"
        for vector in json.loads(path.read_text()):
            encoded, digest = codec.specification(vector["payload"])
            self.assertEqual((encoded, digest), (vector["encoded"], vector["sha256"]))
            self.assertEqual(codec.validate_specification(encoded, digest), 1)
            self.assertEqual(codec.validate_specification(encoded + " ", codec.sha256(encoded + " ")), 0)
            self.assertEqual(codec.validate_specification(encoded, "0" * 64), 0)
            payload = vector["payload"]
            payload["analysisParameters"]["unsupportedFloat"] = 1.2
            with self.assertRaises(ValueError):
                codec.specification(payload)

    def test_bad_spec_and_invalid_unicode_fail_closed(self):
        for value in ("[]", "{", '{"payload":{},"version":1}', '{"payload":{},"version":true}'):
            self.assertEqual(codec.validate_specification(value, codec.sha256(value)), 0)
        with self.assertRaises(ValueError):
            codec.envelope({"x": 2**63})
        with self.assertRaises(UnicodeError):
            codec.envelope({"text": chr(0xd800)})


class LabCase(TemporaryCase):
    def fixture(self, scenario="changing"):
        result = generate(load_scenario(DEFAULT_CONFIG, scenario), self.job / "agent", self.job / "evaluator")
        return self.job / "agent" / result["id"] / "records.sqlite"

    def sql(self, lab, sql):
        with closing(sqlite3.connect(lab.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute(sql).fetchall()


class LabAnalysisTests(LabCase):
    def test_offline_discovery_descriptive_coverage_and_effect(self):
        path = self.fixture("caffeine_timing")
        before = hash_file(path)
        with open_source(path) as source:
            registry = analysis.discover(source)
            self.assertEqual(registry["measurements"]["total_sleep_minutes"]["unit"], "minutes")
            report = analysis.describe(source, "total_sleep_minutes", *EARLY)
            self.assertEqual(report["statistics"]["n"] + report["missing_or_excluded"], report["expected_days"])
            result = analysis.analyze(source, caffeine())
            self.assertEqual(result, analysis.analyze(source, caffeine()))
            self.assertEqual(result["evidence_decision"], "supported")
            self.assertLess(result["effect"], -20)
            self.assertFalse(result["recommendations_allowed"])
            self.assertEqual(result["claim_type"], "association")
            self.assertTrue(any(cell["used"] for cell in result["strata"].values()))
        self.assertEqual(hash_file(path), before)
        self.assertEqual({p.name for p in path.parent.iterdir()}, {"records.sqlite"})

    def test_caffeine_clock_filters_preserve_unambiguous_pairs(self):
        original = self.fixture()
        copy = self.job / "clock-cases.sqlite"
        shutil.copyfile(original, copy)
        with closing(sqlite3.connect(copy)) as db, db:
            pairs = db.execute("""SELECT snapshot.id, sleep.id FROM daily_snapshot AS snapshot
                JOIN daily_sleep AS sleep
                  ON date(sleep.date,'unixepoch')=date(snapshot.snapshot_date,'+1 day')
                WHERE snapshot.caffeine_last_dose_minute IS NOT NULL AND sleep.sleep_start_minute IS NOT NULL
                ORDER BY snapshot.id LIMIT 2""").fetchall()
            db.execute("UPDATE daily_snapshot SET caffeine_last_dose_minute=1500 WHERE id=?", (pairs[0][0],))
            db.execute("UPDATE daily_sleep SET sleep_start_minute=NULL WHERE id=?", (pairs[1][1],))
        with open_source(copy) as source:
            result = analysis.analyze(source, caffeine())
        self.assertGreater(result["exclusions"]["missing_training_or_ambiguous_exposure_clock"], 0)
        self.assertGreater(result["exclusions"]["missing_or_invalid_sleep_clock"], 0)

    def test_declared_baseline_change_and_exploratory_scan(self):
        path = self.fixture()
        plan = analysis.config("baseline-change", "body_weight", "2025-01-06", "2025-09-01", "2025-04-28")
        with open_source(path) as source:
            result = analysis.analyze(source, plan)
            self.assertLess(result["effect"], -3.5)
            self.assertEqual(result["claim_type"], "descriptive")
            self.assertEqual(result["evidence_decision"], "supported")
            scan = analysis.scan_baseline(source, "body_weight", "2025-01-06", "2025-09-01")
            self.assertEqual(scan["status"], "exploratory_candidates")
            self.assertIn(scan["candidates"][0]["split"], ("2025-04-21", "2025-04-28", "2025-05-05"))

    def test_missing_observations_stay_uncertain(self):
        path = self.fixture("travel_gaps")
        plan = caffeine(("2025-06-21", "2025-06-30"))
        with open_source(path) as source:
            result = analysis.analyze(source, plan)
            self.assertEqual(result["evidence_decision"], "inconclusive")
            self.assertEqual(result["eligible_days"], 0)
            self.assertIsNone(result["effect"])
            self.assertIsNone(result["sensitivity_range"])


class LabPersistenceTests(LabCase):
    def test_reassessment_replay_and_history_use_the_portable_tables(self):
        source_path = self.fixture()
        before = hash_file(source_path)
        lab = self.job / "findings.sqlite"
        with open_source(source_path) as source:
            store.initialize(lab, source)
            first = store.record(lab, source, caffeine())
            self.assertEqual(first["assessment"]["decision"], "supported")
            duplicate = store.record(lab, source, caffeine())
            self.assertEqual(duplicate["run_key"], first["run_key"])
            self.assertEqual(duplicate["status"], "already_recorded")
            with self.assertRaisesRegex(ValueError, "non-overlapping"):
                store.record(lab, source, caffeine(("2025-02-01", "2025-06-01")), first["hypothesis_uuid"])
            second = store.record(lab, source, caffeine(LATER), first["hypothesis_uuid"])
            self.assertEqual(second["assessment"]["decision"], "notSupported")
            self.assertEqual(second["assessment"]["applicability"], "recheckRequired")
            self.assertEqual(store.replay(lab, source, first["run_key"])["status"], "reproduced")
            self.assertEqual(store.replay(lab, source, second["run_key"])["status"], "reproduced")
            self.assertEqual(store.status(lab, source)["runs"], 2)
            traces = store.inspect(lab, source, first["run_key"])["result"]["evidence"]
            refs = [reference for cohort in traces for reference in cohort["reference_rows"]]
            self.assertEqual({ref["table"] for ref in refs}, {"daily_snapshot", "daily_sleep"})
            self.assertNotIn("value", refs[0])
        self.assertEqual(hash_file(source_path), before)
        self.assertEqual(self.sql(lab, "SELECT evidence_decision FROM brain_evaluation ORDER BY id"),
                         [("supported",), ("notSupported",)])
        self.assertEqual(self.sql(lab, "SELECT evidence_decision FROM brain_assessment"), [("notSupported",)])
        self.assertEqual(self.sql(lab, "SELECT count(*) FROM brain_evaluation_evidence"), [(4,)])
        self.assertEqual(self.sql(lab, "SELECT count(*) FROM brain_memory_link WHERE relation_type='supersedes'"), [(1,)])
        self.assertEqual(self.sql(lab, "PRAGMA foreign_key_check"), [])

    def test_writer_rolls_back_and_denies_out_of_scope_sql(self):
        source_path = self.fixture()
        lab = self.job / "findings.sqlite"
        with open_source(source_path) as source:
            store.initialize(lab, source)
            with self.assertRaisesRegex(RuntimeError, "simulated"), patch.object(
                store, "_knowledge", side_effect=RuntimeError("simulated late failure")
            ):
                store.record(lab, source, caffeine())
            self.assertEqual(self.sql(lab, "SELECT count(*) FROM brain_hypothesis"), [(0,)])
            self.assertEqual(self.sql(lab, "SELECT count(*) FROM brain_evaluation_evidence"), [(0,)])
            with store.open_lab(lab, source, write=True) as (db, _):
                for statement in (
                    "INSERT INTO interventions VALUES (5, 'blocked')",
                    "UPDATE lab_source SET lab_id='blocked'",
                    "CREATE TABLE forbidden(id INTEGER)",
                    "ATTACH DATABASE ':memory:' AS forbidden",
                    "PRAGMA writable_schema=ON",
                ):
                    with self.subTest(statement=statement), self.assertRaises(sqlite3.DatabaseError):
                        db.execute(statement)
            store.record(lab, source, caffeine())

    def test_source_same_inode_and_stale_bindings_are_blocked(self):
        original = self.fixture("changing")
        different = self.fixture("stable")
        lab = self.job / "findings.sqlite"
        alias = self.job / "alias.sqlite"
        os.link(original, alias)
        before = hash_file(original)
        with open_source(original) as source:
            with self.assertRaisesRegex(ValueError, "separate file"):
                store.initialize(alias, source)
            store.initialize(lab, source)
        lab_hash = hash_file(lab)
        with open_source(different) as source:
            self.assertEqual(store.status(lab, source)["status"], "stale")
            with self.assertRaises(store.StaleSource):
                store.record(lab, source, caffeine())
            with self.assertRaises(store.StaleSource):
                store.inspect(lab, source)
        self.assertEqual(hash_file(original), before)
        self.assertEqual(hash_file(lab), lab_hash)

    def test_untrusted_schema_is_rejected_before_recording(self):
        path = self.fixture()
        lab = self.job / "findings.sqlite"
        with open_source(path) as source:
            store.initialize(lab, source)
            with closing(sqlite3.connect(lab)) as db, db:
                db.execute("CREATE TABLE unexpected(payload TEXT)")
            before = hash_file(lab)
            with self.assertRaisesRegex(ValueError, "intact"):
                store.record(lab, source, caffeine())
            self.assertEqual(hash_file(lab), before)

    def test_projected_intervention_mirrors_are_minimal(self):
        projected = self.job / "records.sqlite"
        create_empty("records", projected)
        with closing(sqlite3.connect(projected)) as db, db:
            db.execute("INSERT INTO user VALUES (1)")
            db.execute("""INSERT INTO interventions
                       (id,uuid,name,intervention_type,is_custom,is_deleted)
                       VALUES (1,'fixture-int','private label','other',1,0)""")
            db.execute("""INSERT INTO intervention_periods
                       (id,user_id,uuid,intervention_id,started_at,start_day_key,is_deleted)
                       VALUES (1,1,'fixture-period',1,0,20250101,0)""")
        lab = self.job / "findings.sqlite"
        with open_source(projected) as source:
            created = store.initialize(lab, source)
        self.assertEqual(created["mirrored_periods"], 1)
        self.assertEqual(self.sql(lab, "SELECT * FROM intervention_periods"), [(1, 1, "fixture-period")])
        self.assertNotIn(b"private label", lab.read_bytes())

    def test_cli_wiki_references_recorded_evidence(self):
        path = self.fixture()
        lab = self.job / "findings.sqlite"
        plan = self.job / "plan.json"
        plan.write_text(json.dumps(caffeine()))
        with open_source(path) as source:
            store.initialize(lab, source)
        receipt = subprocess.run([sys.executable, "-B", str(CLI), "record", str(path), str(lab), str(plan)],
                                 check=True, capture_output=True, text=True)
        first = json.loads(receipt.stdout)
        wiki = subprocess.run([sys.executable, "-B", str(CLI), "wiki", str(path), str(lab)],
                              check=True, capture_output=True, text=True).stdout
        self.assertIn(first["evaluation_uuid"], wiki)
        self.assertIn(first["run_key"], wiki)
        self.assertIn("Competing explanations", wiki)
        self.assertIn("fingerprint", wiki)


if __name__ == "__main__":
    unittest.main()
