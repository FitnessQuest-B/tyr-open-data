"""Phase 4A tests. SDK contract checks use an in-process mock HTTP transport."""

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark/research"))
import run as research
import smoke as live_smoke
import batch
from budget import BATCH_LIMITS, BudgetBlocked, Ledger, Limits, SMOKE_LIMITS, reservation
from observations import Observations, InvalidResult, public_panel
from providers import MockTransport
from responses import PILOT, SDKTransport, _prediction_schema, open_sdk_transport
from sleep_evidence import (
    ACROSS_WINDOW_METHOD, ENDPOINT_METHOD, STABILITY_PACKET_VERSION, ReassessmentObservations,
    TOOL_NAME, TOOL_TARGET, _comparability, _stability, _threshold_cluster, recommended_tool,
    required_abstention, routing_guidance, sleep_decision_basis, sleep_estimates, summaries,
)
from sleep_only import SleepOnly, deterministic_prediction
from sleep_local import ESTIMATE_METHOD, WithinPeriodSleep

ADAPTER = research.ADAPTER
mock_response = research.mock_response


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        packets = stack.enter_context(public_panel())
        cls.packets = packets[0].parent
        order = [path.name for path in packets]
        cases = {}
        for path in packets:
            obs = Observations(path)
            cases[path.name] = {"task_sha256": research.protocol.digest(obs.task),
                                "source_sha256": obs.task["source_sha256"],
                                "observation_sha256": research.protocol.digest(obs.packet)}
        cls.manifest = {"public_only": True, "status": "proposed", "baseline_commit": batch.BASELINE_COMMIT,
                        "ordered_cases": order, "cases": cases, "provenance": research.provenance()}
        stack.enter_context(patch.object(batch, "APPROVED_MANIFEST_SHA256", research.protocol.digest(cls.manifest)))

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_text(research.protocol.canonical(self.manifest) + "\n")

    def test_admission_rejects_manifest_changes_before_loading_observations(self):
        changed = {**self.manifest, "public_only": False, "labels": {"example": "inconclusive"}}
        self.manifest_path.write_text(research.protocol.canonical(changed) + "\n")
        with patch("batch.Observations") as loader:
            with self.assertRaisesRegex(ValueError, "reviewed public batch"):
                batch.run_batch(self.manifest_path, self.packets, self.root / "results")
            loader.assert_not_called()
        self.assertFalse((self.root / "results").exists())

    def test_admission_rejects_changes_to_the_frozen_observation_code(self):
        current = research.provenance()
        current["files"]["benchmark/research/observations.py"] = "0" * 64
        with patch("batch.broker.provenance", return_value=current), patch("batch.Observations") as loader:
            with self.assertRaisesRegex(ValueError, "observation code changed"):
                batch.run_batch(self.manifest_path, self.packets, self.root / "results")
            loader.assert_not_called()
        self.assertFalse((self.root / "results").exists())

    def test_admission_rejects_extra_files_modified_bytes_and_symlinks(self):
        copy = self.root / "copy"
        shutil.copytree(self.packets, copy)
        case = self.manifest["ordered_cases"][0]
        extra = copy / case / "labels.json"
        extra.write_text("{}")
        with self.assertRaisesRegex(ValueError, "only the approved task and records"):
            batch.run_batch(self.manifest_path, copy, self.root / "results")
        extra.unlink()
        database = copy / case / "records.sqlite"
        database.chmod(0o600)
        with database.open("ab") as stream:
            stream.write(b"tampered")
        with patch("batch.Observations") as loader:
            with self.assertRaisesRegex(ValueError, "fingerprint differs"):
                batch.run_batch(self.manifest_path, copy, self.root / "results")
            loader.assert_not_called()
        database.unlink()
        database.symlink_to(self.packets / case / "records.sqlite")
        with self.assertRaises(OSError):
            batch.run_batch(self.manifest_path, copy, self.root / "results")
        self.assertFalse((self.root / "results").exists())

    def test_tool_and_skip_both_get_the_full_final_answer_budget(self):
        transports = {}

        def factory(arm, index):
            transports[arm, index] = batch._mock_transport(arm, index)
            return transports[arm, index]

        report = batch.run_batch(self.manifest_path, self.packets, self.root / "results", mock_transport=factory)
        self.assertEqual(report["status_counts"], {"completed": 24})
        self.assertEqual(report["stage_status_counts"], {"completed": 16, "skip": 4, "tool": 4})
        self.assertEqual(len(report["attempts"]), report["request_limit"])
        self.assertEqual(report["actual_api_calls"], report["max_retries"], 0)
        for index in range(8):
            b, = transports["B", index].requests
            selection, final = transports["C", index].requests
            self.assertEqual([b["max_output_tokens"], selection["max_output_tokens"], final["max_output_tokens"]],
                             [3900, 512, 3900])
            self.assertEqual(selection["tool_choice"], "auto")
            self.assertEqual(selection["text"]["format"]["name"], "tyr_tool_selection_v1")
            self.assertNotIn("tools", b)
            self.assertNotIn("tools", final)
            self.assertEqual(set(json.loads(b["input"])), {"observation_packet"})
            self.assertEqual(set(json.loads(selection["input"])), {"observation_packet"})
            if index % 2:
                self.assertEqual(b, final)
            else:
                self.assertEqual(set(json.loads(final["input"])), {"observation_packet", "executed_tool"})
            self.assertEqual(json.loads(b["input"])["observation_packet"],
                             json.loads(selection["input"])["observation_packet"])
        with self.assertRaises(FileExistsError):
            batch.run_batch(self.manifest_path, self.packets, self.root / "results",
                            mock_transport=lambda *args: self.fail("A finished workspace dispatched again"))

    def test_bad_skip_cannot_open_the_final_stage(self):
        unexpected = mock_response(prediction={"action": "skip", "expected": "inconclusive"})
        unexpected["usage"].update(output_tokens=100, total_tokens=6100)
        unexpected["usage"]["output_tokens_details"]["reasoning_tokens"] = 40

        def factory(arm, index):
            return MockTransport([unexpected]) if (arm, index) == ("C", 0) else batch._mock_transport(arm, index)

        report = batch.run_batch(self.manifest_path, self.packets, self.root / "results", mock_transport=factory)
        self.assertEqual(len(report["attempts"]), 23)
        self.assertEqual(report["stage_status_counts"]["invalid_tool_selection"], 1)
        self.assertEqual(report["stage_status_counts"]["not_run_selection_failed"], 1)

    def test_offline_remediation_shares_the_packet_and_admits_one_three_window_call(self):
        transports = {}

        def factory(arm, index):
            transports[arm, index] = batch._mock_transport(arm, index, remediation=True)
            return transports[arm, index]

        result = batch.run_batch(self.manifest_path, self.packets, self.root / "results",
                                 mock_transport=factory, remediation=True)
        self.assertEqual(result["status_counts"], {"completed": 24})
        self.assertEqual(len(result["attempts"]), 24)
        self.assertEqual(result["stage_status_counts"], {"completed": 16, "tool": 6, "skip": 2})
        self.assertEqual(result["actual_api_calls"], 0)
        scope = result["offline_remediation"]
        self.assertEqual(scope["packet_version"], "observation-packet-v3")
        for index, identity in enumerate(self.manifest["ordered_cases"]):
            b, = transports["B", index].requests
            select, c = transports["C", index].requests
            self.assertEqual(b["input"], select["input"])
            packet = json.loads(b["input"])["observation_packet"]
            self.assertEqual(set(packet["sleep_summary"]["windows"]), set(research.protocol.WINDOWS))
            self.assertEqual(research.protocol.digest(packet), scope["observation_sha256"][identity])
            self.assertIn("Skip an inconclusive middle window", b["instructions"])
            self.assertIn("Prioritize", select["instructions"])
            tool = next(spec for spec in select["tools"] if spec["name"] == TOOL_NAME)
            self.assertEqual(tool["parameters"]["properties"]["target"]["enum"], [TOOL_TARGET])
            self.assertNotIn("tools", c)
            if index < 4:
                execution = json.loads(c["input"])["executed_tool"]
                self.assertEqual(execution["operation"], TOOL_NAME)
                self.assertEqual(set(execution["windows"]), set(research.protocol.WINDOWS))
                self.assertTrue(all(len(w["fixed_thirds"]) == 3 for w in execution["windows"].values()))
            elif index % 2:
                self.assertEqual(b, c)

    def test_remediation_rejects_live_transport_wrong_tool_target_and_extra_arguments(self):
        with self.assertRaisesRegex(PermissionError, "offline"):
            batch.run_batch(self.manifest_path, self.packets, self.root / "results",
                            live_transport=SDKTransport(None), remediation=True)
        valid = mock_response(target=TOOL_TARGET, operation=TOOL_NAME)
        with self.assertRaisesRegex(InvalidResult, "invalid_tool"):
            ADAPTER.output(valid, offer_tool=True, selection_only=True)
        wrong = mock_response(target="window_2", operation=TOOL_NAME)
        with self.assertRaisesRegex(InvalidResult, "invalid_tool"):
            ADAPTER.output(wrong, offer_tool=True, selection_only=True, allow_reassessment=True)
        valid["output"][0]["arguments"] = research.protocol.canonical({"target": TOOL_TARGET, "path": "elsewhere"})
        with self.assertRaisesRegex(InvalidResult, "invalid_tool"):
            ADAPTER.output(valid, offer_tool=True, selection_only=True, allow_reassessment=True)

    def test_stability_gate_requires_support_spread_and_agreement(self):
        def classify(raw, matched, count=10):
            thirds = [{"earlier_count": count, "later_count": 10, "late_minus_earlier_minutes": r,
                       "matched": {"late_minus_earlier_minutes": m}} for r, m in zip(raw, matched, strict=True)]
            with patch("sleep_evidence._thirds", return_value=thirds):
                result = _stability([], None, None, [])
                return result["result"] or result["reason"]

        for values in ((1, -36, -39), (-38, -35, -1)):
            self.assertEqual(classify(values, values), "mixed")
        self.assertEqual(classify((-18, -18, -6), (-18, -18, -6)), "mixed")
        self.assertEqual(classify((-18, -17, -7), (-18, -17, -7)), "no_mixing_detected")
        self.assertEqual(classify((-40, -26, -12.01), (-40, -26, -12.01)), "no_mixing_detected")
        self.assertEqual(classify((-16.866667, -4.1875, -5.196429), (-17.096296, -2.07672, -5.984127)),
                         "no_mixing_detected")
        self.assertEqual(classify((-20, -8, -5), (-17.99, -8, -5)), "no_mixing_detected")
        self.assertEqual(classify((1, -36, -39), (-32, -36, -39)), "no_mixing_detected")
        self.assertEqual(classify((1, -36, -39), (None, -36, -39)), "third_matched_overlap")
        self.assertEqual(classify((1, -36, -39), (1, -36, -39), count=9), "third_pair_count")
        self.assertEqual(_stability(["paired_coverage"], None, None, []),
                         {"availability": "unavailable", "reason": "whole_window_coverage", "result": None})

    def test_missing_thirds_do_not_require_abstention_with_whole_window_support(self):
        packet = {"version": STABILITY_PACKET_VERSION,
                  "sleep_summary": {"windows": {}, "clustered_threshold_windows": []}}
        for target, check, result, available in (
            ("window_1", "pass", None, "unavailable"),
            ("window_2", "pass", "mixed", "available"),
            ("window_3", "fail", None, "unavailable"),
        ):
            packet["sleep_summary"]["windows"][target] = {
                "endpoint_support": {"coverage_check": check},
                "stability_screen": {"availability": available, "result": result},
            }
        self.assertFalse(required_abstention(packet, "window_1"))
        self.assertTrue(required_abstention(packet, "window_2"))
        self.assertTrue(required_abstention(packet, "window_3"))

    def test_threshold_cluster_preserves_an_endpoint_next_to_clear_evidence(self):
        def windows(*effects):
            return {key: {"endpoint_support": {"coverage_check": "pass",
                                               "matched": {"late_minus_earlier_minutes": effect}},
                          "stability_screen": {"result": None}}
                    for key, effect in zip(research.protocol.WINDOWS, effects)}

        self.assertEqual(_threshold_cluster(windows(-16.8, -12.7, -14.1)), list(research.protocol.WINDOWS))
        self.assertEqual(_threshold_cluster(windows(-18, -12, -15)), list(research.protocol.WINDOWS))
        self.assertEqual(_threshold_cluster(windows(-16, -12.5, -36)), [])
        self.assertEqual(_threshold_cluster(windows(-16)), [])

    def test_comparability_routes_one_tool_and_prioritizes_sleep_on_competing_cues(self):
        windows = {}
        groups = {}
        for key, training in (("window_1", 5), ("window_2", 0), ("window_3", 0)):
            count = 10 + training
            windows[key] = {
                "paired_days": 2 * count, "endpoint_support": {
                    "coverage_check": "pass", "matched": {"earlier_count": count, "later_count": count}},
                "stability_screen": {"result": "no_mixing_detected"},
            }
            groups[key] = {"quiet_weekday": [[0] * 10, [0] * 10]}
            if training:
                groups[key]["training_weekday"] = [[0] * training, [0] * training]
        comparison = _comparability(windows, groups)
        cue = comparison["windows"]["window_1"]
        self.assertEqual(cue["removed_local_strata"], ["training_weekday"])
        self.assertEqual(cue["local_matched_pairs"], 30)
        self.assertTrue(cue["material_support_change"])
        self.assertFalse(comparison["windows"]["window_2"]["material_support_change"])
        packet = {"version": STABILITY_PACKET_VERSION, "witnesses": dict.fromkeys(windows, {}),
                  "sleep_summary": {"windows": windows, "clustered_threshold_windows": [],
                                    "cross_window_comparability": comparison},
                  "weight_summary": {"decision": "change", "effect": 2.0}}
        packet["tool_routing"] = routing_guidance(packet)
        self.assertEqual(packet["tool_routing"]["sleep_review_windows"], ["window_1"])
        self.assertEqual(recommended_tool(packet), (TOOL_NAME, TOOL_TARGET))
        packet["weight_summary"]["effect"] = 1.4
        packet["tool_routing"] = routing_guidance(packet)
        self.assertEqual(packet["tool_routing"]["sleep_review_windows"], ["window_1"])
        self.assertTrue(packet["tool_routing"]["borderline_weight_step"])
        self.assertEqual(recommended_tool(packet), (TOOL_NAME, TOOL_TARGET))
        windows["window_1"]["stability_screen"]["result"] = "mixed"
        packet["tool_routing"] = routing_guidance(packet)
        self.assertEqual(packet["tool_routing"]["sleep_review_windows"], [])
        self.assertEqual(recommended_tool(packet), ("evaluate", "weight"))
        packet["weight_summary"]["effect"] = 2.0
        packet["tool_routing"] = routing_guidance(packet)
        self.assertIsNone(recommended_tool(packet))

    def test_offline_stability_constrains_both_arms_and_rejects_decisive_conflicts(self):
        with self.assertRaisesRegex(PermissionError, "offline mock"):
            batch.run_batch(self.manifest_path, self.packets, self.root / "live",
                            live_transport=SDKTransport(None), stability=True)

        def factory(arm, index):
            packet = Observations(self.packets / self.manifest["ordered_cases"][index])
            observation = ReassessmentObservations(packet, stability=True)
            transport = batch._mock_transport(arm, index, remediation=True, observation=observation)
            if index != 0:
                return transport
            outcomes = list(transport.outcomes)
            prediction = json.loads(outcomes[-1]["output"][0]["content"][0]["text"])
            target = next(target for target in research.protocol.WINDOWS if target in packet.packet["witnesses"])
            prediction["relationship"][target].update(decision="supported", effect=-30,
                                                      evidence=packet.packet["witnesses"][target]["id"])
            outcomes[-1] = mock_response(prediction=prediction)
            return MockTransport(outcomes)

        with patch("sleep_evidence._stability", return_value={"availability": "available", "result": "mixed"}):
            transports = {}

            def capture(arm, index):
                transports[arm, index] = factory(arm, index)
                return transports[arm, index]

            result = batch.run_batch(self.manifest_path, self.packets, self.root / "stable",
                                     mock_transport=capture, stability=True)
        self.assertEqual(result["status_counts"], {"completed": 22, "required_window_abstention": 2})
        self.assertEqual(result["offline_stability"]["packet_version"], "observation-packet-v13")
        self.assertEqual(result["offline_stability"]["endpoint_method"], "whole-window-matched-v1")
        self.assertEqual(result["offline_stability"]["stability_method"], "matched-thirds-v2")
        self.assertEqual(result["offline_stability"]["threshold_method"], "clustered-threshold-v1")
        self.assertEqual(result["offline_stability"]["weight_method"], "grounded-weight-v1")
        self.assertEqual(result["offline_stability"]["weight_verification_method"], "local-weight-step-v1")
        self.assertEqual(result["offline_stability"]["routing_method"], "mixed-tool-routing-v3")
        self.assertEqual(result["offline_stability"]["selection_version"], "tyr_tool_selection_v7")
        self.assertEqual(result["offline_stability"]["sleep_precedence_method"], "shared-strata-precedence-v1")
        self.assertEqual(result["actual_api_calls"], 0)
        b, c = (transports[arm, 0].requests[-1] for arm in ("B", "C"))
        self.assertEqual(json.loads(b["input"])["observation_packet"], json.loads(c["input"])["observation_packet"])
        for request in (b, c):
            schema = request["text"]["format"]["schema"]["properties"]["relationship"]["properties"]
            self.assertTrue(all(w["properties"]["decision"]["enum"] == ["inconclusive"] for w in schema.values()))

    def test_dual_cues_execute_sleep_on_host_with_one_final_request(self):
        order = self.manifest["ordered_cases"]
        obs = ReassessmentObservations(Observations(self.packets / order[0]), stability=True)
        obs.packet["tool_routing"].update(sleep_review_windows=["window_3"], borderline_weight_step=True,
                                         recommended="sleep")
        schedule = [(case, arm) for case in order for arm in "ABC"]
        ledger = Ledger(self.root / "host.sqlite", BATCH_LIMITS, schedule, {}, mode="mock-pilot",
                        host_sleep_cases=[order[0]])
        with self.assertRaisesRegex(BudgetBlocked, "unscheduled_stage"):
            ledger.reserve(order[0], "C", 0, "a" * 64)
        with self.assertRaisesRegex(BudgetBlocked, "unscheduled_stage"):
            ledger.reserve(order[1], "C", 1, "a" * 64)
        transport = batch._mock_transport("C", 0, observation=obs)
        with self.assertRaisesRegex(PermissionError, "requires a sleep tool receipt"):
            research.dispatch(ledger, transport, obs, "C", 1)
        result = research.run_model(ledger, obs, "C", transport)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool_selection"], "host_selected_sleep")
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertNotIn("tools", request)
        self.assertEqual(request["max_output_tokens"], 3900)
        self.assertEqual(json.loads(request["input"])["executed_tool"]["operation"], TOOL_NAME)
        report = ledger.report()
        self.assertEqual([a["stage"] for a in report["attempts"]], [1])
        stages = batch._stage_statuses(report, [(order[0], "C", i) for i in range(2)])
        self.assertEqual([stage["status"] for stage in stages], ["host_selected_sleep", "completed"])
        self.assertEqual(research.run_model(ledger, obs, "C", transport), result)
        self.assertEqual(len(transport.requests), 1)

        failed = Ledger(self.root / "failed.sqlite", BATCH_LIMITS, schedule, {}, mode="mock-pilot",
                        host_sleep_cases=[order[0]])
        with patch.object(obs, "tool", side_effect=ValueError("invalid receipt")):
            failure = research.run_model(failed, obs, "C", MockTransport([]))
        self.assertEqual(failure["status"], "tool_failure")
        self.assertEqual(failure["tool_selection"], "host_selected_sleep")
        self.assertEqual(failed.report()["attempts"], [])

    def test_historical_live_batch_stops_before_staging_or_transport(self):
        transport = SDKTransport(None)
        for remediation in (False, True):
            with self.subTest(remediation=remediation), patch.object(batch, "admit") as admit:
                work = self.root / "live"
                with self.assertRaisesRegex(ValueError, "full-context reservation"):
                    batch.run_batch(self.manifest_path, self.packets, work, live_transport=transport,
                                    remediation=remediation, approved_remediation=remediation)
                admit.assert_not_called()
                self.assertFalse(work.exists())

    def test_full_usage_exhausts_the_case_budget_before_dispatch(self):
        model = research.model_abstention()

        def outcome(value, output):
            response = mock_response(prediction=value)
            response["usage"].update(input_tokens=PILOT.input_limit, output_tokens=output,
                                     total_tokens=PILOT.input_limit + output)
            return response

        def factory(arm, index):
            final = outcome(model, 3900)
            return MockTransport([final] if arm == "B" else [outcome({"action": "skip"}, 512), final])

        report = batch.run_batch(self.manifest_path, self.packets, self.root / "results", mock_transport=factory)
        self.assertEqual(len(report["attempts"]), 2)
        self.assertEqual(report["accounted_cost_microusd"], 619_854)
        self.assertEqual(report["hard_cap_microusd"], 5_000_000)
        self.assertEqual(report["status_counts"], {"completed": 9, "budget_exhausted": 1,
                                                   "not_run_budget_exhausted": 14})
        self.assertEqual(report["stage_status_counts"]["not_run_budget_exhausted"], 22)
        self.assertEqual(len(report["scheduled_model_stages"]), 24)

    def test_uncertain_usage_halts_later_stages_without_retry(self):
        transports = {}

        def factory(arm, index):
            if (arm, index) == ("B", 0):
                transport = MockTransport([TimeoutError("untrusted network diagnostics")])
            else:
                transport = MockTransport([])
            transports[arm, index] = transport
            return transport

        report = batch.run_batch(self.manifest_path, self.packets, self.root / "results", mock_transport=factory)
        self.assertEqual(sum(len(t.requests) for t in transports.values()), 1)
        self.assertEqual(report["attempts"][0]["status"], "uncertain")
        self.assertEqual(report["accounted_cost_microusd"], reservation(3900)["cost_microusd"])
        self.assertEqual(report["stage_status_counts"], {"uncertain": 1, "not_run_uncertain_provider_request": 23})
        self.assertNotIn("untrusted network diagnostics", json.dumps(report))


class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.paths = cls.stack.enter_context(public_panel())
        cls.observation = Observations(cls.paths[0])
        cls.case = cls.observation.task["case_id"]

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.schedule = [(self.case, arm) for arm in research.ARMS]

    def ledger(self, limits=None):
        return Ledger(self.root / "research.sqlite", limits or Limits(), self.schedule, {"test": 1})

    def prediction(self):
        return self.observation.validate_model(research.model_abstention())["prediction"]

    def test_provenance_admission_and_packet_allowlist(self):
        data = json.loads(ADAPTER.request(self.observation.packet)["input"])["observation_packet"]
        self.assertEqual(set(data), {"version", "task", "snapshot_columns", "snapshot", "sleep_columns", "sleep", "witnesses"})
        self.assertEqual(set(data["task"]), {"version", "case_id", "relationship", "change"})
        self.assertTrue(all(type(cell) in (type(None), int, float) for row in data["snapshot"] for cell in row[2:]))
        self.assertTrue(all(type(cell) in (type(None), int, float) for row in data["sleep"] for cell in row[2:]))
        # Controller/CLI has no caller-supplied packet path. Normal packet validation also rejects broken bindings.
        with self.assertRaises(ValueError):
            Observations(self.root)
        with self.assertRaises(ValueError):
            ADAPTER.request({**self.observation.packet, "unexpected": "x" * 48_001})
        with self.assertRaises(PermissionError):
            research.dispatch(self.ledger(), SDKTransport(None), self.observation, "B", 0)

    def test_sleep_only_envelope_rejects_weight_output_and_live_transport(self):
        obs = SleepOnly(self.paths[0])
        b, c = (obs.request(arm) for arm in ("B", "C"))
        packet = b["input"]["observation_packet"]
        self.assertEqual(packet, c["input"]["observation_packet"])
        self.assertEqual(set(packet["task"]), {"case_id", "relationship"})
        self.assertEqual(set(packet["tool_routing"]), {"method", "action", "sleep_review_windows"})
        self.assertTrue(set(packet["witnesses"]) <= set(research.protocol.WINDOWS))
        self.assertNotIn("body_weight", packet["snapshot_columns"])
        self.assertEqual(b["response_schema"]["required"], ["relationship"])
        self.assertNotIn("executed_tool", b["input"])
        with self.assertRaisesRegex(PermissionError, "mock transport"):
            obs.request_mock("C", SDKTransport(None))
        value = deterministic_prediction(c)
        self.assertEqual(obs.request_mock("C", MockTransport([value]))["status"], "completed")
        with self.assertRaisesRegex(InvalidResult, "malformed_prediction"):
            obs.request_mock("C", MockTransport([{**value, "change": {}}]))

    def test_within_period_submission_requires_calculated_effect_and_local_witness(self):
        observations = (WithinPeriodSleep(path) for path in self.paths)
        obs = next(item for item in observations if item.local_witnesses)
        request = obs.request("C")
        value = deterministic_prediction(request)
        target = next(iter(obs.local_witnesses))
        valid = obs.request_mock("C", MockTransport([value]))
        self.assertEqual(valid["numerical_provenance"][target], ESTIMATE_METHOD)
        self.assertTrue(valid["prediction"]["relationship"][target]["references"])
        for key, changed, classification in (
            ("effect", value["relationship"][target]["effect"] + 1, "ungrounded_sleep"),
            ("estimate_method", ENDPOINT_METHOD, "ungrounded_sleep"),
            ("evidence", "foreign-case", "invalid_evidence"),
        ):
            altered = deepcopy(value)
            altered["relationship"][target][key] = changed
            with self.assertRaisesRegex(InvalidResult, classification):
                obs.request_mock("C", MockTransport([altered]))
        with self.assertRaisesRegex(PermissionError, "mock transport"):
            obs.request_mock("C", SDKTransport(None))
        self.assertNotIn("within_period_support", obs.request("B")["input"])

    def test_sleep_summary_counts_and_missing_observations(self):
        enriched = ReassessmentObservations(self.observation)
        summary = enriched.packet["sleep_summary"]["windows"]["window_1"]
        coverage = self.observation.tool("coverage", "window_1")
        self.assertEqual(summary["paired_days"], coverage["paired_days"])
        self.assertEqual(summary["later_count"], coverage["late_days"])
        self.assertEqual(summary["earlier_count"] + summary["later_count"], summary["paired_days"])
        self.assertAlmostEqual(summary["late_minus_earlier_minutes"],
                               summary["later_mean_minutes"] - summary["earlier_mean_minutes"], places=5)
        window = self.observation.window("window_1")
        start, end = (research.protocol.civil(window[key]) for key in ("start", "end"))
        with patch("sleep_evidence._windows", return_value=[("window_1", start, end, [])]):
            missing = summaries(None, self.observation.task)["windows"]["window_1"]
        self.assertEqual(missing["paired_days"], 0)
        self.assertIsNone(missing["late_minus_earlier_minutes"])
        self.assertIsNone(missing["matched"]["late_minus_earlier_minutes"])
        self.assertEqual(missing["support_limits"], ["paired_coverage", "common_support"])

    def test_grounded_weight_binds_the_effect_date_and_local_witness(self):
        observations = (ReassessmentObservations(Observations(path), stability=True) for path in self.paths)
        obs = next(item for item in observations if item.packet["weight_summary"]["decision"] == "change")
        calculated = obs.packet["weight_summary"]
        model = research.model_abstention(grounded_sleep=True)
        model["change"] = {key: calculated[key] for key in ("decision", "effect", "split", "evidence")}

        result = obs.validate_model(model)
        self.assertEqual(result["numerical_provenance"]["weight"], "matches_calculation")
        finding = result["prediction"]["change"]
        self.assertEqual(obs.tool("evaluate", "weight")["finding"], finding)
        self.assertEqual(len(finding["references"]), 4)
        weight_days = [obs.accepted.rows["daily_snapshot"][ref["row_id"]]["day"]
                       for ref in finding["references"]]
        self.assertEqual(sum(day < calculated["split"] for day in weight_days), 2)
        for replacement in ({"effect": calculated["effect"] * 2}, {"split": None}, {"evidence": "sleep"}):
            invalid = {**model, "change": {**model["change"], **replacement}}
            with self.assertRaisesRegex(InvalidResult, "ungrounded_weight"):
                obs.validate_model(invalid)

    def test_c_weight_override_requires_a_matching_weight_challenge(self):
        observations = (ReassessmentObservations(Observations(path), stability=True) for path in self.paths)
        obs = next(item for item in observations if item.packet["weight_summary"]["decision"] == "change")
        grounded = obs.packet["weight_summary"]
        abstention = research.model_abstention(grounded_sleep=True)
        keep = {**abstention, "change": {key: grounded[key] for key in ("decision", "effect", "split", "evidence")}}
        tool = obs.tool("evaluate", "weight")
        challenge = {**tool, "weight_verification": {**tool["weight_verification"], "status": "challenge",
                                                    "abstention_reason": "near_threshold_local_step"}}
        self.assertEqual(obs.validate_model(keep, arm="C")["status"], "completed")
        with self.assertRaisesRegex(InvalidResult, "weight_verification_conflict"):
            obs.validate_model(abstention, arm="C")
        self.assertEqual(obs.validate_model(abstention, challenge, arm="C")["status"], "completed")
        with self.assertRaisesRegex(InvalidResult, "weight_verification_conflict"):
            obs.validate_model(keep, challenge, arm="C")
        mismatched = {**challenge, "weight_verification": {**challenge["weight_verification"], "split": None}}
        with self.assertRaisesRegex(InvalidResult, "weight_verification_conflict"):
            obs.validate_model(abstention, mismatched, arm="C")
        self.assertEqual(obs.validate_model(abstention, arm="B")["status"], "completed")

    def test_sleep_decision_binds_named_estimate_and_tool_scope(self):
        from pilot_design import task_record
        from reassessment_design import DEVELOPMENT_SEED, make_case
        from synthetic_storage import build_records

        def usable():
            for replica in range(4):
                cid, first, days, windows, _ = make_case(DEVELOPMENT_SEED, "gain_anchor", replica)
                path = self.root / cid
                path.mkdir()
                database = path / "records.sqlite"
                build_records(database, days)
                task = task_record(cid, first, len(days), windows, research.protocol.hash_file(database))
                (path / "task.json").write_text(research.protocol.canonical(task) + "\n")
                obs = ReassessmentObservations(Observations(path), stability=True)
                tool = obs.tool(TOOL_NAME, TOOL_TARGET)
                for target in research.protocol.WINDOWS:
                    obs.packet["tool_routing"]["sleep_review_windows"] = [target]
                    if ACROSS_WINDOW_METHOD in sleep_estimates(obs.packet, target, tool, arm="C"):
                        yield obs, tool, target

        obs, tool, target = next(usable())
        witness = obs.packet["witnesses"][target]["id"]
        model = research.model_abstention(grounded_sleep=True)
        grounded = obs.packet["weight_summary"]
        model["change"] = {key: grounded[key] for key in ("decision", "effect", "split", "evidence")}
        def choose(method, effect):
            model["relationship"][target].update(
                decision="supported" if effect <= -15 else "notSupported",
                effect=effect, evidence=witness, estimate_method=method,
            )

        def variants(receipt):
            return _prediction_schema(obs.packet, receipt, arm="C")["properties"]["relationship"]["properties"][target]

        effect = tool["windows"][target]["matched_across_windows"]["late_minus_earlier_minutes"]
        self.assertEqual(sleep_estimates(obs.packet, target, tool, arm="C"), {ACROSS_WINDOW_METHOD: effect})
        self.assertEqual(variants(tool)["anyOf"][1]["properties"]["estimate_method"]["enum"], [ACROSS_WINDOW_METHOD])
        choose(ACROSS_WINDOW_METHOD, effect)
        record = obs.validate_model(model, tool, arm="C")
        self.assertEqual(record["numerical_provenance"][target], ACROSS_WINDOW_METHOD)
        self.assertNotIn("estimate_method", record["prediction"]["relationship"][target])
        with self.assertRaisesRegex(InvalidResult, "ungrounded_sleep"):
            obs.validate_model(model, tool, arm="B")
        with self.assertRaisesRegex(InvalidResult, "ungrounded_sleep"):
            obs.validate_model(model, arm="C")

        whole = sleep_estimates(obs.packet, target, arm="C")[ENDPOINT_METHOD]
        choose(ENDPOINT_METHOD, whole)
        with self.assertRaisesRegex(InvalidResult, "ungrounded_sleep"):
            obs.validate_model(model, tool, arm="C")
        self.assertEqual(obs.validate_model(model, tool, arm="B")["status"], "completed")
        self.assertEqual(obs.validate_model(model, arm="C")["status"], "completed")
        self.assertEqual(sleep_estimates(obs.packet, target, obs.tool("evaluate", "weight"), arm="C"),
                         {ENDPOINT_METHOD: whole})
        with patch.dict(obs.packet["tool_routing"], sleep_review_windows=[]):
            self.assertEqual(obs.validate_model(model, tool, arm="C")["status"], "completed")

        calculation = tool["windows"][target]
        for value, reason in ((None, "missing_common_sensitivity"), ([-16, -14], "common_estimate_threshold_sensitive")):
            with self.subTest(reason=reason), patch.dict(calculation, leave_one_14_day_block_range_minutes=value):
                self.assertEqual(sleep_decision_basis(obs.packet, target, tool, arm="C")["reason"], reason)
                self.assertEqual(variants(tool)["properties"]["decision"]["enum"], ["inconclusive"])
                with self.assertRaisesRegex(InvalidResult, "required_window_abstention"):
                    obs.validate_model(model, tool, arm="C")
        with patch.dict(calculation["matched_across_windows"], earlier_count=9):
            self.assertEqual(sleep_decision_basis(obs.packet, target, tool, arm="C")["reason"],
                             "inadequate_common_support")
        model["relationship"][target] = research.model_abstention(grounded_sleep=True)["relationship"][target]
        self.assertEqual(obs.validate_model(model, tool, arm="C")["status"], "completed")
        with self.assertRaisesRegex(InvalidResult, "invalid_tool"):
            obs.tool("evaluate", target)

    def test_shared_packet_and_no_worker_or_provider_access(self):
        ledger = self.ledger()
        final = mock_response(prediction=research.model_abstention())
        b, c = MockTransport([final]), MockTransport([mock_response(target="window_1"), final])
        self.assertEqual(research.run_model(ledger, self.observation, "B", b)["status"], "completed")
        result = research.run_model(ledger, self.observation, "C", c)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool"]["target"], "window_1")
        self.assertIsNone(result["submission"]["provider"])
        self.assertEqual(b.requests[0]["input"], c.requests[0]["input"])
        self.assertNotIn("tools", b.requests[0])
        self.assertEqual({t["name"] for t in c.requests[0]["tools"]}, {"coverage", "evaluate"})
        self.assertNotIn("tools", c.requests[1])
        second = json.loads(c.requests[1]["input"])
        self.assertEqual(second["executed_tool"], result["tool"])
        self.assertEqual(set(second), {"observation_packet", "executed_tool"})
        for request in [*b.requests, *c.requests]:
            self.assertFalse(request["store"])
            self.assertFalse(request["background"])
            self.assertEqual(request["max_output_tokens"], PILOT.output_limit)
            self.assertTrue(request["text"]["format"]["strict"])
            self.assertNotIn("previous_response_id", request)
        receipt = ledger.report()
        self.assertEqual(receipt["actual_api_calls"], 0)
        self.assertEqual(receipt["accounted_cost_microusd"], 21_600)
        self.assertEqual(len(receipt["attempts"]), 3)

    def test_resume_after_settled_stage_does_not_resend(self):
        transport = MockTransport([mock_response(target="weight")])
        first = research.dispatch(self.ledger(), transport, self.observation, "C", 0)
        self.assertEqual(first["status"], "tool")
        ledger = self.ledger()
        replay = research.demo_transport()
        result = research.run_model(ledger, self.observation, "C", replay)
        self.assertEqual(len(replay.requests), 1)
        self.assertEqual(research.run_model(ledger, self.observation, "C", MockTransport([])), result)
        self.assertEqual(len(ledger.report()["attempts"]), 2)
        with self.assertRaises(ValueError):
            Ledger(ledger.path, Limits(attempts=9), self.schedule, {"test": 1})

    def test_interrupted_attempt_blocks_and_keeps_full_reservation(self):
        ledger = self.ledger()
        self.assertIsNone(ledger.reserve(self.case, "B", 0, "digest"))
        attempts = self.ledger().report()["attempts"]
        self.assertEqual(attempts[0]["status"], "pending")
        self.assertEqual(attempts[0]["accounted_cost_microusd"], reservation()["cost_microusd"])
        with self.assertRaisesRegex(BudgetBlocked, "pending_request"):
            self.ledger().reserve(self.case, "C", 0, "digest")

    def test_concurrent_reservations_are_serialized(self):
        ledger = self.ledger(Limits(experiment_microusd=309_000))

        def reserve(arm):
            try:
                return ledger.reserve(self.case, arm, 0, "digest")
            except BudgetBlocked as error:
                return error.classification

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ("B", "C")))
        self.assertCountEqual(results, [None, "pending_request"])
        self.assertEqual(len(ledger.report()["attempts"]), 1)

    def test_budget_exhaustion_latches_across_restart(self):
        ledger = self.ledger(Limits(attempts=1))
        first = MockTransport([mock_response(prediction=research.model_abstention())])
        research.run_model(ledger, self.observation, "B", first)
        denied = MockTransport([])
        result = research.run_model(self.ledger(Limits(attempts=1)), self.observation, "C", denied)
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertFalse(denied.requests)
        self.assertEqual(len(ledger.report()["attempts"]), 1)

    def test_token_and_monetary_ceilings_are_independent(self):
        for limits in (Limits(tokens=401_999), Limits(case_microusd=308_999),
                       Limits(experiment_microusd=308_999)):
            with self.subTest(limits=limits), TemporaryDirectory() as scratch:
                ledger = Ledger(Path(scratch) / "research.sqlite", limits, self.schedule, {})
                denied = ledger.reserve(self.case, "B", 0, "digest")
                self.assertEqual(denied["status"], "budget_exhausted")
                self.assertEqual(ledger.report()["attempts"], [])

    def test_full_context_experiment_stops_at_the_aggregate_cap(self):
        cases = [f"case-{i}" for i in range(17)]
        ledger = Ledger(self.root / "full.sqlite", Limits(), [(case, "B") for case in cases], {})
        for case in cases[:16]:
            self.assertIsNone(ledger.reserve(case, "B", 0, "digest"))
            ledger.settle(case, "B", 0, {"input_tokens": 400_000, "output_tokens": 2_000}, {"status": "completed"})
        self.assertEqual(ledger.reserve(cases[-1], "B", 0, "digest"), {"status": "budget_exhausted"})
        amounts = ledger.report()
        self.assertEqual(len(amounts["attempts"]), 16)
        self.assertEqual(amounts["accounted_cost_microusd"], 4_944_000)

    def test_uncertain_usage_keeps_reservation_and_stops_other_arms(self):
        ledger = self.ledger()
        for payload in (TimeoutError("SECRET_MARKER"), {**mock_response(prediction=research.model_abstention()), "model": "moving"}):
            with self.subTest(payload_type=type(payload)), TemporaryDirectory() as scratch:
                journal = Ledger(Path(scratch) / "research.sqlite", Limits(), self.schedule, {})
                first = research.run_model(journal, self.observation, "B", MockTransport([payload]))
                self.assertEqual(first["status"], "uncertain_provider_request")
                blocked = research.run_model(journal, self.observation, "C", MockTransport([]))
                self.assertEqual(blocked["status"], "not_run_uncertain_provider_request")
                report = journal.report()
                self.assertEqual(len(report["attempts"]), 1)
                self.assertEqual(report["accounted_cost_microusd"], reservation()["cost_microusd"])
                self.assertNotIn("SECRET_MARKER", json.dumps(report))
        self.assertEqual(ledger.report()["recorded_runs"], 0)

    def test_refusal_and_malformed_response_count_as_spend(self):
        for kind, expected in (("refusal", "provider_refusal"), ("output_text", "malformed_provider_output")):
            with self.subTest(kind=kind), TemporaryDirectory() as scratch:
                response = mock_response(prediction=research.model_abstention())
                response["output"][0]["content"] = [{"type": kind, "text": '{"a":1,"a":2}'}]
                ledger = Ledger(Path(scratch) / "research.sqlite", Limits(), self.schedule, {})
                outcome = research.run_model(ledger, self.observation, "B", MockTransport([response]))
                self.assertEqual(outcome["status"], expected)
                self.assertEqual(ledger.report()["accounted_cost_microusd"], 7200)

    def test_rejects_tool_extraction_and_extra_turns(self):
        cases = [
            ("B", mock_response(target="weight"), "invalid_tool"),
            ("C", mock_response(target="weight", operation="read_file"), "invalid_tool"),
            ("C", mock_response(target="/tmp/evaluator/index.json"), "invalid_tool"),
            ("C", mock_response(target="window_4"), "invalid_tool"),
        ]
        extra = mock_response(target="weight")
        extra["output"][0]["arguments"] = '{"target":"weight","path":"/tmp/evaluator"}'
        cases.append(("C", extra, "invalid_tool"))
        parallel = mock_response(target="weight")
        parallel["output"].append(deepcopy(parallel["output"][0]))
        cases.append(("C", parallel, "malformed_provider_output"))
        for arm, response, expected in cases:
            with self.subTest(arm=arm, expected=expected), TemporaryDirectory() as scratch:
                ledger = Ledger(Path(scratch) / "research.sqlite", Limits(), self.schedule, {})
                transport = MockTransport([response])
                outcome = research.run_model(ledger, self.observation, arm, transport)
                self.assertEqual(outcome["status"], expected)
                self.assertEqual(len(transport.requests), 1)
        result = research.run_model(self.ledger(), self.observation, "C",
                                    MockTransport([mock_response(target="weight"), mock_response(target="weight")]))
        self.assertEqual(result["status"], "invalid_tool")

    def test_invalid_evidence_causality_and_tool_numbers(self):
        invalid = self.prediction()
        invalid["change"]["references"] = [{"table": "daily_snapshot", "row_id": 2**62, "column": "body_weight"}]
        with self.assertRaisesRegex(InvalidResult, "invalid_evidence"):
            self.observation.validate(invalid)
        invalid = self.prediction()
        invalid["change"]["claim_type"] = "causal"
        with self.assertRaisesRegex(InvalidResult, "unsupported_causal"):
            self.observation.validate(invalid)
        prediction = self.prediction()
        tool = self.observation.tool("evaluate", "window_1")
        self.assertIsNotNone(tool["finding"]["effect"])
        prediction["relationship"]["window_1"]["effect"] = tool["finding"]["effect"]
        score = self.observation.validate(prediction, tool)
        self.assertEqual(score["numerical_provenance"]["window_1"], "matches_tool")
        score = self.observation.validate(prediction)
        self.assertEqual(score["numerical_provenance"]["window_1"], "model_estimate")
        prediction["relationship"]["window_1"]["effect"] += 8
        with self.assertRaisesRegex(InvalidResult, "tool_number_mismatch"):
            self.observation.validate(prediction, tool)

    def test_mock_c_preserves_provenance_when_weight_tool_returns_no_estimate(self):
        witness = self.observation.packet["witnesses"]["weight"]
        tool = self.observation.tool("evaluate", "weight")
        self.assertIsNone(tool["finding"]["effect"])
        self.assertEqual(tool["finding"]["decision"], "inconclusive")
        for effect, provenance in ((0.25, "model_estimate"), (None, "unavailable")):
            with self.subTest(effect=effect), TemporaryDirectory() as scratch:
                model = research.model_abstention()
                model["change"].update(decision="no_change", effect=effect, evidence=witness["id"])
                ledger = Ledger(Path(scratch) / "research.sqlite", Limits(), self.schedule, {})
                transport = MockTransport([mock_response(target="weight", operation="evaluate"),
                                           mock_response(prediction=model)])
                result = research.run_model(ledger, self.observation, "C", transport)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["tool"], tool)
                self.assertEqual(result["numerical_provenance"]["weight"], provenance)
                submission = research.scoring.submission(result["submission"], self.observation.task)
                finding = submission["predictions"]["change"]
                self.assertEqual(finding["effect"], effect)
                self.assertEqual(finding["references"], witness["references"])
                self.assertEqual(ledger.report()["actual_api_calls"], 0)
        zero_tool = {**tool, "finding": {**tool["finding"], "effect": 0.0}}
        model["change"]["effect"] = 0.25
        with self.assertRaisesRegex(InvalidResult, "tool_number_mismatch"):
            self.observation.validate_model(model, zero_tool)
        model["change"]["effect"] = 1.0
        with self.assertRaisesRegex(InvalidResult, "invalid_effect"):
            self.observation.validate_model(model, tool)
        model["change"].update(effect=0.25, evidence="fake")
        with self.assertRaisesRegex(InvalidResult, "invalid_evidence"):
            self.observation.validate_model(model, tool)

    def test_mock_decisive_b_and_c_translate_to_scorer_contract(self):
        tool = self.observation.tool("evaluate", "window_1")
        model = research.model_abstention()
        sleep_witness = self.observation.packet["witnesses"]["window_1"]
        weight_witness = self.observation.packet["witnesses"]["weight"]
        model["relationship"]["window_1"].update(
            decision=tool["finding"]["decision"], effect=tool["finding"]["effect"], evidence=sleep_witness["id"])
        model["change"].update(decision="no_change", evidence=weight_witness["id"])

        ledger = self.ledger()
        b_transport = MockTransport([mock_response(prediction=model)])
        c_transport = MockTransport([mock_response(target="window_1", operation="evaluate"),
                                     mock_response(prediction=model)])
        b = research.run_model(ledger, self.observation, "B", b_transport)
        c = research.run_model(ledger, self.observation, "C", c_transport)
        for actual in (b, c):
            self.assertEqual(actual["status"], "completed")
            submission = research.scoring.submission(actual["submission"], self.observation.task)
            prediction = submission["predictions"]
            self.assertEqual(prediction["case_id"], self.case)
            for finding, witness in [(prediction["relationship"]["window_1"], sleep_witness),
                                     (prediction["change"], weight_witness)]:
                self.assertEqual(finding["references"], witness["references"])
            with closing(sqlite3.connect(self.observation.database.as_uri() + "?mode=ro", uri=True)) as db:
                for target, witness in (("window_1", sleep_witness), ("weight", weight_witness)):
                    window = self.observation.window(target)
                    trace = research.scoring._trace(
                        db, witness["references"], window["start"], window["end"], relationship=target != "weight")
                    self.assertTrue(trace["traceable"])
                    self.assertEqual(trace["invalid_references"], 0)
        self.assertEqual(b["numerical_provenance"]["window_1"], "model_estimate")
        self.assertEqual(c["numerical_provenance"]["window_1"], "matches_tool")
        sent_tool = json.loads(c_transport.requests[1]["input"])["executed_tool"]
        self.assertNotIn("references", sent_tool["finding"])
        self.assertEqual(c["tool"], tool)

    def test_model_rejects_wrong_witness_and_prediction_shape(self):
        valid = research.model_abstention()
        witnesses = self.observation.packet["witnesses"]
        valid["relationship"]["window_1"].update(decision="notSupported", effect=0, evidence=witnesses["window_1"]["id"])
        self.observation.validate_model(valid)
        other_case = Observations(self.paths[1])
        for token in (None, witnesses["weight"]["id"], other_case.packet["witnesses"]["window_1"]["id"], "fake"):
            with self.subTest(token=token):
                invalid = deepcopy(valid)
                invalid["relationship"]["window_1"]["evidence"] = token
                with self.assertRaisesRegex(InvalidResult, "invalid_evidence"):
                    self.observation.validate_model(invalid)
        for weight_fields in (
            {"decision": "change", "split": "bad date", "effect": 2.0, "evidence": witnesses["weight"]["id"]},
            {"decision": "no_change", "split": "2025-04-01", "effect": 0.0, "evidence": witnesses["weight"]["id"]},
            {"decision": "inconclusive", "split": None, "effect": None, "claim_type": "causal"},
        ):
            with self.subTest(fields=weight_fields):
                invalid = deepcopy(valid)
                invalid["change"].update(weight_fields)
                with self.assertRaisesRegex(InvalidResult, "malformed_prediction"):
                    self.observation.validate_model(invalid)
        invalid = deepcopy(valid)
        invalid["relationship"]["window_1"]["confounders"]["training_day"] = 1
        with self.assertRaisesRegex(InvalidResult, "malformed_prediction"):
            self.observation.validate_model(invalid)
        invalid = deepcopy(valid)
        invalid["relationship"]["window_1"]["effect"] = None
        with self.assertRaisesRegex(InvalidResult, "malformed_prediction"):
            self.observation.validate_model(invalid)
        invalid = deepcopy(valid)
        invalid["relationship"]["window_1"]["effect"] = -15
        with self.assertRaisesRegex(InvalidResult, "invalid_effect"):
            self.observation.validate_model(invalid)

    def test_provider_schema_matches_witness_and_decision_rules(self):
        witnesses = self.observation.packet["witnesses"]
        envelope = ADAPTER.request(self.observation.packet)
        schema = envelope["text"]["format"]["schema"]
        self.assertEqual(set(schema["properties"]), {"relationship", "change"})
        sleep = schema["properties"]["relationship"]["properties"]["window_1"]["anyOf"]
        self.assertEqual(sleep[0]["properties"]["evidence"], {"type": "null"})
        self.assertEqual(sleep[1]["properties"]["effect"]["maximum"], -15)
        self.assertEqual(sleep[2]["properties"]["effect"]["exclusiveMinimum"], -15)
        self.assertEqual(sleep[2]["properties"]["evidence"]["enum"], [witnesses["window_1"]["id"]])
        self.assertEqual(sleep[2]["properties"]["confounders"]["properties"]["training_day"], {"type": "boolean"})
        weight = schema["properties"]["change"]["anyOf"]
        self.assertEqual(weight[1]["properties"]["split"], {"type": "null"})
        splits = weight[2]["properties"]["split"]["enum"]
        self.assertEqual((splits[0], splits[-1]), (witnesses["weight"]["first_split"], witnesses["weight"]["last_split"]))
        packet = {**self.observation.packet, "witnesses": {}}
        schema = ADAPTER.request(packet)["text"]["format"]["schema"]
        sleep = schema["properties"]["relationship"]["properties"]["window_1"]
        self.assertEqual(sleep["properties"]["decision"]["enum"], ["inconclusive"])
        self.assertEqual(schema["properties"]["change"]["properties"]["decision"]["enum"], ["inconclusive"])

    def test_dry_run_writes_no_ledger_and_demo_resumes(self):
        work = self.root / "research"
        dry_run = research.demo(work, dry_run=True)
        self.assertFalse(work.exists())
        self.assertEqual(dry_run["actual_api_calls"], 0)
        result = research.demo(work)
        self.assertEqual(result["recorded_runs"], result["scheduled_runs"])
        self.assertEqual(result["mock_attempts"], 24)
        self.assertEqual(research.demo(work), result)

    def test_live_smoke_schedule_and_cost_using_mock_provider(self):
        seen = []
        outcomes = iter((mock_response(target="window_1", operation="evaluate"),
                         mock_response(prediction=research.model_abstention())))

        def fake_create(**payload):
            seen.append(payload)
            response = next(outcomes)
            return SimpleNamespace(model_dump=lambda **kwargs: response)

        transport = SDKTransport(SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
        result = live_smoke.smoke(self.root, transport)
        self.assertEqual(len(seen), 2)
        self.assertEqual(result["attempted_requests"], 2)
        self.assertEqual(result["max_retries"], 0)
        self.assertEqual(result["authorized_microusd"], 650_000)
        self.assertEqual(result["metered_cost_usd"], "0.0144")
        self.assertEqual(sum(a["reserved_cost_microusd"] for a in result["attempts"]), 618_000)
        self.assertEqual(seen[0]["tool_choice"], "required")
        self.assertNotIn("tools", seen[1])
        self.assertIn("executed_tool", json.loads(seen[1]["input"]))
        self.assertTrue(all(run["result"]["status"] == "completed" for run in result["runs"]))
        with self.assertRaises(ValueError):
            Ledger(self.root / "bad.sqlite", SMOKE_LIMITS, self.schedule + [("another", "A")],
                   {}, mode="live-smoke")

    def test_live_smoke_stops_after_unaccounted_request(self):
        class APIError(Exception):
            status_code = 403

        def fake_create(**payload):
            raise APIError("This text is private")

        transport = SDKTransport(SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
        result = live_smoke.smoke(self.root, transport)
        self.assertEqual(result["attempted_requests"], 1)
        self.assertEqual(result["responses_with_usage"], 0)
        self.assertEqual(result["unresolved_reservation_microusd"], 309_000)
        self.assertEqual(result["runs"][1]["result"]["http_status"], 403)
        self.assertEqual(result["runs"][1]["result"]["status"], "uncertain_provider_request")
        self.assertNotIn("This text is private", json.dumps(result))

    def test_live_rerun_caps_and_full_reservation(self):
        request_caps = []
        final = mock_response(prediction=research.model_abstention())
        final["usage"].update(output_tokens=2_500, total_tokens=8_500)
        selection = mock_response(target="window_1", operation="evaluate")
        selection["usage"].update(output_tokens=111, total_tokens=6_111)
        selection["usage"]["output_tokens_details"]["reasoning_tokens"] = 90
        responses = iter((selection, final))

        def fake_create(**payload):
            request_caps.append(payload["max_output_tokens"])
            response = next(responses)
            return SimpleNamespace(model_dump=lambda **kwargs: response)

        transport = SDKTransport(SimpleNamespace(responses=SimpleNamespace(create=fake_create)))
        result = live_smoke.smoke(self.root, transport, rerun=True)
        self.assertEqual(request_caps, [512, 3_900])
        self.assertEqual(result["mode"], "live-smoke-rerun")
        self.assertEqual(result["responses_with_usage"], 2)
        self.assertEqual(result["max_retries"], 0)
        self.assertEqual(result["authorized_microusd"], 650_000)
        self.assertEqual(sum(a["reserved_cost_microusd"] for a in result["attempts"]), 619_854)
        self.assertGreaterEqual(result["usage_totals"]["reasoning_tokens"], 90)
        self.assertTrue(all(run["result"]["status"] == "completed" for run in result["runs"]))


class SDKTests(unittest.TestCase):
    def test_no_sdk_or_credentials_without_authorization(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PermissionError):
                with open_sdk_transport():
                    self.fail("An unapproved transport must not be created")
        with patch.dict(os.environ, {"OPENAI_LOG": "debug"}, clear=True):
            with self.assertRaisesRegex(ValueError, "clean provider environment"):
                with open_sdk_transport(authorized=True):
                    self.fail("An inherited provider override must block initialization")

    @unittest.skipUnless(importlib.util.find_spec("openai") and importlib.util.find_spec("httpx2"),
                         "optional pinned SDK is absent")
    def test_real_sdk_serialization_through_mock_http(self):
        import httpx2

        seen = []
        response = mock_response(target="weight")
        response["object"] = "response"
        response["created_at"] = 0
        response["output"][0].update(id="fc_offline", status="completed")
        statuses = iter((200, 429, 302))

        def fake(request):
            seen.append(json.loads(request.content))
            status = next(statuses)
            if status == 200:
                return httpx2.Response(status, json=response)
            return httpx2.Response(status, json={"error": {"message": "offline test"}},
                                   headers={"Location": "https://unapproved.invalid/v1/responses"})

        test = self

        class MockClient(httpx2.Client):
            def __init__(self, **kwargs):
                test.assertIs(kwargs["trust_env"], False)
                test.assertIs(kwargs["follow_redirects"], False)
                super().__init__(transport=httpx2.MockTransport(fake), **kwargs)

        with patch("httpx2.Client", MockClient), patch.dict(os.environ, {"OPENAI_API_KEY": "offline-fixture"},
                                                           clear=True):
            import openai

            with open_sdk_transport(authorized=True) as transport:
                self.assertEqual(transport.client.max_retries, 0)
                with public_panel() as packets:
                    envelope = ADAPTER.request(Observations(packets[0]).packet, offer_tool=True)
                result = transport.send(envelope)
                self.assertEqual(ADAPTER.output(result, offer_tool=True)["target"], "weight")
                self.assertEqual(seen, [envelope])
                with self.assertRaises(openai.RateLimitError):
                    transport.send(envelope)
                with self.assertRaises(openai.APIStatusError):
                    transport.send(envelope)
                with self.assertRaisesRegex(ValueError, "Unexpected provider destination"):
                    transport.client._client.post("https://unapproved.invalid/v1/responses")
        self.assertEqual(seen, [envelope] * 3)
