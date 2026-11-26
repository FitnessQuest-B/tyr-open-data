"""Operate the offline, source-bound TYR Brain Lab."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from tyr_brain_lab import analysis, store
from tyr_brain_lab.source import open_source


def wiki(lab, source):
    runs = store.inspect(lab, source)
    lines = [
        "# Personal knowledge review", "",
        f"Source profile `{source.manifest['profile']}`, SHA-256 `{source.manifest['sha256']}`.",
        "Findings are exploratory and describe the recorded evidence. Sensitivity ranges are block-deletion diagnostics.",
    ]
    for run in runs:
        saved = store.inspect(lab, source, run["run_key"])["result"]
        plan, assessment = run["plan"], run["assessment"]
        applicability = assessment["applicability"] if run["current"] else "historical"
        lines.extend([
            "", f"## {run['title']}", "",
            f"- Evidence decision `{assessment['decision']}` with `{assessment['claim_strength']}` claim strength.",
            f"- Applicability `{applicability}`.",
            f"- Plan `{plan['method']}` over {plan['start']} to {plan['end_exclusive']} exclusive.",
            f"- Observed coverage {saved['eligible_days']} of {saved['expected_days']} planned days.",
        ])
        if saved["effect"] is not None:
            lines.append(f"- Recorded difference {saved['effect']} {saved['unit']}.")
        if saved["sensitivity_range"]:
            low, high = saved["sensitivity_range"]
            lines.append(f"- Block-deletion range {low} to {high} {saved['unit']}.")
        lines.extend([
            "- Competing explanations include " + ", ".join(item.replace("_", " ") for item in saved["confounders"]) + ".",
            f"- Evaluation `{run['evaluation_uuid']}` and run `{run['run_key']}`.",
        ])
        if run["supersedes"]:
            lines.append(f"- Reassesses evaluation `{run['supersedes']}`.")
        for evidence in saved["evidence"]:
            lines.append(f"- `{evidence['role']}` evidence has {evidence['statistics']['n']} observations "
                         f"and fingerprint `{evidence['input_sha256']}`.")
    return "\n".join(lines) + "\n"


def dates(parser):
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True, help="Exclusive civil date")


def source_command(commands, name):
    sub = commands.add_parser(name)
    sub.add_argument("source", type=Path)
    return sub


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("discover", "describe", "scan-baseline"):
        sub = source_command(commands, name)
        if name != "discover":
            sub.add_argument("--metric", choices=analysis.METRICS, required=True)
            dates(sub)

    propose = commands.add_parser("propose")
    propose.add_argument("--method", choices=analysis.METHODS, required=True)
    propose.add_argument("--metric", choices=analysis.METRICS)
    dates(propose)
    propose.add_argument("--split")
    propose.add_argument("--minimum-change-milli", type=int)
    propose.add_argument("--late-minute", type=int)

    read = source_command(commands, "analyze")
    read.add_argument("plan", type=Path)
    for name in ("init", "record", "status", "inspect", "replay", "wiki"):
        sub = source_command(commands, name)
        sub.add_argument("lab", type=Path)
        if name == "record":
            sub.add_argument("plan", type=Path)
            sub.add_argument("--hypothesis", help="Active hypothesis UUID for a later non-overlapping reassessment")
        if name in {"inspect", "replay"}:
            sub.add_argument("--run", required=name == "replay")

    args = parser.parse_args()
    try:
        if args.command == "propose":
            metric = args.metric or ("total_sleep_minutes" if args.method == "late-caffeine-sleep" else "body_weight")
            result = analysis.config(args.method, metric, args.start, args.end, args.split,
                                     args.minimum_change_milli, args.late_minute)
        else:
            with open_source(args.source) as source:
                result = dispatch(args, source)
        if args.command == "wiki":
            print(result, end="")
        else:
            print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
    except (ValueError, OSError, sqlite3.Error, OverflowError) as error:
        parser.exit(1, f"{error}\n")


def dispatch(args, source):
    command = args.command
    if command == "discover":
        return analysis.discover(source)
    if command in {"describe", "scan-baseline"}:
        method = analysis.describe if command == "describe" else analysis.scan_baseline
        return method(source, args.metric, args.start, args.end)
    if command in {"analyze", "record"}:
        plan = analysis.check_plan(json.loads(args.plan.read_text(encoding="utf-8")))
        if command == "analyze":
            return analysis.analyze(source, plan)
        return store.record(args.lab, source, plan, args.hypothesis)
    if command == "inspect":
        return store.inspect(args.lab, source, args.run)
    if command == "replay":
        return store.replay(args.lab, source, args.run)
    if command == "wiki":
        return wiki(args.lab, source)
    return (store.initialize if command == "init" else store.status)(args.lab, source)


if __name__ == "__main__":
    main()
