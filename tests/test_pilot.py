import io
import json
import math
import sys
from datetime import date, timedelta

from test_contract import ROOT, TemporaryCase

sys.path[:0] = [str(ROOT / "benchmark"), str(ROOT / "benchmark/isolated")]

import pilot
import protocol
from pilot_design import LABELS
from runner import GuestProgress, boot_arguments, boot_observations, result_submission, vm
from weight_break import detect
from wire import READY, RESULT_START, capture, frame, receive


class PilotTests(TemporaryCase):
    def test_inconclusive_window_can_separate_a_decisive_reassessment(self):
        truths = ("notSupported", "inconclusive", "supported")
        case = {"relationship": {key: {"expected": label, "effective_decision": label}
                                 for key, label in zip(protocol.WINDOWS, truths, strict=True)}}
        target = {(("window_1", "notSupported"), ("window_3", "supported"))}
        self.assertEqual(pilot.transitions(case, "expected"), target)
        self.assertEqual(pilot.transitions(case, "effective_decision"), target)
        case["relationship"]["window_2"]["effective_decision"] = "supported"
        self.assertNotEqual(pilot.transitions(case, "effective_decision"), target)

    def test_development_cases_reproduce_and_keep_truth_private(self):
        first, second = self.job / "first", self.job / "second"
        self.assertEqual(pilot.prepare(first, development=True)["cases"], 12)
        self.assertEqual(pilot.prepare(second, development=True)["cases"], 12)
        for (task, database, truth), (other, twin, reference) in zip(pilot.load(first), pilot.load(second), strict=True):
            self.assertEqual(task, other)
            self.assertEqual(database.read_bytes(), twin.read_bytes())
            self.assertEqual(truth, reference)
            self.assertEqual({p.name for p in database.parent.iterdir()}, {"task.json", "records.sqlite"})
            self.assertNotIn(truth["latent"]["family"], (database.parent / "task.json").read_text())
        audit = pilot.audit(first)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["windows"], 36)
        self.assertEqual(audit["reassessment_targets"], dict.fromkeys(pilot.REASSESSMENT_DIRECTIONS, 1))
        for bins in audit["distributions"].values():
            for values in bins:
                self.assertEqual(set(values), set(LABELS))

    def test_valid_abstention_gets_credit_for_insufficient_weight(self):
        workspace = self.job / "development"
        pilot.prepare(workspace, development=True)
        task, data, truth = next(case for case in pilot.load(workspace)
                                 if case[2]["expected"]["weight_decision"] == "inconclusive")
        value = pilot.abstain(task)
        case = pilot.scoring.score_case(data, task, truth["expected"], value)
        self.assertTrue(case["change"]["correct"])
        self.assertEqual(case["change"]["expected"], "inconclusive")

    def test_both_reassessment_directions_have_record_support_across_seeds(self):
        from pilot_design import expected, make_case, task_record
        from synthetic_storage import build_records

        for seed in (bytes(32), bytes(range(32))):
            counts = dict.fromkeys(pilot.REASSESSMENT_DIRECTIONS, 0)
            for replica in range(8):
                identifier, first, days, windows, latent = make_case(seed, "changing", replica)
                folder = self.job / identifier
                folder.mkdir()
                database = folder / "records.sqlite"
                build_records(database, days)
                task = task_record(identifier, first, len(days), windows, protocol.hash_file(database))
                for before, after in pilot.transitions(expected(database, task, latent), "decision"):
                    counts[before[1] + "_to_" + after[1]] += 1
            self.assertEqual(counts, dict.fromkeys(pilot.REASSESSMENT_DIRECTIONS, 4))


class WeightTests(TemporaryCase):
    def evaluate(self, drift, step, *, gap=False, span=240):
        origin = date(2025, 1, 1)
        points = []
        for day in range(span):
            if day % 7 == 3 or (gap and 85 <= day < 155):
                continue
            when = (origin + timedelta(days=day)).isoformat()
            points.append({"day": when, "value": 78 + drift * day / span + (step if day >= 120 else 0)
                           + 0.18 * math.sin(day * 0.71),
                           "references": [{"table": "daily_snapshot", "row_id": day + 1, "column": "body_weight"}]})
        return detect(points, origin.isoformat(), (origin + timedelta(days=span)).isoformat())

    def test_smooth_drift_and_subthreshold_steps_are_controls(self):
        for drift in (-3.0, 0, 3.0):
            for step in (0, 0.55):
                with self.subTest(drift=drift, step=step):
                    self.assertEqual(self.evaluate(drift, step)["decision"], "no_change")
        self.assertEqual(self.evaluate(0, 0.95)["decision"], "inconclusive")

    def test_both_signs_of_step_are_recovered_in_the_presence_of_drift(self):
        for drift, step in ((3.0, -2.5), (-3.0, 2.5)):
            with self.subTest(drift=drift, step=step):
                result = self.evaluate(drift, step)
                self.assertEqual(result["decision"], "change")
                self.assertAlmostEqual(result["effect"], step, delta=0.15)
                self.assertLessEqual(abs((protocol.civil(result["split"]) - date(2025, 5, 1)).days), 1)
                self.assertEqual(len(result["references"]), 4)

    def test_hidden_steps_and_too_short_windows_abstain(self):
        self.assertEqual(self.evaluate(0, 2.5, gap=True)["decision"], "inconclusive")
        self.assertEqual(self.evaluate(0, 0, span=60)["decision"], "inconclusive")


class SupervisorTests(TemporaryCase):
    def test_direct_boot_uses_only_validated_boot_arguments(self):
        boot = {"root_partuuid": "abcd1234-abcd-abcd-abcd-123456abcdef", "kernel": "/trusted/Image", "initrd": None}
        self.assertEqual(boot_arguments(boot), ["-kernel", "/trusted/Image", "-append",
                         "root=PARTUUID=abcd1234-abcd-abcd-abcd-123456abcdef ro rootwait console=ttyAMA0,115200"])
        boot["initrd"] = "/trusted/initrd"
        self.assertEqual(boot_arguments(boot)[-2:], ["-initrd", "/trusted/initrd"])
        boot["root_partuuid"] += " init=/bin/sh"
        with self.assertRaises(ValueError):
            boot_arguments(boot)
        with self.assertRaises(ValueError):
            vm(None, None, None, b"")

    def test_boot_diagnostics_keep_markers_and_fault_class_only(self):
        observation = boot_observations(b"Linux version 6\nRun /sbin/init as init process\n"
                                        b"TYR_BOOT_DEVICES_READY\nTYR_BOOT_RUNTIME_READY\nother text\n")
        self.assertEqual(observation, {"boot_milestones": ["kernel", "linux_init", "devices", "runtime"],
                                       "boot_fault": None})
        self.assertEqual(boot_observations(b"UEFI firmware\nSynchronous Exception\n"),
                         {"boot_milestones": ["firmware"], "boot_fault": "firmware_exception"})

    def test_serial_milestones_select_independent_deadlines(self):
        progress = GuestProgress()
        payload = RESULT_START + frame({"status": "completed"}, [b"x", b""])
        self.assertEqual(progress.deadline(b"", 2), 35)
        self.assertEqual(progress.stage, "boot_readiness")
        self.assertEqual(progress.deadline(READY, 5), 120)
        self.assertEqual(progress.stage, "guest_execution")
        self.assertEqual(progress.deadline(READY + payload[:-1], 10), 18)
        self.assertEqual(progress.stage, "result_delivery")
        self.assertEqual(progress.deadline(READY + payload, 11), 21)
        self.assertEqual(progress.stage, "shutdown")
        self.assertEqual(progress.telemetry(), {"ready_milliseconds": 5000, "result_start_milliseconds": 10000,
                                                "result_complete_milliseconds": 11000})

    def test_capture_honors_the_selected_phase_deadline(self):
        progress = GuestProgress()
        marker = READY + RESULT_START
        command = [sys.executable, "-c", f"import sys,time; sys.stdout.buffer.write({marker!r}); "
                                        "sys.stdout.buffer.flush(); time.sleep(10)"]
        status, code, output, _, elapsed = capture(command, 5, (100, 10),
                                                   deadline=lambda data, t: min(progress.deadline(data, t),
                                                                                0.3 if data else 4))
        self.assertEqual(status, "timeout")
        self.assertLess(code, 0)
        self.assertEqual(output, marker)
        self.assertLess(elapsed, 2000)
        self.assertEqual(progress.stage, "result_delivery")

    def test_result_framing_rejects_excess_and_truncated_parts(self):
        blob = frame({"status": "completed"}, [b"sample", b""])
        self.assertEqual(receive(io.BytesIO(blob), (6, 0)), ({"status": "completed"}, [b"sample", b""]))
        with self.assertRaises(ValueError):
            receive(io.BytesIO(blob), (5, 0))
        with self.assertRaises(ValueError):
            receive(io.BytesIO(blob[:-1]), (6, 0))

    def test_process_supervisor_enforces_timeout_and_output_caps(self):
        self.assertEqual(capture([sys.executable, "-c", "print('x'*1000)"], 5, (99, 10))[0], "output_limit")
        self.assertEqual(capture([sys.executable, "-c", "import time; time.sleep(10)"], 0.2, (10, 10))[0], "timeout")

    def test_supervisor_rejects_wrong_case_and_agent_reported_provider(self):
        task = {"case_id": "0" * 32}
        normal = pilot.abstain(task)
        self.assertEqual(result_submission(task, {"status": "completed"}, protocol.canonical(normal)), normal)
        state = {"status": "completed"}
        normal["predictions"]["case_id"] = "1" * 32
        self.assertIsNone(result_submission(task, state, json.dumps(normal)))
        self.assertEqual(state["status"], "invalid_submission")
        normal["predictions"]["case_id"] = task["case_id"]
        normal["provider"] = {}
        self.assertIsNone(result_submission(task, {"status": "completed"}, protocol.canonical(normal)))
