import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from native_brain_receipts import envelope
from read_native import check_temporal_rows, manifest_for


class TestNativeCompatibility(unittest.TestCase):
    def test_explicit_version_and_preserved_v92_manifest(self):
        old = manifest_for("v92")
        newer = manifest_for("v93")
        self.assertEqual(old["source_app_schema_version"], 92)
        self.assertEqual(newer["source_app_schema_version"], 93)
        self.assertNotIn("logged_temporal_basis", old["export_projections"]["log_entries"]["columns"])
        self.assertIn("logged_temporal_basis", newer["export_projections"]["log_entries"]["columns"])
        self.assertEqual(set(old["export_projections"]), set(newer["export_projections"]))

    def test_null_ambiguous_and_coherent_capture(self):
        row = dict(start_temporal_basis=None, start_time_precision=None,
                   start_utc_offset_minutes=None, assigned_civil_date=None,
                   assigned_day_basis=None)
        check_temporal_rows("workout_sessions", [row])
        captured = dict(row, start_temporal_basis="capture_device_at_observation",
                        start_time_precision="second", start_utc_offset_minutes=-240,
                        assigned_civil_date="2026-09-18",
                        assigned_day_basis="capture_device_at_observation")
        check_temporal_rows("workout_sessions", [captured])
        with self.assertRaises(ValueError):
            check_temporal_rows("workout_sessions", [dict(captured, assigned_civil_date="2026-02-30")])
        with self.assertRaises(ValueError):
            check_temporal_rows("workout_sessions", [dict(captured, start_time_precision="date_only")])
        with self.assertRaises(ValueError):
            check_temporal_rows("workout_sessions", [dict(row, start_utc_offset_minutes=0)])

    def test_envelope_rejects_duplicate_keys_and_bad_versions(self):
        self.assertEqual(envelope('{"payload":{},"version":1}')["payload"], {})
        for bad in ['{"payload":{},"version":true}', '{"payload":{},"version":2}',
                    '{"payload":{"x":1,"x":2},"version":1}']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                envelope(bad)
