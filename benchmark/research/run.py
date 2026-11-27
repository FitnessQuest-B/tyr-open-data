"""Exercise the Phase 4A broker on regenerated public cases with in-memory mocks."""

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / path) for path in ("benchmark", "brain-lab", "tools")]

import protocol
import scoring
import worker
from budget import BATCH_MODES, MOCK_MODES, Ledger, Limits, reservation
from observations import InvalidResult, Observations, TOOL_VERSION, VERSION as PACKET_VERSION, public_panel
from providers import MockTransport
from responses import PILOT, PROMPT_VERSION, Responses, SDKTransport
from sleep_evidence import (
    GROUNDED_TOOL_VERSION, PACKET_VERSION as REASSESSMENT_PACKET_VERSION,
    STABILITY_PACKET_VERSION, TOOL_NAME, TOOL_TARGET, requires_sleep_route,
)

ARMS = ("A", "B", "C")
ADAPTER = Responses()


def provenance():
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                         text=True, stderr=subprocess.DEVNULL, timeout=5,
                                         env={key: value for key, value in os.environ.items()
                                              if not key.startswith("OPENAI_")}).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    sources = sorted(HERE.glob("*.py")) + [ROOT / name for name in (
        "benchmark/task.md", "benchmark/protocol.py", "benchmark/worker.py", "benchmark/prepare.py",
        "benchmark/evidence_method.py", "benchmark/scoring.py", "benchmark/weight_break.py",
        "brain-lab/tyr_brain_lab/analysis.py", "brain-lab/tyr_brain_lab/source.py",
        "tools/generate_synthetic.py", "tools/synthetic_model.py", "tools/synthetic_storage.py",
        "scenarios/starter.json", "schema/versions/0.1.0/manifest.json")]
    return {"commit": commit, "files": {str(p.relative_to(ROOT)): protocol.hash_file(p) for p in sources},
            "packet_version": PACKET_VERSION, "prompt_version": PROMPT_VERSION, "tool_version": TOOL_VERSION,
            "scoring_version": scoring.SCORING_VERSION, "adapter": ADAPTER.name}


def dispatch(ledger, transport, observation, arm, stage, tool=None):
    expected = MockTransport if ledger.mode in MOCK_MODES else SDKTransport
    if type(transport) is not expected:
        raise PermissionError("The transport must match the ledger's frozen mode")
    stability = observation.packet["version"] == STABILITY_PACKET_VERSION
    if stability and ledger.mode != "mock-pilot":
        raise PermissionError("Window stability payloads require the offline mock pilot")
    remediation = stability or observation.packet["version"] == REASSESSMENT_PACKET_VERSION
    if remediation and ledger.mode not in ("mock-pilot", "live-pilot-remediated"):
        raise PermissionError("Remediated sleep payloads require the reviewed remediation schedule")
    if not remediation and ledger.mode == "live-pilot-remediated":
        raise PermissionError("The live remediation schedule requires the reviewed sleep payload")
    case = observation.task["case_id"]
    if arm == "C":
        host_sleep = requires_sleep_route(observation.packet)
        if host_sleep != (case in ledger.host_sleep_cases):
            raise PermissionError("The host sleep route must match the frozen case schedule")
        if host_sleep and (stage != 1 or tool is None or (tool["operation"], tool["target"], tool["version"])
                           != (TOOL_NAME, TOOL_TARGET, GROUNDED_TOOL_VERSION)):
            raise PermissionError("Host-selected sleep requires a sleep tool receipt on the final stage")
    offer_tool = arm == "C" and stage == 0
    selection_only = ledger.mode in BATCH_MODES and offer_tool
    require_tool = expected is SDKTransport and offer_tool and not selection_only
    output_limit = ledger.output_limit(arm, stage)
    payload = ADAPTER.request(observation.packet, offer_tool=offer_tool, require_tool=require_tool,
                              tool_result=tool, output_limit=output_limit, selection_only=selection_only,
                              arm=arm)
    cached = ledger.reserve(case, arm, stage, protocol.digest(payload))
    if cached is not None:
        return cached
    try:
        response = transport.send(payload)
        usage = ADAPTER.usage(response, output_limit=output_limit)
    except Exception as error:
        # Exception strings can contain headers or raw payloads. Keep only the classification.
        ledger.settle(case, arm, stage)
        status_code = getattr(error, "status_code", None)
        return {"status": "uncertain_provider_request", **(
            {"http_status": status_code} if type(status_code) is int and 300 <= status_code <= 599 else {}
        )}
    try:
        output = ADAPTER.output(response, offer_tool=offer_tool, selection_only=selection_only,
                                allow_reassessment=remediation, weight_only_evaluation=stability)
        if output["status"] == "prediction":
            if require_tool:
                raise InvalidResult("required_tool_missing")
            if stability:
                output = observation.validate_model(output["prediction"], tool, arm=arm)
            else:
                output = observation.validate_model(output["prediction"], tool)
    except InvalidResult as error:
        output = {"status": error.classification}
    except (KeyError, OverflowError, TypeError, ValueError, RecursionError):
        output = {"status": "malformed_provider_output"}
    ledger.settle(case, arm, stage, usage, output)
    return output


def run_model(ledger, observation, arm, transport):
    case = observation.task["case_id"]
    recorded = ledger.result(case, arm)
    if recorded is not None:
        return recorded
    start = time.monotonic()
    tool = None
    host_sleep = arm == "C" and requires_sleep_route(observation.packet)
    if host_sleep and (ledger.mode != "mock-pilot" or case not in ledger.host_sleep_cases):
        raise PermissionError("Host-selected sleep requires its frozen mock pilot schedule")
    result = ({"status": "tool", "operation": TOOL_NAME, "target": TOOL_TARGET} if host_sleep
              else dispatch(ledger, transport, observation, arm, 0))
    if result["status"] == "tool":
        try:
            tool = observation.tool(result["operation"], result["target"])
        except (ValueError, OSError, sqlite3.Error):
            result = {"status": "tool_failure",
                      "tool_request": {key: result[key] for key in ("operation", "target")}}
        else:
            result = dispatch(ledger, transport, observation, arm, 1, tool)
    elif result["status"] == "skip":
        result = {**dispatch(ledger, transport, observation, arm, 1), "tool_selection": "skip"}
    if tool is not None:
        result = {**result, "tool": tool}
    if host_sleep:
        result = {**result, "tool_selection": "host_selected_sleep"}
    if result["status"] == "completed":
        submission = {"version": protocol.VERSION, "worker": f"research-{arm.lower()}",
                      "provider": None, "elapsed_milliseconds": int((time.monotonic() - start) * 1000),
                      "predictions": result["prediction"]}
        result = {key: value for key, value in result.items() if key != "prediction"}
        result["submission"] = scoring.submission(submission, observation.task)
    ledger.finish(case, arm, result)
    return result


def mock_response(*, prediction=None, target=None, operation="coverage"):
    # Mock usage exercises the accounting path. It is not a measurement of tokenization.
    if prediction is not None:
        output = [{"type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": protocol.canonical(prediction)}]}]
    else:
        output = [{"type": "function_call", "name": operation,
                   "arguments": protocol.canonical({"target": target}), "call_id": "call_offline_example"}]
    return {"model": PILOT.identifier, "service_tier": "default", "id": "resp_offline_example",
            "status": "completed", "output": output, "usage": {
                "input_tokens": 6000, "output_tokens": 600, "total_tokens": 6600,
                "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 200},
            }}


def model_abstention(*, grounded_sleep=False):
    return {
        "relationship": {
            target: {"decision": "inconclusive", "effect": None, "evidence": None,
                     **({"estimate_method": None} if grounded_sleep else {}),
                     "confounders": dict.fromkeys(sorted(protocol.CONFOUNDERS), False)}
            for target in protocol.WINDOWS
        },
        "change": {"decision": "inconclusive", "split": None, "effect": None, "evidence": None},
    }


def demo_transport():
    def outcomes():
        for _ in range(2):
            if "tools" in transport.requests[-1]:
                yield mock_response(target="window_1")
            else:
                yield mock_response(prediction=model_abstention())

    transport = MockTransport(outcomes())
    return transport


def demo(workspace, dry_run=False):
    # No supplied dataset path, prompt, provider URL, tool names, or key are accepted.
    with public_panel() as paths:
        cases = [Observations(path) for path in paths]
        schedule = [(case.task["case_id"], arm) for case in cases for arm in ARMS]
        if dry_run:
            sizes = [len(protocol.canonical(ADAPTER.request(case.packet, offer_tool=True))) for case in cases]
            return {"mode": "dry_run", "cases": len(cases), "scheduled_runs": len(schedule),
                    "per_request_reservation": reservation(), "max_initial_request_bytes": max(sizes),
                    "max_mock_attempts": len(cases) * 3, "actual_api_calls": 0}
        workspace = Path(workspace)
        if workspace.resolve().is_relative_to(ROOT) or workspace.is_symlink():
            raise ValueError("Keep research artifacts outside the checkout")
        workspace.mkdir(mode=0o700, exist_ok=True)
        ledger = Ledger(workspace / "research.sqlite", Limits(), schedule,
                        {**provenance(), "observations": {case.task["case_id"]: protocol.digest(case.packet)
                                                        for case in cases}})
        for path, case in zip(paths, cases, strict=True):
            identity = case.task["case_id"]
            if ledger.result(identity, "A") is None:
                baseline = worker.execute(path, "evidence-aware")
                ledger.finish(identity, "A", {"status": "completed", "submission": baseline})
            for arm in ("B", "C"):
                if ledger.result(identity, arm) is not None:
                    continue
                run_model(ledger, case, arm, demo_transport())
        report = ledger.report()
        counts = Counter(item["result"]["status"] for item in report["runs"] if item["result"] is not None)
        return {"mode": report["mode"], "scheduled_runs": report["scheduled_runs"],
                "recorded_runs": report["recorded_runs"], "status_counts": dict(counts),
                "mock_attempts": len(report["attempts"]), "accounted_tokens": report["accounted_tokens"],
                "accounted_cost_microusd": report["accounted_cost_microusd"],
                "actual_api_calls": 0, "actual_cost_microusd": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and args.workspace is None:
        parser.error("Supply an owner-only workspace outside the checkout")
    try:
        print(protocol.canonical(demo(args.workspace, args.dry_run)))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
