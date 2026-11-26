"""Observation-only worker entry point. Receives one detached packet."""

import argparse
import json
import os
import sqlite3
import sys
import sysconfig
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "brain-lab"), str(ROOT / "tools")]
from tyr_brain_lab import analysis
from tyr_brain_lab.source import open_source

import protocol
from providers import Client, LocalAdapter, MockTransport, Policy, ResponsesAdapter

METHODS = ("deterministic", "mock-openai", "mock-local")


def _refs(evidence, fields):
    chosen = []
    for group in evidence:
        group_refs = []
        for ref in group["reference_rows"]:
            column = fields.get(ref["table"])
            if column and (ref.get("column") == column or column in ref.get("columns", ())):
                item = {"table": ref["table"], "row_id": ref["row_id"], "column": column}
                if item not in group_refs and sum(x["table"] == item["table"] for x in group_refs) < 2:
                    group_refs.append(item)
        chosen.extend(group_refs)
    return chosen


def _confounders(result):
    totals = {"training": Counter(), "quiet": Counter()}
    for stratum, arms in result["strata"].items():
        cell = totals[stratum.split("_")[0]]
        cell["late"] += arms["late"]
        cell["observed"] += arms["late"] + arms["early"]
    detected = []
    if all(cell["observed"] for cell in totals.values()):
        rates = [cell["late"] / cell["observed"] for cell in totals.values()]
        if abs(rates[0] - rates[1]) >= 0.18:
            detected.append("training_day")
    if result["different_logged_doses"]:
        detected.append("dose_size")
    if result["coverage_ratio"] < 0.75:
        detected.append("logging_gaps")
    return detected


def deterministic(task, source):
    findings = {}
    for window in task["relationship"]:
        plan = analysis.config("late-caffeine-sleep", "total_sleep_minutes", window["start"], window["end"])
        result = analysis.analyze(source, plan)
        findings[window["id"]] = {
            "decision": result["evidence_decision"], "claim_type": "association", "effect": result["effect"],
            "references": _refs(result["evidence"], {"daily_snapshot": "caffeine_last_dose_minute",
                                                     "daily_sleep": "total_minutes"}),
            "confounders": _confounders(result),
        }
    start, end = task["change"]["start"], task["change"]["end"]
    scan = analysis.scan_baseline(source, "body_weight", start, end)
    change = {"decision": "inconclusive", "effect": None, "references": [], "claim_type": "descriptive", "split": None}
    if scan["candidates"]:
        top = scan["candidates"][0]["split"]
        result = analysis.analyze(source, analysis.config("baseline-change", "body_weight", start, end, top))
        change.update(effect=result["effect"], references=_refs(result["evidence"], {"daily_snapshot": "body_weight"}))
        if result["evidence_decision"] == "supported":
            change.update(decision="change", split=top)
        elif result["evidence_decision"] == "notSupported":
            change["decision"] = "no_change"
    return {"version": protocol.VERSION, "case_id": task["case_id"], "relationship": findings, "change": change}


def _mock_response(method, task):
    prediction = {"version": protocol.VERSION, "case_id": task["case_id"],
                  "relationship": {key: {"decision": "inconclusive", "claim_type": "association",
                                         "effect": None, "references": [], "confounders": []}
                                   for key in protocol.WINDOWS},
                  "change": {"decision": "inconclusive", "claim_type": "descriptive",
                             "split": None, "effect": None, "references": []}}
    text = protocol.canonical(prediction)
    if method == "mock-openai":
        return ResponsesAdapter(), {
            "model": "mock-responses-v1", "status": "completed",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 188, "output_tokens": 96},
        }
    return LocalAdapter(), {"model": "mock-local-v1", "text": text, "prompt_tokens": 136, "generated_tokens": 96}


def _accounted_mock(method, task, source, ledger):
    adapter, payload = _mock_response(method, task)
    observations = {
        "task": task,
        "observed_sleep_counts": {
            window["id"]: analysis.describe(source, "total_sleep_minutes", window["start"], window["end"])["statistics"]
            for window in task["relationship"]
        },
    }
    model = payload["model"]
    ledger = Path(ledger).resolve()
    if ledger.is_relative_to(source.path.parent) or ledger.is_relative_to(ROOT):
        raise ValueError("Keep the mock request ledger outside the observation packet and source checkout")
    client = Client(ledger, Policy(max_attempts=60, max_total_tokens=500_000),
                    adapter, MockTransport([payload]))
    estimate = client.call(model, observations, dry_run=True)
    receipt = client.call(model, observations)
    prediction = json.loads(receipt.pop("text"))
    return prediction, {**receipt, "reserved_tokens": estimate["reserved_tokens"]}


def execute(packet, method, ledger=None):
    if method not in METHODS:
        raise ValueError("Choose a bundled offline worker")
    started = time.perf_counter_ns()
    task, database = protocol.read_packet(packet)
    with open_source(database) as source:
        if source.manifest["profile"] != "open_data_projection" or source.owner != 1:
            raise ValueError("Bundled workers admit synthetic benchmark projections only")
        if method == "deterministic":
            prediction, provider = deterministic(task, source), None
        elif ledger is not None:
            prediction, provider = _accounted_mock(method, task, source, ledger)
        else:
            with tempfile.TemporaryDirectory(prefix="tyr-mock-ledger-") as tmp:
                prediction, provider = _accounted_mock(method, task, source, Path(tmp) / "requests.sqlite")
    return {
        "version": protocol.VERSION,
        "worker": method, "predictions": protocol.validate_predictions(prediction, task), "provider": provider,
        "elapsed_milliseconds": (time.perf_counter_ns() - started) // 1_000_000,
    }



def _confine(packet, ledger):
    """Prevent accidental IO outside a bundled worker's declared file inputs."""
    packet = packet.resolve()
    ledger = ledger.resolve() if ledger else None
    data = packet / "records.sqlite"
    reads = {data, packet / "task.json", ROOT / "schema/versions/0.1.0/manifest.json"}
    writes = {ledger} if ledger else set()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()

    def enforce(event, args):
        if event.startswith(("socket.", "subprocess.", "ctypes.dlopen")) or event in {"os.system", "os.exec", "os.spawn"}:
            raise PermissionError("Network and subprocess access are outside the bundled worker scope")
        if event == "open" and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            flags = args[2]
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            installed = path.is_relative_to(stdlib) and "site-packages" not in path.relative_to(stdlib).parts
            if path not in (writes if writing else reads | writes) and (writing or not installed):
                raise PermissionError("Opened file is outside the worker packet scope")
        if event == "sqlite3.connect":
            uri = urlsplit(os.fsdecode(args[0]))
            if uri.scheme != "file":
                raise PermissionError("Worker SQLite connections use declared file URIs")
            path = Path(unquote(uri.path)).resolve()
            mode = parse_qs(uri.query).get("mode", [])
            if path != ledger and not (path == data and mode == ["ro"]):
                raise PermissionError("SQLite connection is outside the worker packet scope")

    sys.addaudithook(enforce)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--worker", choices=METHODS, default="deterministic")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--confined-inputs", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.confined_inputs:
            if args.worker != "deterministic" and args.ledger is None:
                raise ValueError("A confined mock worker needs a designated ledger")
            _confine(args.packet, args.ledger)
        print(protocol.canonical(execute(args.packet, args.worker, args.ledger)))
    except (OSError, ValueError, sqlite3.Error, TypeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
