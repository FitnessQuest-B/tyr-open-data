"""Run the separately authorized, one-case Phase 4B Responses smoke test."""

import argparse
import os
import re
import stat
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import run as broker
from budget import Ledger, RERUN_LIMITS, RERUN_OUTPUT_LIMITS, SMOKE_LIMITS, SMOKE_STAGES, json_result, verify_live_schedule
from observations import Observations, public_panel
from responses import PILOT, open_sdk_transport

CACHED_INPUT_RATE = 75_000
MAX_CREDENTIAL_BYTES = 1024
KEY_LINE = re.compile(rb"OPENAI_API_KEY=(sk-[A-Za-z0-9_-]{20,})\r?\n?")


def validate_workspace(path):
    if path.resolve().is_relative_to(broker.ROOT) or path.is_symlink():
        raise ValueError("Keep the live-smoke artifacts outside the checkout")


@contextmanager
def project_transport(path):
    if path.resolve().is_relative_to(broker.ROOT) or path.parent.is_symlink():
        raise ValueError("Keep the project credential outside the checkout")
    if any(name.startswith("OPENAI_") for name in os.environ):
        raise ValueError("Use a dedicated process without inherited OpenAI settings")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > MAX_CREDENTIAL_BYTES):
            raise ValueError("Expected an owner-only credential file")
        match = KEY_LINE.fullmatch(source.read(MAX_CREDENTIAL_BYTES + 1))
    if match is None:
        raise ValueError("The approved credential file has an unexpected format")
    os.environ["OPENAI_API_KEY"] = match.group(1).decode("ascii")
    try:
        with open_sdk_transport(authorized=True) as transport:
            yield transport
    finally:
        os.environ.pop("OPENAI_API_KEY", None)


def summarize(ledger):
    report = ledger.report()
    for attempt in report["attempts"]:
        attempt["usage"] = json_result(attempt["usage"])
        attempt["result"] = json_result(attempt["result"])
    usage_rows = [attempt["usage"] for attempt in report["attempts"] if attempt["usage"] is not None]
    totals = {key: sum(row[key] for row in usage_rows) for key in (
        "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens")}
    cached = totals["cached_input_tokens"]
    cost = Decimal((totals["input_tokens"] - cached) * PILOT.input_rate
                   + cached * CACHED_INPUT_RATE + totals["output_tokens"] * PILOT.output_rate) / 10**12
    return {
        **report, "model": PILOT.identifier, "max_requests": ledger.limits.attempts, "max_retries": 0,
        "authorized_microusd": ledger.limits.experiment_microusd,
        "attempted_requests": len(report["attempts"]), "responses_with_usage": len(usage_rows),
        "usage_totals": totals, "metered_cost_usd": format(cost, "f"),
        "unresolved_reservation_microusd": sum(
            a["reserved_cost_microusd"] for a in report["attempts"] if a["status"] != "settled"),
    }


def smoke(workspace, transport, *, rerun=False):
    validate_workspace(workspace)
    limits = RERUN_LIMITS if rerun else SMOKE_LIMITS
    output_caps = tuple(RERUN_OUTPUT_LIMITS[stage] if rerun else PILOT.output_limit for stage in SMOKE_STAGES)
    verify_live_schedule(limits, output_caps, 1)
    with public_panel() as paths:
        path = paths[0]
        observation = Observations(path)
        case = observation.task["case_id"]
        ledger = Ledger(
            workspace / "research.sqlite", limits, [(case, arm) for arm in ("A", "C")],
            {**broker.provenance(), "observation_sha256": broker.protocol.digest(observation.packet),
             "purpose": "phase-4b-one-public-case", "service_tier": "default"},
            mode="live-smoke-rerun" if rerun else "live-smoke")
        baseline = broker.worker.execute(path, "evidence-aware")
        ledger.finish(case, "A", {"status": "completed", "submission": baseline})
        broker.run_model(ledger, observation, "C", transport)
        return summarize(ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-phase-4b", action="store_true", required=True)
    parser.add_argument("--higher-output-cap", action="store_true")
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_workspace(args.workspace)
        # An approved invocation only gets one ledger. Reusing the directory cannot dispatch again.
        args.workspace.mkdir(mode=0o700)
        with project_transport(args.credential_file) as transport:
            receipt = smoke(args.workspace, transport, rerun=args.higher_output_cap)
        fd = os.open(args.workspace / "summary.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(broker.protocol.canonical(receipt) + "\n")
        print(broker.protocol.canonical({
            key: receipt[key] for key in (
                "model", "authorized_microusd", "attempted_requests", "responses_with_usage",
                "usage_totals", "metered_cost_usd", "unresolved_reservation_microusd")
        }))
    except Exception as error:
        # Do not print exceptions that might contain provider request material.
        parser.exit(1, f"Live smoke halted ({type(error).__name__}). Inspect the local ledger.\n")


if __name__ == "__main__":
    main()
