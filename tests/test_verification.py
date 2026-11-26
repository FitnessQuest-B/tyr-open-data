import math
import sys
from datetime import date, timedelta

from test_contract import ROOT, TemporaryCase

sys.path[:0] = [str(ROOT / "benchmark"), str(ROOT / "brain-lab")]

import pilot
import protocol
import verification
from evidence_method import weight_decision
from pilot_design import task_record
from synthetic_storage import build_records
from verification_design import CASE_COUNTS, DEVELOPMENT_SEED, expected, make_case
from worker import execute


class WeightTests(TemporaryCase):
    def predict(self, step, *, gap=False, drift=0):
        start = date(2025, 1, 1)
        points = []
        for day in range(240):
            if day % 11 == 0 or (gap and 105 <= day < 135):
                continue
            points.append({"day": (start + timedelta(days=day)).isoformat(),
                           "value": 80 + drift * day / 239 + (step if day >= 120 else 0) + 0.12 * math.sin(day),
                           "references": [{"table": "daily_snapshot", "row_id": day + 1, "column": "body_weight"}]})
        return weight_decision(points, start.isoformat(), (start + timedelta(days=240)).isoformat())

    def test_withholds_near_threshold_and_gap_decisions(self):
        for step, gap in ((1.13, False), (2.5, True), (-2.5, True)):
            with self.subTest(step=step, gap=gap):
                self.assertEqual(self.predict(step, gap=gap)["decision"], "inconclusive")

    def test_signed_clear_steps_and_drift_controls(self):
        for step, drift in ((-2.35, 3.0), (2.35, -3.0)):
            result = self.predict(step, drift=drift)
            self.assertEqual(result["decision"], "change")
            self.assertAlmostEqual(result["effect"], step, delta=0.25)
            self.assertLessEqual(abs((protocol.civil(result["split"]) - date(2025, 5, 1)).days), 14)
            self.assertGreaterEqual(len(result["references"]), 2)
        self.assertEqual(self.predict(0.35, drift=3)["decision"], "no_change")


class VerificationTests(TemporaryCase):
    def test_private_reassessment_requires_qualified_public_design(self):
        with self.assertRaisesRegex(ValueError, "public panel"):
            verification.prepare(self.job / "holdout", revision=5)
        with self.assertRaisesRegex(ValueError, "public panel"):
            verification.prepare(self.job / "holdout", revision=5,
                                 calibration={"passed": True, "design_sha256": "stale"})
        self.assertFalse((self.job / "holdout").exists())

    def test_both_directions_preserve_adjacent_and_bridged_windows(self):
        for family in ("sleep_loss", "sleep_gain"):
            for replica in (0, 8):
                with self.subTest(family=family, replica=replica):
                    identifier, first, days, windows, truth = make_case(DEVELOPMENT_SEED, family, replica)
                    packet = self.job / identifier
                    packet.mkdir()
                    data = packet / "records.sqlite"
                    build_records(data, days)
                    task = task_record(identifier, first, len(days), windows, protocol.hash_file(data))
                    pilot.write_json(packet / "task.json", task)
                    gold = expected(data, task, truth)
                    claimed = execute(packet, "evidence-aware")["predictions"]
                    actual = pilot.transitions(claimed, "decision")
                    self.assertEqual(actual, pilot.transitions(gold, "decision"))
                    self.assertEqual(len(actual), 1)
                    if replica == 0:
                        self.assertEqual(claimed["relationship"]["window_2"]["decision"], "inconclusive")
                    else:
                        self.assertNotEqual(claimed["relationship"]["window_2"]["decision"], "inconclusive")

    def test_failed_execution_and_always_abstaining_do_not_pass_gates(self):
        data = {"strata": {f: {"correct": n, "submitted_change": 12 if f == "weight_gap" else 0,
                               "submitted_transition_cases": 0} for f, n in CASE_COUNTS.items()},
                "reassessment": {"wrong_windows": 0, "extra_qualified": 0}}
        counts = {f: {"correct": n if f in {"weight_threshold", "weight_gap"} else 0,
                      "submitted_change": 0, "submitted_transition_cases": 0} for f, n in CASE_COUNTS.items()}
        abstain = {"strata": counts, "reassessment": data["reassessment"]}
        gate = verification.gates(data, abstain, [{"statuses": {"completed": 119, "timeout": 1},
                                                   "replays": 8, "matched": 8}])
        self.assertFalse(gate["weight_guardrails"])
        self.assertFalse(gate["exact_reassessment"])
        self.assertFalse(gate["execution_and_replay"])
