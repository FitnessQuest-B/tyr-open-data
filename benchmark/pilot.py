"""Prepare and evaluate the private benchmark pilot. Execution stays in the runner."""

import argparse
import hashlib
import json
import os
import random
import secrets
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from statistics import fmean

import bench  # Sets up imports for the standalone generator tools.
import protocol
import scoring
from generate_synthetic import separated_roots, verify_bundle
from pilot_design import FAMILIES, LABELS, expected, make_case, task_record
from synthetic_storage import build_records

SUITE_VERSION = 3
SCORING_VERSION = 4
PILOT_CASES = 48
LEAKAGE_LIMIT = 0.53
DEVELOPMENT_SEED = hashlib.sha256(b"TYR public development suite v3").digest()
REASSESSMENT_DIRECTIONS = ("supported_to_notSupported", "notSupported_to_supported")


def write_json(path, value):
    with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        stream.write(protocol.canonical(value) + "\n")


def prepare(workspace, *, development=False, seed_file=None):
    master = DEVELOPMENT_SEED if development else secrets.token_bytes(32)
    if seed_file is not None:
        if development:
            raise ValueError("Development cases use the public development seed")
        master = bytes.fromhex(seed_file.read_text().strip())
        if len(master) != 32:
            raise ValueError("Replay needs a private 32-byte hexadecimal seed")
    agent, evaluator = separated_roots(workspace / "agent", workspace / "evaluator")
    workspace = agent.parent
    workspace.mkdir(mode=0o700)
    try:
        agent.mkdir(mode=0o700)
        evaluator.mkdir(mode=0o700)
        bindings = {}
        for family in FAMILIES:
            for replica in range(2 if development else 8):
                identifier, first, days, windows, latent = make_case(master, family, replica)
                packet = agent / identifier
                packet.mkdir(mode=0o700)
                seq = packet / "records.sqlite"
                build_records(seq, days)
                verified = verify_bundle(packet)
                source_hash = verified["sha256"]
                task = task_record(identifier, first, len(days), windows, source_hash)
                answer = {"latent": latent, "expected": expected(seq, task, latent)}
                write_json(evaluator / (identifier + ".json"), answer)
                write_json(packet / "task.json", task)
                seq.chmod(0o444)
                (packet / "task.json").chmod(0o444)
                protocol.read_packet(packet)
                bindings[identifier] = {
                    "task_sha256": protocol.digest(task), "source_sha256": source_hash,
                    "truth_sha256": protocol.digest(answer),
                }
        index = {"suite_version": SUITE_VERSION, "development": development,
                 "master_seed": master.hex(), "cases": bindings}
        write_json(evaluator / "index.json", index)
    except BaseException:
        shutil.rmtree(workspace)
        raise
    return {"suite_version": SUITE_VERSION, "development": development, "cases": len(bindings)}


def suite_index(workspace):
    agent, evaluator = separated_roots(workspace / "agent", workspace / "evaluator")
    index = protocol.read_json(evaluator / "index.json", max_bytes=2 * 1024**2)
    cases = index["cases"]
    size = 12 if index["development"] else PILOT_CASES
    if (index["suite_version"] not in (2, SUITE_VERSION) or len(cases) != size
            or set(cases) != {path.name for path in agent.iterdir()}):
        raise ValueError("Not a complete supported pilot suite")
    return agent, evaluator, index


def load(workspace):
    agent, evaluator, index = suite_index(workspace)
    cases = index["cases"]
    for identifier, binding in sorted(cases.items()):
        task, data = protocol.read_packet(agent / identifier)
        truth = protocol.read_json(evaluator / (identifier + ".json"))
        if (protocol.digest(task) != binding["task_sha256"] or task["source_sha256"] != binding["source_sha256"]
                or protocol.digest(truth) != binding["truth_sha256"]):
            raise ValueError("Frozen case binding failed")
        yield task, data, truth


def macro_recall(pairs):
    counts = Counter(label for label, _ in pairs)
    return round(fmean(sum(actual == predicted == label for actual, predicted in pairs) / count
                       for label, count in counts.items()), 6)


def audit(workspace):
    _, _, suite = suite_index(workspace)
    rows = []
    qualifying = Counter(dict.fromkeys(REASSESSMENT_DIRECTIONS, 0))
    for index, (task, database, truth) in enumerate(load(workspace)):
        gold = truth["expected"]
        if expected(database, task, truth["latent"]) != gold:
            raise ValueError("Frozen truth disagrees with emitted observations")
        if truth["latent"]["family"] == "changing":
            for before, after in transitions(gold, "decision"):
                qualifying[before[1] + "_to_" + after[1]] += 1
        for position, window in enumerate(task["relationship"]):
            start, end = map(protocol.civil, (window["start"], window["end"]))
            duration = (end - start).days
            band = 0 if duration <= 55 else 1 if duration <= 64 else 2
            features = (position, band, (start.month - 1) // 3)
            row = gold["relationship"][window["id"]]
            adequate = not {"paired_coverage", "common_support"} & set(row["adequacy"]["reasons"])
            rows.append((index, features, row["decision"], adequate))
    distributions = {
        axis: [dict(Counter(label for _, features, label, _ in rows if features[dimension] == key))
               for key in range(3)]
        for axis, dimension in (("window_position", 0), ("duration_band", 1))
    }
    calendar_only = []
    for case, features, label, _ in rows:
        similar = [other for index, observed, other, _ in rows if index != case and observed == features]
        fallback = [other for index, observed, other, _ in rows if index != case and observed[:2] == features[:2]]
        pool = similar or fallback or [other for index, _, other, _ in rows if index != case]
        counts = Counter(pool)
        calendar_only.append((label, max(LABELS, key=lambda choice: (counts[choice], choice))))
    metadata_accuracy = macro_recall(calendar_only)
    coverage_accuracy = macro_recall([(label, "notSupported" if adequate else "inconclusive")
                                     for _, _, label, adequate in rows])
    minimum = 1 if suite["development"] else 4
    reassessment_passed = min(qualifying.values()) >= minimum
    return {
        "suite_version": suite["suite_version"], "windows": len(rows),
        "bindings_sha256": protocol.digest(suite["cases"]),
        "layout_macro_recall": metadata_accuracy, "coverage_only_macro_recall": coverage_accuracy,
        "layout_limit": LEAKAGE_LIMIT, "label_counts": dict(Counter(row[2] for row in rows)),
        "distributions": distributions,
        "reassessment_targets": dict(qualifying), "minimum_per_reassessment_direction": minimum,
        "reassessment_coverage_passed": reassessment_passed,
        "passed": metadata_accuracy <= LEAKAGE_LIMIT
        and all(set(counts) == set(LABELS)
                for values in distributions.values() for counts in values)
        and (suite["suite_version"] == 2 or reassessment_passed),
    }


def abstain(task):
    return {"version": protocol.VERSION, "worker": "always-abstain", "provider": None, "elapsed_milliseconds": 0,
            "predictions": {"version": protocol.VERSION, "case_id": task["case_id"],
                            "relationship": {key: {"decision": "inconclusive", "claim_type": "association",
                                                   "effect": None, "references": [], "confounders": []}
                                             for key in protocol.WINDOWS},
                            "change": {"decision": "inconclusive", "claim_type": "descriptive",
                                       "effect": None, "split": None, "references": []}}}


def transitions(case, decision_key):
    decisive = [(key, case["relationship"][key][decision_key]) for key in protocol.WINDOWS
                if case["relationship"][key][decision_key] in {"supported", "notSupported"}]
    return {(before, after) for before, after in zip(decisive, decisive[1:]) if before[1] != after[1]}


def score_subset(scored, reference):
    attempts = len(reference)
    rows = [window for case in scored for window in case["relationship"].values()]
    weights = [case["change"] for case in scored]
    labels = Counter(window["expected"] for case in reference for window in case["relationship"].values())
    qualified = sum(row["correct"] and row["expected"] == "supported" for row in rows)
    errors = [row["effect_absolute_error_minutes"] for row in rows if row["effect_absolute_error_minutes"] is not None]
    breakpoints = [row["breakpoint_absolute_error_days"] for row in weights
                   if row["breakpoint_absolute_error_days"] is not None]
    reassessment = Counter(targets=sum(len(transitions(case, "expected")) for case in reference))
    for case in scored:
        actual = transitions(case, "expected")
        assessed = transitions(case, "effective_decision")
        reassessment["recovered"] += len(actual & assessed)
        reassessment["wrong_direction_or_false"] += len(assessed - actual)
    return {
        "attempted_cases": attempts, "completed_cases": len(scored),
        "relationship_targets": attempts * 3,
        "relationship_label_counts": dict(labels),
        "relationship_correct": sum(row["correct"] for row in rows),
        "qualified_recovery": qualified,
        "false_positives": sum(row["expected"] == "notSupported" and row["submitted"] == "supported" for row in rows),
        "false_negatives": labels["supported"] - qualified,
        "correct_abstentions": sum(row["correct"] and row["expected"] == "inconclusive" for row in rows),
        "invalid_effect_or_evidence": sum(row["effective_decision"] in {"invalid_effect", "invalid_evidence"}
                                          for row in rows + weights),
        "unsupported_causal_claims": sum(row["unsupported_causal"] for row in rows + weights),
        "weight_correct": sum(row["correct"] for row in weights),
        "weight_false_alarms": sum(row["expected"] == "no_change" and row["submitted"] == "change" for row in weights),
        "weight_correct_abstentions": sum(row["correct"] and row["expected"] == "inconclusive" for row in weights),
        "weight_label_counts": dict(Counter(case["change"]["expected"] for case in reference)),
        "mean_absolute_observable_effect_error": round(fmean(errors), 6) if errors else None,
        "mean_breakpoint_error_days": round(fmean(breakpoints), 6) if breakpoints else None,
        "traceable_decisive_claims": sum(row["submitted"] != "inconclusive" and row["evidence"]["traceable"]
                                        and not row["evidence"]["invalid_references"] for row in rows + weights),
        "observable_confounder_evidence": sum(case.get("training_evidence", 0) for case in scored),
        "reassessment": dict(reassessment),
    }


def interval(scores):
    stream = random.Random(31257)
    draws = sorted(fmean(stream.choices(scores, k=len(scores))) for _ in range(2000))
    return [round(draws[50], 6), round(draws[1949], 6)]


def read_result(folder, task, database):
    run = protocol.read_json(folder / "run.json")
    if run["case_id"] != task["case_id"]:
        raise ValueError("Runner receipt has the wrong case binding")
    status = run["status"]
    if status == "completed":
        hashes = [protocol.hash_file(database.parent / "task.json"), task["source_sha256"],
                  protocol.hash_file(bench.ROOT / "benchmark/task.md")]
        if run["sha256"] != hashes:
            raise ValueError("Runner receipt has the wrong packet or task contract hash")
        submission = scoring.submission(protocol.read_json(folder / "submission.json"), task)
        if submission["provider"] is not None:
            raise ValueError("Expected a local offline submission")
        return run, submission
    if status not in {"timeout", "output_limit", "invalid_submission", "agent_failure", "environment_failure"}:
        raise ValueError("Unknown runner result")
    if (folder / "submission.json").exists():
        raise ValueError("A failed run contains a submission")
    return run, None


def training_evidence(database, task, gold, result):
    """Count named training confounders supported by cited positive-dose rows."""
    credited = 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        for window in task["relationship"]:
            key = window["id"]
            finding = result["predictions"]["relationship"][key]
            if not all("training_day" in names for names in (gold["relationship"][key]["confounders"],
                                                             finding["confounders"])):
                continue
            roles = set()
            for ref in finding["references"]:
                if ref["table"] == "daily_snapshot" and ref["column"] == "workout_session_count":
                    record = db.execute("""
                        SELECT workout_session_count > 0
                          FROM daily_snapshot
                         WHERE id = ? AND snapshot_date >= ? AND snapshot_date < ?
                           AND workout_session_count >= 0 AND caffeine_mg > 0
                    """, (ref["row_id"], window["start"], window["end"])).fetchone()
                    if record:
                        roles.add(record[0])
            credited += roles == {0, 1}
    return credited


def score(workspace, runs):
    _, _, suite = suite_index(workspace)
    cases = list(load(workspace))
    ids = {task["case_id"] for task, _, _ in cases}
    output = {}
    statuses, times = Counter(), []
    families = {family: [] for family in FAMILIES}
    family_references = {family: [] for family in FAMILIES}
    assessed, baseline, comparison = [], [], []
    repeated, matches = 0, 0
    frozen = set()
    if {path.name for path in (runs / "first").iterdir()} != ids:
        raise ValueError("Expected a runner receipt for every frozen case")
    replays = {path.name for path in (runs / "replay").iterdir()}
    if not replays or replays - ids:
        raise ValueError("Expected independent replay receipts for a subset of this suite")
    for task, data, truth in cases:
        identifier = task["case_id"]
        family = truth["latent"]["family"]
        gold = truth["expected"]
        run, result = read_result(runs / "first" / identifier, task, data)
        statuses[run["status"]] += 1
        frozen.add((run["profile_sha256"], run["image"]))
        reference = scoring.score_case(data, task, gold, abstain(task))
        baseline.append(reference)
        family_references[family].append(reference)
        case = None
        if result is not None:
            case = scoring.score_case(data, task, gold, result)
            case["training_evidence"] = training_evidence(data, task, gold, result)
            assessed.append(case)
            families[family].append(case)
            times.append(run["elapsed_milliseconds"])
        if identifier in replays:
            second_run, second = read_result(runs / "replay" / identifier, task, data)
            frozen.add((second_run["profile_sha256"], second_run["image"]))
            repeated += 1
            matches += result is not None and second is not None and result["predictions"] == second["predictions"]
        correct = lambda item: (sum(row["correct"] for row in item["relationship"].values()) + item["change"]["correct"]) / 4
        # Failures are zero credit, including on deliberately insufficient cases.
        comparison.append((correct(case) if case else 0.0) - correct(reference))
        output[identifier] = {"status": run["status"], "score": case, "always_abstain": reference}
    if len(frozen) != 1:
        raise ValueError("The pilot must use one pinned runner profile and one agent image")
    result = {
        "suite_version": suite["suite_version"], "scoring_version": SCORING_VERSION, "purpose": "method_validation",
        "method": score_subset(assessed, baseline), "always_abstain": score_subset(baseline, baseline),
        "by_family": {family: score_subset(families[family], family_references[family]) for family in FAMILIES},
        "statuses": dict(statuses), "replay": {"attempted": repeated, "matched": matches},
        "mean_runtime_milliseconds": round(fmean(times), 2) if times else None,
        "mean_case_credit_difference": round(fmean(comparison), 6),
        "case_bootstrap_95_interval": interval(comparison),
    }
    return result, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("workspace", type=Path)
    build.add_argument("--development", action="store_true")
    build.add_argument("--seed-file", type=Path)
    review = commands.add_parser("audit")
    review.add_argument("workspace", type=Path)
    review.add_argument("--output", type=Path)
    evaluate = commands.add_parser("score")
    evaluate.add_argument("workspace", type=Path)
    evaluate.add_argument("runs", type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.workspace, development=args.development, seed_file=args.seed_file)
        elif args.command == "audit":
            result = audit(args.workspace)
            if args.output:
                write_json(args.output, result)
            if not result["passed"]:
                parser.exit(1, "The suite requires review against the layout and reassessment checks.\n")
        else:
            _, evaluator = separated_roots(args.workspace / "agent", args.workspace / "evaluator")
            if args.output.resolve().parent != evaluator:
                raise ValueError("Write detailed scores inside the private evaluator directory")
            result, details = score(args.workspace, args.runs)
            write_json(args.output, {"summary": result, "cases": details})
        # Explicit CLI output contains aggregate counts only. Files remain evaluator-local.
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
