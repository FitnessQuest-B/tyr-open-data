"""Run the reviewed public Phase 4C batch with a bounded provider schedule."""

import argparse
import hashlib
import json
import os
import sqlite3
import stat
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import run as broker
from budget import BATCH_CASES, BATCH_LIMITS, RERUN_OUTPUT_LIMITS, Ledger, json_result, verify_live_schedule
from observations import Observations
from providers import MockTransport
from responses import (
    REASSESSMENT_PROMPT_VERSION, REASSESSMENT_SELECTION_VERSION, SDKTransport,
    SELECTION_VERSION, STABILITY_PROMPT_VERSION, WEIGHT_SELECTION_VERSION,
)
from sleep_evidence import (
    ACROSS_WINDOW_METHOD, COMPARABILITY_METHOD, ENDPOINT_METHOD, GROUNDED_TOOL_VERSION,
    PACKET_VERSION as REMEDIATED_PACKET_VERSION, PRECEDENCE_METHOD, ROUTING_METHOD,
    STABILITY_METHOD, STABILITY_PACKET_VERSION,
    STABILITY_SUMMARY_VERSION, SUMMARY_VERSION, THRESHOLD_METHOD, TOOL_NAME, TOOL_TARGET,
    TOOL_VERSION as REASSESSMENT_TOOL_VERSION, ReassessmentObservations, recommended_tool, requires_sleep_route,
)
from weight_evidence import WEIGHT_METHOD, WEIGHT_VERIFICATION_METHOD, required_weight_output
from smoke import project_transport, summarize

APPROVED_MANIFEST_SHA256 = "c44ff92e5f6efb589ed6c651c24532f9990347ebb006cebf9916c77cdf2ba78c"
APPROVED_REMEDIATION_SHA256 = "0c883204e1b8c66b5a64f6d106979c175cc0b92c8c4b14b167e62e4eea0cfb55"
BASELINE_COMMIT = "ff5ec5367ceaccb8373f3cf708b9f5a9850669d5"
STAGES = (("B", 0), ("C", 0), ("C", 1))
MAX_SQLITE_BYTES = 16 * 1024**2
BATCH_UPDATED_FILES = {
    "benchmark/research/budget.py", "benchmark/research/responses.py", "benchmark/research/run.py",
}


def _read_regular(path, limit):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("Expected a bounded regular pilot input file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Pilot input exceeds its size limit")
    return data


def _manifest(path, current):
    raw = _read_regular(path, broker.protocol.MAX_SUBMISSION_SIZE)
    if not raw.endswith(b"\n") or hashlib.sha256(raw[:-1]).hexdigest() != APPROVED_MANIFEST_SHA256:
        raise ValueError("Pilot manifest differs from the reviewed public batch")
    value = json.loads(raw)
    protocol = broker.protocol
    protocol.fields(value, "baseline_commit cases ordered_cases provenance public_only status")
    if value["public_only"] is not True or value["baseline_commit"] != BASELINE_COMMIT:
        raise ValueError("Pilot manifest must bind the approved public batch and baseline")
    order = value["ordered_cases"]
    if (type(order) is not list or len(order) != BATCH_CASES
            or not all(type(case) is str and protocol.ID.fullmatch(case) for case in order)
            or len(set(order)) != BATCH_CASES
            or type(value["cases"]) is not dict or set(order) != set(value["cases"])):
        raise ValueError("Pilot manifest requires eight unique case identities")
    prior = value["provenance"]
    if any(prior[key] != current[key] for key in ("packet_version", "prompt_version", "tool_version",
                                                 "adapter", "scoring_version")):
        raise ValueError("Pilot request or scoring contract changed since qualification")
    for name, digest in prior["files"].items():
        if name not in BATCH_UPDATED_FILES and current["files"].get(name) != digest:
            raise ValueError("Worker, scorer or observation code changed since qualification")
    return value


@contextmanager
def admit(manifest_path, packet_root, current):
    manifest = _manifest(manifest_path, current)
    if (packet_root.is_symlink() or not packet_root.is_dir()
            or {entry.name for entry in packet_root.iterdir()} != set(manifest["ordered_cases"])):
        raise ValueError("Pilot packet root must contain exactly the approved case directories")
    protocol = broker.protocol
    with TemporaryDirectory(prefix="tyr-public-pilot-") as scratch:
        staged = []
        for case in manifest["ordered_cases"]:
            source = packet_root / case
            binding = manifest["cases"][case]
            protocol.fields(binding, "task_sha256 source_sha256 observation_sha256")
            if (source.is_symlink() or not source.is_dir()
                    or {entry.name for entry in source.iterdir()} != {"task.json", "records.sqlite"}):
                raise ValueError("Pilot packet may contain only the approved task and records files")
            task_bytes = _read_regular(source / "task.json", protocol.MAX_SUBMISSION_SIZE)
            data_bytes = _read_regular(source / "records.sqlite", MAX_SQLITE_BYTES)
            # Both inputs are authenticated before loading the staged SQLite projection.
            if (not task_bytes.endswith(b"\n")
                    or hashlib.sha256(task_bytes[:-1]).hexdigest() != binding["task_sha256"]
                    or hashlib.sha256(data_bytes).hexdigest() != binding["source_sha256"]):
                raise ValueError("Frozen pilot task or records fingerprint differs")
            destination = Path(scratch) / case
            destination.mkdir(mode=0o700)
            for name, data in (("task.json", task_bytes), ("records.sqlite", data_bytes)):
                path = destination / name
                path.write_bytes(data)
                path.chmod(0o400)
            observation = Observations(destination)
            if protocol.digest(observation.packet) != binding["observation_sha256"]:
                raise ValueError("Compiled pilot observations differ from the reviewed packet")
            staged.append(observation)
        yield tuple(staged)


def _mock_transport(arm, index, *, remediation=False, observation=None):
    prediction = broker.model_abstention(grounded_sleep=observation is not None)
    final = broker.mock_response(prediction=prediction)
    if arm == "B":
        return MockTransport([final])
    if observation is not None:
        choice = recommended_tool(observation.packet)
        selection = (broker.mock_response(operation=choice[0], target=choice[1]) if choice else
                     broker.mock_response(prediction={"action": "skip"}))
        tool = observation.tool(*choice) if choice == ("evaluate", "weight") else None
        prediction["change"] = required_weight_output(observation.packet, tool, arm)
        final = broker.mock_response(prediction=prediction)
        if requires_sleep_route(observation.packet):
            return MockTransport([final])
    elif remediation and index < 4:
        selection = broker.mock_response(target=TOOL_TARGET, operation=TOOL_NAME)
    elif index % 2:
        selection = broker.mock_response(prediction={"action": "skip"})
    else:
        selection = broker.mock_response(target="weight", operation="evaluate")
    selection["usage"].update(output_tokens=64, total_tokens=6064)
    selection["usage"]["output_tokens_details"]["reasoning_tokens"] = 32
    return MockTransport([selection, final])


def _stage_statuses(report, schedule):
    attempts = {(a["case_id"], a["arm"], a["stage"]): a for a in report["attempts"]}
    outcomes = {(row["case_id"], row["arm"]): row["result"] for row in report["runs"]}
    stages = []
    for case, arm, stage in schedule:
        attempt = attempts.get((case, arm, stage))
        if attempt is not None:
            status = json_result(attempt["result"])["status"] if attempt["status"] == "settled" else attempt["status"]
        else:
            outcome = outcomes[case, arm]
            final = outcome["status"]
            initial = attempts.get((case, arm, 0))
            selection = json_result(initial["result"]) if initial is not None else None
            if (arm, stage) == ("C", 0) and outcome.get("tool_selection") == "host_selected_sleep":
                status = "host_selected_sleep"
            elif stage == 1 and selection is not None and selection["status"] not in ("tool", "skip"):
                status = "not_run_selection_failed"
            else:
                status = final if final.startswith("not_run_") else "not_run_" + final
        stages.append({"case_id": case, "arm": arm, "stage": stage, "status": status})
    return stages


def run_batch(manifest_path, packet_root, workspace, *, mock_transport=None, live_transport=None,
              remediation=False, approved_remediation=False, stability=False):
    live = live_transport is not None
    if stability and (live or remediation or approved_remediation):
        raise PermissionError("Window stability is a separate offline mock mode")
    if live and remediation and not approved_remediation:
        raise PermissionError("Use offline verification or explicit authorization for live remediation")
    if approved_remediation and not (live and remediation):
        raise PermissionError("Live remediation authorization applies only to the remediated live batch")
    if live and type(live_transport) is not SDKTransport:
        raise PermissionError("Live pilot requires the dedicated host SDK transport")
    if live:
        verify_live_schedule(BATCH_LIMITS, tuple(RERUN_OUTPUT_LIMITS.values()), BATCH_CASES)
    if (workspace.resolve().is_relative_to(broker.ROOT) or workspace.is_symlink()
            or workspace.resolve().is_relative_to(packet_root.resolve())):
        raise ValueError("Use a fresh results workspace outside the checkout and packet root")
    current = broker.provenance()
    reassessment = remediation or stability
    with admit(manifest_path, packet_root, current) as cases:
        scope_info = {}
        host_sleep_cases = ()
        mode = "live-pilot" if live else "mock-pilot"
        if reassessment:
            cases = tuple(ReassessmentObservations(case, stability=stability) for case in cases)
            scope = {
                "packet_version": STABILITY_PACKET_VERSION if stability else REMEDIATED_PACKET_VERSION,
                "summary_version": STABILITY_SUMMARY_VERSION if stability else SUMMARY_VERSION,
                "prompt_version": STABILITY_PROMPT_VERSION if stability else REASSESSMENT_PROMPT_VERSION,
                "selection_version": WEIGHT_SELECTION_VERSION if stability else REASSESSMENT_SELECTION_VERSION,
                "tool_version": GROUNDED_TOOL_VERSION if stability else REASSESSMENT_TOOL_VERSION,
                "observation_sha256": {case.task["case_id"]: broker.protocol.digest(case.packet) for case in cases},
            }
            if live:
                if broker.protocol.digest(scope) != APPROVED_REMEDIATION_SHA256:
                    raise ValueError("Remediated payloads differ from the offline-reviewed scope")
                mode = "live-pilot-remediated"
            if stability:
                host_sleep_cases = tuple(case.task["case_id"] for case in cases if requires_sleep_route(case.packet))
                scope.update(endpoint_method=ENDPOINT_METHOD, stability_method=STABILITY_METHOD,
                             threshold_method=THRESHOLD_METHOD, weight_method=WEIGHT_METHOD,
                             weight_verification_method=WEIGHT_VERIFICATION_METHOD,
                             sleep_tool_estimate_method=ACROSS_WINDOW_METHOD,
                             comparability_method=COMPARABILITY_METHOD, routing_method=ROUTING_METHOD,
                             sleep_precedence_method=PRECEDENCE_METHOD, host_sleep_cases=sorted(host_sleep_cases))
                scope_info = {"offline_stability": scope}
            else:
                scope_info = {"remediation" if live else "offline_remediation": scope}
        workspace.mkdir(mode=0o700)
        order = [case.task["case_id"] for case in cases]
        ledger = Ledger(
            workspace / "research.sqlite", BATCH_LIMITS,
            [(case, arm) for case in order for arm in broker.ARMS],
            {**current, "admission_sha256": APPROVED_MANIFEST_SHA256,
             "selection_version": (scope["selection_version"] if reassessment else SELECTION_VERSION),
             **scope_info}, mode=mode, host_sleep_cases=host_sleep_cases)
        for index, case in enumerate(cases):
            identity = case.task["case_id"]
            baseline = broker.worker.execute(case.database.parent, "evidence-aware")
            ledger.finish(identity, "A", {"status": "completed", "submission": baseline})
            for arm in ("B", "C"):
                if live:
                    transport = live_transport
                elif mock_transport is not None:
                    transport = mock_transport(arm, index)
                else:
                    transport = _mock_transport(arm, index, remediation=reassessment,
                                                observation=case if stability else None)
                broker.run_model(ledger, case, arm, transport)
        report = ledger.report()
        stages = _stage_statuses(report, [(case, arm, stage) for case in order for arm, stage in STAGES])
        if live:
            report = summarize(ledger)
    return {
        **report, "admission_sha256": APPROVED_MANIFEST_SHA256, "scheduled_model_stages": stages,
        **scope_info,
        "status_counts": dict(Counter(row["result"]["status"] for row in report["runs"])),
        "stage_status_counts": dict(Counter(row["status"] for row in stages)),
        "hard_cap_microusd": BATCH_LIMITS.experiment_microusd,
        "request_limit": BATCH_LIMITS.attempts, "max_retries": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline-remediation", action="store_true")
    mode.add_argument("--offline-stability", action="store_true")
    mode.add_argument("--approved-live-phase-4c", action="store_true")
    mode.add_argument("--approved-live-phase-4c-remediation", action="store_true")
    parser.add_argument("--credential-file", type=Path)
    args = parser.parse_args()
    live = args.approved_live_phase_4c or args.approved_live_phase_4c_remediation
    if live != (args.credential_file is not None):
        parser.error("Live execution requires both explicit approval and the approved project credential file")
    if live:
        try:
            verify_live_schedule(BATCH_LIMITS, tuple(RERUN_OUTPUT_LIMITS.values()), BATCH_CASES)
        except ValueError as error:
            parser.error(str(error))
    try:
        if live:
            with project_transport(args.credential_file) as transport:
                report = run_batch(args.manifest, args.packets, args.workspace, live_transport=transport,
                                   remediation=args.approved_live_phase_4c_remediation,
                                   approved_remediation=args.approved_live_phase_4c_remediation)
        else:
            report = run_batch(args.manifest, args.packets, args.workspace, remediation=args.offline_remediation,
                               stability=args.offline_stability)
        fd = os.open(args.workspace / "summary.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(broker.protocol.canonical(report) + "\n")
        fields = ("mode", "admission_sha256", "recorded_runs", "status_counts", "stage_status_counts",
                  "accounted_cost_microusd", "hard_cap_microusd", "request_limit", "max_retries")
        fields += (("attempted_requests", "responses_with_usage", "usage_totals", "metered_cost_usd",
                    "unresolved_reservation_microusd") if live else ("actual_api_calls",))
        print(broker.protocol.canonical({key: report[key] for key in fields}))
    except (OSError, ValueError, sqlite3.Error) as error:
        if live:
            parser.exit(1, f"Live pilot halted ({type(error).__name__}). Inspect the local ledger.\n")
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
