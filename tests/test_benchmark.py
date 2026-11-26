import copy
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from test_contract import ROOT, TemporaryCase, create_empty

sys.path.insert(0, str(ROOT / "benchmark"))
import bench
import protocol
import providers
import scoring
from prepare import prepare
from worker import execute

MASTER = "15" * 32


def response(text="fixture mock result", input_tokens=12, output_tokens=6):
    return {"status": "completed", "model": "mock-response-test",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}


class ProviderTests(TemporaryCase):
    def client(self, payloads, policy=None, name="ledger.sqlite"):
        mock = providers.MockTransport(payloads)
        return providers.Client(self.job / name, policy or providers.Policy(), providers.ResponsesAdapter(), mock), mock

    def test_dry_run_opt_ins_and_budget_check_do_not_dispatch(self):
        client, mock = self.client([response()], providers.Policy(max_total_tokens=1))
        plan = client.call("mock-response-test", {"x": "fiction"}, dry_run=True)
        self.assertFalse(plan["fits_per_experiment_limit"])
        self.assertFalse(client.path.exists())
        with self.assertRaises(providers.BudgetExceeded):
            client.call("mock-response-test", {"x": "fiction"})
        with self.assertRaisesRegex(ValueError, "Billable"):
            client.call("mock-response-test", {}, billable=True)
        with self.assertRaisesRegex(ValueError, "separate authorization"):
            client.call("mock-response-test", {}, data_class="personal")
        self.assertEqual(mock.requests, [])
        self.assertEqual(client.accounting()["actual_api_calls"], 0)

    def test_cost_reservation_and_cache_stay_with_experiment(self):
        common = dict(allow_paid=True, max_output_tokens=120, input_microusd_per_million=5_000_000,
                      output_microusd_per_million=10_000_000)
        draft, _ = self.client([], providers.Policy(**common))
        maximum = draft.call("mock-response-test", {"first": 1}, billable=True, dry_run=True)["reserved_cost_microusd"]
        policy = providers.Policy(**common, max_cost_microusd=maximum)
        client, mock = self.client([response()], policy)
        done = client.call("mock-response-test", {"first": 1}, billable=True)
        self.assertEqual(done["simulated_cost_microusd"], 120)
        self.assertEqual(done["actual_cost_microusd"], 0)
        self.assertEqual(mock.requests[0]["store"], False)
        self.assertEqual(mock.requests[0]["max_output_tokens"], 120)
        resumed, fresh_transport = self.client([], policy)
        again = resumed.call("mock-response-test", {"first": 1}, billable=True)
        self.assertTrue(again["cached"])
        self.assertEqual(again["request_id"], done["request_id"])
        with self.assertRaises(providers.BudgetExceeded):
            resumed.call("mock-response-test", {"other": 2}, billable=True)
        self.assertEqual(fresh_transport.requests, [])
        self.assertEqual(resumed.accounting()["attempts"], 1)

    def test_retry_requires_unsent_proof_and_counts_toward_limit(self):
        client, mock = self.client([providers.UnsentRetryable("test"), response()])
        result = client.call("mock-response-test", {"example": 1})
        self.assertFalse(result["cached"])
        self.assertEqual(len(mock.requests), 2)
        self.assertEqual(client.accounting()["attempts"], 2)
        limited, other = self.client([providers.UnsentRetryable("test"), response()],
                                     providers.Policy(max_attempts=1), name="limited.sqlite")
        with self.assertRaises(providers.BudgetExceeded):
            limited.call("mock-response-test", {"example": 2})
        self.assertEqual(len(other.requests), 1)

    def test_ambiguous_attempt_and_bad_usage_remain_reserved(self):
        for label, outcome in (("uncertain", RuntimeError("mock timeout")), ("usage", response(output_tokens=50_000))):
            client, mock = self.client([outcome], name=f"{label}.sqlite")
            with self.assertRaises(providers.AmbiguousRequest):
                client.call("mock-response-test", {"fixture": 1})
            with self.assertRaises(providers.AmbiguousRequest):
                client.call("mock-response-test", {"fixture": 1})
            self.assertEqual(len(mock.requests), 1)
            self.assertEqual(client.accounting()["completed"], 0)
            self.assertGreater(client.accounting()["accounted_tokens"], 0)

    def test_local_adapter_uses_the_same_guard_and_ledger(self):
        mock = providers.MockTransport([{"model": "mock-local", "text": "fixture local result",
                                         "prompt_tokens": 13, "generated_tokens": 9}])
        client = providers.Client(self.job / "local.sqlite", providers.Policy(), providers.LocalAdapter(), mock)
        answer = client.call("mock-local", {"fixture": 1})
        self.assertEqual(answer["text"], "fixture local result")
        self.assertEqual(answer["input_tokens"], 13)
        self.assertIn("max_new_tokens", mock.requests[0])

    def test_cannot_open_an_observation_database_as_a_ledger(self):
        path = self.job / "records.sqlite"
        create_empty("records", path)
        before = protocol.hash_file(path)
        client, mock = self.client([response()], name=path.name)
        with self.assertRaisesRegex(ValueError, "outside the provider-ledger"):
            client.call("mock-response-test", {"fixture": 1})
        self.assertEqual(mock.requests, [])
        self.assertEqual(protocol.hash_file(path), before)


class BenchmarkTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.agent = self.job / "agent"
        self.evaluator = self.job / "evaluator"
        self.prepared = prepare(self.agent, self.evaluator, replicates=1, master_seed=MASTER)

    def test_held_out_inputs_are_deterministic_and_have_no_truth_members(self):
        twin = self.job / "repeat-agent"
        twin_truth = self.job / "repeat-evaluator"
        self.assertEqual(prepare(twin, twin_truth, 1, MASTER), self.prepared)
        windows = []
        for case in self.prepared["cases"]:
            packet = self.agent / case
            task, records = protocol.read_packet(packet)
            windows.append((task["relationship"], task["change"]))
            self.assertEqual(records.read_bytes(), (twin / case / "records.sqlite").read_bytes())
            self.assertEqual(sorted(p.name for p in packet.iterdir()), ["records.sqlite", "task.json"])
            self.assertNotIn("master_seed", (packet / "task.json").read_text())
            self.assertNotIn("truth", (packet / "task.json").read_text())
            self.assertTrue((self.evaluator / case / "truth.json").exists())
        self.assertTrue(all(value == windows[0] for value in windows))
        kit = self.job / "kit"
        bench.detached_worker_files(kit)
        self.assertEqual({path.relative_to(kit).as_posix() for path in kit.rglob("*") if path.is_file()},
                         set(bench.WORKER_FILES))
        self.assertFalse((kit / "scenarios").exists())
        self.assertFalse((kit / "benchmark/scoring.py").exists())

    def test_worker_scope_blocks_truth_reads_and_sqlite_write_access(self):
        packet = self.agent / self.prepared["cases"][0]
        script = r'''
from pathlib import Path
import socket, sqlite3, sys
sys.path.insert(0, sys.argv[1])
from worker import _confine
packet, truth = (Path(arg) for arg in sys.argv[2:])
_confine(packet, None)
for action in (
    lambda: truth.read_bytes(),
    lambda: sqlite3.connect((packet / "records.sqlite").as_uri() + "?mode=rw", uri=True),
    lambda: socket.socket(),
):
    try: action()
    except PermissionError: pass
    else: raise AssertionError("scope violation")
assert (packet / "task.json").read_bytes()
with sqlite3.connect((packet / "records.sqlite").as_uri() + "?mode=ro", uri=True) as db:
    assert db.execute("SELECT count(*) FROM user").fetchone() == (1,)
'''
        result = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "benchmark"),
                                 str(packet), str(self.evaluator / "index.json")],
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, "")

    def test_offline_runs_score_uncertainty_reassessment_and_replay(self):
        first, second = self.job / "first", self.job / "second"
        bench.run_offline(self.agent, first, "deterministic")
        bench.run_offline(self.agent, second, "deterministic")
        report = bench.score(self.agent, self.evaluator, first, replay=second)
        self.assertEqual(report["scoring_version"], 2)
        result = report["summary"]
        self.assertEqual(result["relationship"]["targets"], 12)
        self.assertGreater(result["relationship"]["correct_abstentions"], 0)
        self.assertGreater(result["relationship"]["recovered_positive_windows"], 0)
        self.assertEqual(result["baseline_change"]["targets"], 1)
        self.assertEqual(result["reassessment"]["change_targets"], 1)
        self.assertEqual(result["reproducibility"], {"checked": 4, "matching_predictions": 4})
        self.assertEqual(result["compute"]["actual_api_calls"], 0)

    def test_mock_workers_have_usage_and_no_actual_charges(self):
        for mode in ("mock-openai", "mock-local"):
            with self.subTest(mode=mode):
                output = self.job / mode
                bench.run_offline(self.agent, output, mode)
                score = bench.score(self.agent, self.evaluator, output)["summary"]
                self.assertEqual(score["relationship"]["abstentions"], 12)
                self.assertEqual(score["compute"]["actual_api_calls"], 0)
                self.assertEqual(score["compute"]["actual_cost_microusd"], 0)
                usage, = score["compute"]["usage_by_model"].values()
                self.assertGreater(usage["input_tokens"], 0)
                self.assertEqual(score["relationship"]["recovered_positive_windows"], 0)

    def test_scorer_flags_unsupported_causality_and_false_evidence(self):
        identifier = self.prepared["cases"][0]
        packet = self.agent / identifier
        task, source = protocol.read_packet(packet)
        index = protocol.read_json(self.evaluator / "index.json")
        value = execute(packet, "deterministic")
        value["predictions"]["relationship"]["window_1"].update(
            claim_type="causal", decision="supported", effect=-12,
            references=[{"table": "daily_sleep", "row_id": 999_999, "column": "total_minutes"}],
        )
        result = scoring.score_case(source, task, index["cases"][identifier]["expected"], scoring.submission(value, task))
        row = result["relationship"]["window_1"]
        self.assertEqual(row["effective_decision"], "invalid_causal")
        self.assertEqual(row["evidence"]["invalid_references"], 1)
        self.assertFalse(row["correct"])
        with self.assertRaisesRegex(ValueError, "Exactly one decision"):
            value["predictions"]["relationship"]["extra"] = {}
            scoring.submission(value, task)

    def test_decisive_scores_require_effect_thresholds_and_traceable_references(self):
        index = protocol.read_json(self.evaluator / "index.json")
        identifier = next(item["case_id"] for item in index["designs"] if item["scenario"] == "changing")
        packet = self.agent / identifier
        task, source = protocol.read_packet(packet)
        expected = index["cases"][identifier]["expected"]
        original = execute(packet, "deterministic")

        def evaluate(value):
            case = scoring.score_case(source, task, expected, scoring.submission(value, task))
            return case, scoring.aggregate([case], [], [value])

        matching = copy.deepcopy(original)
        early = matching["predictions"]["relationship"]["window_1"]
        late = matching["predictions"]["relationship"]["window_2"]
        change = matching["predictions"]["change"]
        early["effect"] = -15
        late["effect"] = -14.999999
        change["effect"] = 1 if change["effect"] > 0 else -1
        case, summary = evaluate(matching)
        self.assertTrue(case["relationship"]["window_1"]["correct"])
        self.assertTrue(case["relationship"]["window_2"]["correct"])
        self.assertTrue(case["change"]["correct"])
        self.assertEqual(summary["reassessment"]["recovered_changes"], 1)

        unknown_sleep = {"table": "daily_sleep", "row_id": 999_999, "column": "total_minutes"}
        cases = (
            ("window_1", {"effect": 10}, "invalid_effect"),
            ("window_1", {"effect": -14.999999}, "invalid_effect"),
            ("window_1", {"references": []}, "invalid_evidence"),
            ("window_1", {"references": early["references"][:2]}, "invalid_evidence"),
            ("window_1", {"references": [*early["references"], unknown_sleep]}, "invalid_evidence"),
            ("window_2", {"effect": -15}, "invalid_effect"),
            ("window_2", {"references": early["references"]}, "invalid_evidence"),
            ("change", {"effect": change["effect"] * 0.01}, "invalid_effect"),
            ("change", {"references": []}, "invalid_evidence"),
            ("change", {"references": change["references"][:1]}, "invalid_evidence"),
        )
        for target, overrides, reason in cases:
            with self.subTest(target=target, overrides=overrides):
                value = copy.deepcopy(matching)
                if target == "change":
                    value["predictions"]["change"].update(overrides)
                else:
                    value["predictions"]["relationship"][target].update(overrides)
                case, summary = evaluate(value)
                result = case["change"] if target == "change" else case["relationship"][target]
                self.assertEqual(result["effective_decision"], reason)
                self.assertFalse(result["correct"])
                if target == "change":
                    self.assertEqual(summary["baseline_change"]["detected"], 0)
                else:
                    self.assertEqual(summary["reassessment"]["recovered_changes"], 0)
                    if target == "window_1":
                        self.assertEqual(summary["relationship"]["recovered_positive_windows"], 0)

    def test_unqualified_null_claims_still_count_as_submitted_false_positives(self):
        index = protocol.read_json(self.evaluator / "index.json")
        identifier = next(item["case_id"] for item in index["designs"] if item["scenario"] == "stable")
        packet = self.agent / identifier
        task, source = protocol.read_packet(packet)
        expected = index["cases"][identifier]["expected"]
        value = execute(packet, "deterministic")
        value["predictions"]["relationship"]["window_1"].update(decision="supported", effect=-15, references=[])
        value["predictions"]["change"].update(decision="change", split=task["relationship"][0]["end"], effect=1,
                                               references=[])
        case = scoring.score_case(source, task, expected, scoring.submission(value, task))
        summary = scoring.aggregate([case], [], [value])
        self.assertEqual(summary["relationship"]["false_positives"], 0)
        self.assertEqual(summary["relationship"]["submitted_false_positives"], 1)
        self.assertEqual(summary["baseline_change"]["false_alarms"], 0)
        self.assertEqual(summary["baseline_change"]["submitted_false_alarms"], 1)
        self.assertEqual(summary["invalid_evidence_claims"], 2)

    def test_truth_packaging_and_task_tamper_are_rejected(self):
        identifier = self.prepared["cases"][0]
        packet = self.agent / identifier
        extra = packet / "truth.json"
        extra.write_bytes((self.evaluator / identifier / "truth.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "only records.sqlite"):
            protocol.read_packet(packet)
        extra.unlink()
        output = self.job / "submissions"
        bench.run_offline(self.agent, output, "deterministic")
        task_path = packet / "task.json"
        task_path.chmod(0o600)
        task = protocol.read_json(task_path)
        task["relationship"][0]["end"] = "2025-04-18"
        task_path.write_text(json.dumps(task))
        with self.assertRaisesRegex(ValueError, "private evaluator binding"):
            bench.score(self.agent, self.evaluator, output)


if __name__ == "__main__":
    unittest.main()
