import json
import sqlite3
import subprocess
import sys
import unittest
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from statistics import mean

from test_contract import ROOT, TemporaryCase
from generate_synthetic import DEFAULT_CONFIG, generate, hash_file, verify_bundle
from synthetic_model import load_scenario

DURATIONS = {"stable": 210, "caffeine_timing": 224, "changing": 252, "travel_gaps": 238}


def ro(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))


class SyntheticTests(TemporaryCase):
    def fixture(self, name, *, tag="", bundle_id=None, seed=None):
        scenario = load_scenario(DEFAULT_CONFIG, name, seed)
        agent = self.job / f"{tag}agent"
        evaluator = self.job / f"{tag}evaluator"
        result = generate(scenario, agent, evaluator, bundle_id)
        bundle = agent / result["id"]
        truth = evaluator / result["id"] / "truth.json"
        return bundle, truth, result

    def test_all_starters_reproduce_and_are_self_contained(self):
        for index, (name, length) in enumerate(DURATIONS.items()):
            with self.subTest(scenario=name):
                identifier = f"{index + 1:032x}"
                first, truth, result = self.fixture(name, bundle_id=identifier)
                second, second_truth, replay = self.fixture(name, tag="repeat-", bundle_id=identifier)
                self.assertEqual(result, replay)
                self.assertEqual((first / "records.sqlite").read_bytes(), (second / "records.sqlite").read_bytes())
                self.assertEqual(truth.read_bytes(), second_truth.read_bytes())
                manifest = json.loads(truth.read_text())
                self.assertFalse(manifest["provenance"]["uses_personal_records"])
                self.assertEqual(manifest["date_window"]["until_day"], length)
                self.assertEqual(manifest["observation_package"]["sha256"], result["sha256"])
                self.assertEqual(manifest["observation_package"]["logical_sha256"], result["logical_sha256"])
                self.assertEqual(set(child.name for child in first.iterdir()), {"records.sqlite"})
                self.assertNotIn(name.encode(), (first / "records.sqlite").read_bytes())
                self.assertEqual(verify_bundle(first), result)
                with ro(first / "records.sqlite") as db:
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                    self.assertEqual(db.execute("SELECT count(*) FROM daily_snapshot").fetchone(), (length,))
                    self.assertEqual(db.execute("SELECT count(*) FROM user").fetchone(), (1,))
                    self.assertEqual(db.execute("SELECT count(*) FROM workout_sessions").fetchone(), (length // 7 * 4,))
                    self.assertGreater(db.execute("SELECT count(*) FROM log_entry_nutrients").fetchone()[0], 1000)

    def test_seed_changes_observations_and_custom_config_is_supported(self):
        _, truth, original = self.fixture("stable")
        original_seed = json.loads(truth.read_text())["seed"]
        _, _, other = self.fixture("stable", seed=original_seed + 1)
        self.assertNotEqual(original["logical_sha256"], other["logical_sha256"])
        self.assertNotEqual(original["id"], other["id"])

        config = self.job / "custom.json"
        config.write_text(json.dumps({
            "format_version": 1,
            "scenarios": {"custom": {
                "seed": 4, "start_date": "2025-01-06", "days": 180,
                "phases": [{"from_day": 0, "missing": {"nutrition": 1}}],
            }},
        }))
        custom = load_scenario(config, "custom")
        result = generate(custom, self.job / "agent-custom", self.job / "evaluator-custom")
        with ro(self.job / "agent-custom" / result["id"] / "records.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM log_entries").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT count(*) FROM daily_snapshot WHERE caffeine_mg IS NULL").fetchone(), (180,))

    def test_agent_verification_rejects_truth_files_and_linked_databases(self):
        agent, truth, _ = self.fixture("stable")
        misplaced = agent / "metadata.json"
        misplaced.write_bytes(truth.read_bytes())
        with self.assertRaisesRegex(ValueError, "only an ordinary"):
            verify_bundle(agent)
        misplaced.unlink()

        invalid_bundle = self.job / "a" / ("c" * 32)
        invalid_bundle.mkdir(parents=True)
        (invalid_bundle / "records.sqlite").symlink_to(agent / "records.sqlite")
        with self.assertRaisesRegex(ValueError, "only an ordinary"):
            verify_bundle(invalid_bundle)

    def test_root_overlap_and_reuse_are_rejected_without_replacing_output(self):
        scenario = load_scenario(DEFAULT_CONFIG, "stable")
        shared = self.job / "shared"
        with self.assertRaisesRegex(ValueError, "disjoint"):
            generate(scenario, shared, shared / "truth")
        self.assertFalse(shared.exists())
        real = self.job / "real"
        real.mkdir()
        alias = self.job / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "disjoint"):
            generate(scenario, alias, real / "truth")
        identifier = "1" * 32
        agent, truth, _ = self.fixture("stable", bundle_id=identifier)
        original = (hash_file(agent / "records.sqlite"), hash_file(truth))
        with self.assertRaises(FileExistsError):
            self.fixture("changing", bundle_id=identifier)
        self.assertEqual((hash_file(agent / "records.sqlite"), hash_file(truth)), original)
        blocked_agent = self.job / "reserved-agent"
        with self.assertRaises(FileExistsError):
            generate(scenario, blocked_agent, self.job / "evaluator", identifier)
        self.assertEqual(list(blocked_agent.iterdir()), [])

    def test_cli_emits_opaque_result(self):
        agent = self.job / "agent"
        evaluator = self.job / "evaluator"
        tool = ROOT / "tools/generate_synthetic.py"
        reply = subprocess.run([sys.executable, "-B", str(tool), "generate", "changing",
                                "--agent-root", str(agent), "--truth-root", str(evaluator)],
                               check=True, capture_output=True, text=True)
        result = json.loads(reply.stdout)
        self.assertEqual(set(result), {"id", "sha256", "logical_sha256"})
        self.assertRegex(result["id"], r"^[0-9a-f]{32}$")
        checked = subprocess.run([sys.executable, "-B", str(tool), "verify-agent", str(agent / result["id"])],
                                 check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(checked.stdout), result)

    def test_effect_and_change_are_visible_in_projected_observations(self):
        expected = {"stable": (0,), "caffeine_timing": (-32,), "changing": (-34, 0)}
        for name, effects in expected.items():
            with self.subTest(scenario=name):
                agent, truth, _ = self.fixture(name)
                phases = json.loads(truth.read_text())["phases"]
                with ro(agent / "records.sqlite") as db:
                    paired = db.execute("""
                        SELECT day.id - 1, day.workout_session_count, day.caffeine_last_dose_minute,
                               sleep.total_minutes
                        FROM daily_snapshot AS day
                        JOIN daily_sleep AS sleep
                          ON date(sleep.date, 'unixepoch') = date(day.snapshot_date, '+1 day')
                        WHERE day.caffeine_last_dose_minute IS NOT NULL
                    """).fetchall()
                    # These are fixture acceptance bands, independent of any benchmark scorer.
                    for phase, target in zip(phases, effects, strict=True):
                        self.assertEqual(phase["causal_effect"]["late_minus_early_minutes"], target)
                        groups = defaultdict(list)
                        for index, trained, dose, duration in paired:
                            if phase["from_day"] <= index < phase["until_day"]:
                                groups[trained, dose].append(duration)
                        for trained in (0, 1):
                            late, early = groups[trained, 1020], groups[trained, 630]
                            self.assertGreaterEqual(min(len(late), len(early)), 15)
                            self.assertLess(abs(mean(late) - mean(early) - target), 12)
                    if name == "changing":
                        before, after = db.execute("""
                            SELECT avg(CASE WHEN id <= 108 THEN body_weight END),
                                   avg(CASE WHEN id > 120 THEN body_weight END) FROM daily_snapshot
                        """).fetchone()
                        self.assertGreater(before - after, 3.5)

    def test_travel_offsets_and_deliberate_gaps_preserve_civil_semantics(self):
        agent, truth, _ = self.fixture("travel_gaps")
        manifest = json.loads(truth.read_text())
        self.assertEqual(len(manifest["insufficient_evidence_periods"]), 2)
        with ro(agent / "records.sqlite") as db:
            offsets = db.execute("""
                SELECT DISTINCT 480 - (entry.logged_at - unixepoch(day.snapshot_date)) / 60
                FROM log_entries AS entry
                JOIN daily_snapshot AS day ON cast(replace(day.snapshot_date,'-','') AS INTEGER) = entry.day_key
                WHERE entry.meal_type = 'breakfast' AND entry.entity_type = 'FOOD'
            """).fetchall()
            self.assertEqual({value for value, in offsets}, {-420, -300, -240, 60})
            self.assertEqual(db.execute("""
                SELECT count(*) FROM daily_snapshot
                WHERE id - 1 >= 89 AND id - 1 < 95 AND total_steps IS NOT NULL
            """).fetchone(), (0,))
            self.assertEqual(db.execute("""
                SELECT count(*) FROM daily_snapshot
                WHERE id - 1 >= 166 AND id - 1 < 175 AND caffeine_mg IS NOT NULL
            """).fetchone(), (0,))
            self.assertEqual(db.execute("""
                SELECT count(*) FROM daily_sleep
                WHERE date % 86400 != 0 OR sleep_end - sleep_start != total_minutes * 60
                  OR sleep_start_minute NOT BETWEEN 0 AND 1439 OR sleep_end_minute NOT BETWEEN 0 AND 1439
            """).fetchone(), (0,))
            self.assertEqual(db.execute("""
                SELECT count(*) FROM (
                    SELECT sleep.id FROM daily_sleep AS sleep JOIN sleep_segments AS segment ON segment.daily_sleep_id=sleep.id
                    GROUP BY sleep.id HAVING sum(segment.duration_minutes) != sleep.total_minutes
                )
            """).fetchone(), (0,))


if __name__ == "__main__":
    unittest.main()
