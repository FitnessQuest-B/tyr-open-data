"""Prepare, audit and compare the two pinned workers on verification suite revision 4."""

import argparse
import json
import secrets
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import bench
import pilot
import protocol
import scoring
import reassessment_design as reassessment
import verification_design as original
from generate_synthetic import separated_roots, verify_bundle
from pilot_design import LABELS, task_record
from synthetic_storage import build_records
from verification_design import CASE_COUNT, CASE_COUNTS, REPLAY_FAMILIES, SUITE_VERSION, expected

SCORING_VERSION = 5
DIRECTIONS = {"sleep_loss": ("supported", "notSupported"), "sleep_gain": ("notSupported", "supported")}
TARGETS = {"weight_threshold": "inconclusive", "weight_gap": "inconclusive", "weight_step": "change",
           "weight_drift": "no_change", "weight_steady": "no_change", "weight_small": "no_change"}
MAX_INDEX_BYTES = 2 * 1024**2
DESIGNS = {4: original, 5: reassessment}
BASELINE_TAG = "b6bb54616f7a8c845a2d20e231523f720859a41e"


def design_sha256():
    return protocol.hash_file(Path(reassessment.__file__))


def prepare(workspace, *, development=False, seed_file=None, revision=4, calibration=None):
    design = DESIGNS[revision]
    if revision == 5 and not development:
        if (calibration is None or calibration.get("passed") is not True
                or calibration.get("design_sha256") != design_sha256()
                or calibration.get("source_sha256") != protocol.hash_file(Path(__file__))):
            raise ValueError("Qualify the exact revision 5 design on the public panel before freezing a private suite")
    if development and seed_file:
        raise ValueError("Development uses the public seed")
    master = (design.DEVELOPMENT_SEED if development else
              bytes.fromhex(seed_file.read_text().strip()) if seed_file else secrets.token_bytes(32))
    if len(master) != 32 or (not development and master in {d.DEVELOPMENT_SEED for d in DESIGNS.values()}):
        raise ValueError("A private suite needs a separate 32-byte seed")
    agent, evaluator = separated_roots(workspace / "agent", workspace / "evaluator")
    workspace = agent.parent
    workspace.mkdir(mode=0o700)
    try:
        agent.mkdir(mode=0o700)
        evaluator.mkdir(mode=0o700)
        bindings = {}
        for family, count in design.CASE_COUNTS.items():
            for replica in range(count):
                identifier, first, days, windows, mechanism = design.make_case(master, family, replica)
                packet = agent / identifier
                packet.mkdir(mode=0o700)
                database = packet / "records.sqlite"
                build_records(database, days)
                sha = verify_bundle(packet)["sha256"]
                task = task_record(identifier, first, len(days), windows, sha)
                gold = {"latent": mechanism, "expected": design.expected(database, task, mechanism)}
                bindings[identifier] = {"task_sha256": protocol.digest(task), "source_sha256": sha,
                                        "truth_sha256": protocol.digest(gold)}
                pilot.write_json(evaluator / f"{identifier}.json", gold)
                pilot.write_json(packet / "task.json", task)
                database.chmod(0o444)
                (packet / "task.json").chmod(0o444)
        pilot.write_json(evaluator / "index.json", {"suite_version": revision, "development": development,
                         "cases": bindings, "master_seed": master.hex()})
    except BaseException:
        shutil.rmtree(workspace)
        raise
    return {"suite_version": revision, "development": development, "cases": len(bindings)}


def suite(workspace):
    agent, evaluator = separated_roots(workspace / "agent", workspace / "evaluator")
    index = protocol.read_json(evaluator / "index.json", max_bytes=MAX_INDEX_BYTES)
    design = DESIGNS.get(index["suite_version"])
    if (design is None or len(index["cases"]) != design.CASE_COUNT
            or set(index["cases"]) != {p.name for p in agent.iterdir()}):
        raise ValueError("Expected a complete supported verification suite")
    return agent, evaluator, index


def load(workspace):
    agent, evaluator, index = suite(workspace)
    for identifier, binding in sorted(index["cases"].items()):
        task, database = protocol.read_packet(agent / identifier)
        truth = protocol.read_json(evaluator / f"{identifier}.json")
        if (protocol.digest(task) != binding["task_sha256"] or task["source_sha256"] != binding["source_sha256"]
                or protocol.digest(truth) != binding["truth_sha256"]):
            raise ValueError("Frozen case binding failed")
        yield task, database, truth


def band(window):
    length = (protocol.civil(window["end"]) - protocol.civil(window["start"])).days
    return 0 if length <= 55 else 1 if length <= 64 else 2


def metadata_recall(rows):
    predictions = []
    categories = sorted({label for _, _, label in rows})
    for case, features, label in rows:
        pools = [[other for owner, actual, other in rows if owner != case and actual[:n] == features[:n]]
                 for n in range(len(features), -1, -1)]
        counts = Counter(next(pool for pool in pools if pool))
        predictions.append((label, max(categories, key=lambda item: (counts[item], item))))
    return pilot.macro_recall(predictions)


def audit(workspace):
    _, _, index = suite(workspace)
    if index["suite_version"] == 5:
        return audit_reassessment(workspace, index)
    families = Counter()
    transition_counts = {key: Counter() for key in DIRECTIONS}
    weight_signs = Counter()
    replay = {}
    bad_cases = 0
    windows, weight, change = [], [], []
    for task, database, truth in load(workspace):
        identifier = task["case_id"]
        latent, gold = truth["latent"], truth["expected"]
        family = latent["family"]
        if expected(database, task, latent) != gold:
            raise ValueError("Frozen labels disagree with current emitted observations")
        families[family] += 1
        if family in REPLAY_FAMILIES:
            replay.setdefault(family, identifier)  # The minimum opaque ID was fixed before predictions.
        split_year = latent["duration"] // 24
        case_layout = (split_year, *(band(w) for w in task["relationship"]),
                       (protocol.civil(task["change"]["start"]).month - 1) // 3)
        for pos, window in enumerate(task["relationship"]):
            year_quarter = (protocol.civil(window["start"]).month - 1) // 3
            windows.append((identifier, (pos, band(window), year_quarter),
                            gold["relationship"][window["id"]]["decision"]))
        if family in TARGETS:
            label = gold["weight_decision"]
            weight.append((identifier, case_layout, label))
            expected_reasons = {"weight_threshold": ["weight_threshold_gray_zone"],
                                "weight_gap": ["weight_local_support"]}
            if label != TARGETS[family] or gold["weight_adequacy"]["reasons"] != expected_reasons.get(family, []):
                bad_cases += 1
            if family == "weight_step":
                weight_signs["positive" if latent["step_kg"] > 0 else "negative"] += 1
        else:
            actual = pilot.transitions(gold, "decision")
            change.append((identifier, case_layout, family if family in DIRECTIONS else "no_transition"))
            if family in DIRECTIONS and len(actual) == 1:
                (before, after), = actual
                if (before[1], after[1]) == DIRECTIONS[family]:
                    kind = "bridged" if (before[0], after[0]) == ("window_1", "window_3") else "adjacent"
                    transition_counts[family][kind] += 1
                    continue
            if actual or family in DIRECTIONS:
                bad_cases += 1
    raw = {"sleep_windows": metadata_recall(windows), "weight_targets": metadata_recall(weight),
           "reassessment_targets": metadata_recall(change)}
    label_coverage = all({label for _, features, label in windows if features[axis] == bin_} == set(LABELS)
                         for axis in (0, 1) for bin_ in range(3))
    reassessment_ok = all(sum(counts.values()) == CASE_COUNTS[family] and
                          min(counts["adjacent"], counts["bridged"]) >= 6
                          for family, counts in transition_counts.items())
    passed = (not bad_cases and families == CASE_COUNTS and weight_signs == {"negative": 9, "positive": 9}
              and reassessment_ok and max(raw.values()) <= pilot.LEAKAGE_LIMIT and label_coverage)
    return {
        "suite_version": SUITE_VERSION, "bindings_sha256": protocol.digest(index["cases"]),
        "passed": passed, "design_mismatches": bad_cases, "families": dict(families),
        "reassessment_coverage_passed": reassessment_ok, "reassessment": transition_counts,
        "weight_step_signs": dict(weight_signs), "metadata_macro_recall": raw, "label_coverage": label_coverage,
        "replay": [replay[family] for family in REPLAY_FAMILIES],
    }


def audit_reassessment(workspace, index):
    families = Counter()
    shapes = {direction: Counter() for direction in reassessment.DIRECTION}
    replay = {}
    rows, targets = [], []
    problems = Counter()
    for task, db, truth in load(workspace):
        identifier = task["case_id"]
        latent, gold = truth["latent"], truth["expected"]
        family = latent["family"]
        if reassessment.expected(db, task, latent) != gold:
            raise ValueError("Frozen reassessment labels differ from emitted records")
        families[family] += 1
        if family in reassessment.REPLAY_FAMILIES:
            replay.setdefault(family, identifier)
        direction = reassessment.POSITIVE.get(family)
        pair = pilot.transitions(gold, "decision")
        labels = set((before[1], after[1]) for before, after in pair)
        if direction:
            if len(pair) == 1 and labels == {reassessment.DIRECTION[direction]}:
                (before, after), = pair
                shape = "bridge" if (before[0], after[0]) == ("window_1", "window_3") else "adjacent"
                shapes[direction][shape] += 1
                if family.endswith("_bridge") and shape != "bridge":
                    problems["expected_bridge"] += 1
            else:
                problems["ineligible_positive"] += 1
        elif pair:
            problems["unexpected_control_transition"] += 1
        if family.endswith("_bridge"):
            evidence = gold["bridge_evidence"]
            if min(evidence["paired_rows"]) < 16 or min(map(min, evidence["arms_in_shared_strata"])) < 6:
                problems["bridge_support"] += 1
        metadata = []
        for position, window in enumerate(task["relationship"]):
            start, end = map(protocol.civil, (window["start"], window["end"]))
            days = (end - start).days
            length = 0 if days <= 72 else 1 if days <= 81 else 2
            metadata.append(length)
            rows.append((identifier, (position, length, (start.month - 1) // 3),
                         gold["relationship"][window["id"]]["decision"]))
        first = protocol.civil(task["change"]["start"])
        targets.append((identifier, ((first.month - 1) // 3, *metadata), direction or "control"))
    recall = {"sleep_windows": metadata_recall(rows), "reassessment_targets": metadata_recall(targets)}
    coverage = all({label for _, features, label in rows if features[axis] == slot} == set(LABELS)
                   for axis in (0, 1) for slot in range(3))
    support = all(sum(counts.values()) == 24 and min(counts["bridge"], counts["adjacent"]) >= 8
                  for counts in shapes.values())
    return {"suite_version": 5, "passed": (families == reassessment.CASE_COUNTS and support and coverage
                                           and not problems and max(recall.values()) <= pilot.LEAKAGE_LIMIT),
            "bindings_sha256": protocol.digest(index["cases"]), "reassessment_coverage_passed": support,
            "metadata_macro_recall": recall, "label_coverage": coverage, "families": dict(families),
            "reassessment_shapes": shapes, "design_mismatches": dict(problems),
            "replay": [replay[family] for family in reassessment.REPLAY_FAMILIES]}


def results(workspace, runs, audit_record, profile, image, method):
    cases = list(load(workspace))
    case_ids = {task["case_id"] for task, _, _ in cases}
    if ({p.name for p in (runs / "first").iterdir()} != case_ids
            or {p.name for p in (runs / "replay").iterdir()} != set(audit_record["replay"])):
        raise ValueError("Run and replay sets must match the prescheduled verification inputs")
    profile_sha = protocol.digest(profile)
    statuses, result = Counter(), {}
    matched = 0
    for task, data, truth in cases:
        identifier = task["case_id"]
        run, submission = pilot.read_result(runs / "first" / identifier, task, data)
        if run["profile_sha256"] != profile_sha or run["image"] != image:
            raise ValueError("Prediction is from a different profile or image")
        if submission and submission["worker"] != method:
            raise ValueError("Unexpected worker in receipt")
        statuses[run["status"]] += 1
        if identifier in audit_record["replay"]:
            repeat_run, repeat = pilot.read_result(runs / "replay" / identifier, task, data)
            if repeat_run["profile_sha256"] != profile_sha or repeat_run["image"] != image:
                raise ValueError("Replay is from a different profile or image")
            matched += bool(submission and repeat and repeat["worker"] == method
                            and submission["predictions"] == repeat["predictions"])
        result[identifier] = scoring.score_case(data, task, truth["expected"], submission) if submission else None
    return result, {"statuses": dict(statuses), "replays": len(audit_record["replay"]), "matched": matched}


def compare_metrics(cases, scored, baseline=None):
    counts = {family: Counter(total=number) for family, number in CASE_COUNTS.items()}
    diagnostics = Counter()
    paired = {"weight_abstention": [], "exact_reassessment": []}
    for task, _, truth in cases:
        identifier, gold, family = task["case_id"], truth["expected"], truth["latent"]["family"]
        row = scored[identifier]
        previous = baseline[identifier] if baseline is not None else None
        if family in TARGETS:
            correct = int(row is not None and row["change"]["correct"])
            counts[family]["correct"] += correct
            counts[family]["submitted_change"] += bool(row and row["change"]["submitted"] == "change")
            if family in ("weight_threshold", "weight_gap") and baseline is not None:
                paired["weight_abstention"].append(correct - int(previous is not None and previous["change"]["correct"]))
            continue
        wanted = pilot.transitions(gold, "decision")
        actual = pilot.transitions(row, "effective_decision") if row else set()
        submitted = pilot.transitions(row, "submitted") if row else set()
        correct = len(wanted & actual)
        counts[family]["correct"] += correct
        counts[family]["submitted_transition_cases"] += bool(submitted)
        diagnostics["extra_qualified"] += len(actual - wanted)
        for before, after in submitted - wanted:
            if any((a[1], b[1]) == (before[1], after[1]) for a, b in wanted):
                diagnostics["wrong_windows"] += 1
            elif any((a[1], b[1]) == (after[1], before[1]) for a, b in wanted):
                diagnostics["reverse_direction"] += 1
            else:
                diagnostics["unsupported"] += 1
        diagnostics["missed"] += len(wanted - actual)
        for before, after in wanted - actual:
            diagnostics["missed_with_abstention"] += bool(row and any(
                row["relationship"][key]["effective_decision"] == "inconclusive" for key in (before[0], after[0])))
        if row:
            diagnostics["correct_windows"] += sum(value["correct"] for value in row["relationship"].values())
            diagnostics["correct_window_abstentions"] += sum(value["correct"] and value["expected"] == "inconclusive"
                                                               for value in row["relationship"].values())
        if family in DIRECTIONS and baseline is not None:
            prior = pilot.transitions(previous, "effective_decision") if previous else set()
            paired["exact_reassessment"].append(correct - len(wanted & prior))
    return {"strata": counts, "reassessment": diagnostics,
            "paired": {key: {"count_difference": sum(values), "cases": len(values),
                             "case_bootstrap_95_interval": pilot.interval(values)}
                       for key, values in paired.items() if values}}


def gates(baseline, candidate, replays):
    orig, new = baseline["strata"], candidate["strata"]
    check = lambda families, obj: sum(obj[family]["correct"] for family in families)
    uncertain = ("weight_threshold", "weight_gap")
    controls = ("weight_steady", "weight_drift", "weight_small")
    sleep_controls = ("sleep_stable", "sleep_composition", "sleep_sparse")
    return {
        "weight_abstention": (check(uncertain, new) >= 21 and all(new[name]["correct"] >= 10 for name in uncertain)
                              and check(uncertain, new) - check(uncertain, orig) >= 3),
        "weight_guardrails": (new["weight_step"]["correct"] >= max(16, orig["weight_step"]["correct"] - 1)
                             and check(controls, new) >= max(16, check(controls, orig) - 1)
                             and new["weight_drift"]["submitted_change"] <= 1),
        "exact_reassessment": (all(new[key]["correct"] >= max(13, orig[key]["correct"]) for key in DIRECTIONS)
                               and check(DIRECTIONS, new) - check(DIRECTIONS, orig) >= 2),
        "reassessment_guardrails": (sum(new[key]["submitted_transition_cases"] for key in sleep_controls) <= 3
                                     and candidate["reassessment"]["wrong_windows"] <= 2
                                     and candidate["reassessment"]["extra_qualified"] <= baseline["reassessment"]["extra_qualified"]),
        "execution_and_replay": all(receipt["statuses"] == {"completed": CASE_COUNT}
                                    and receipt["replays"] == receipt["matched"] == 8 for receipt in replays),
    }


def reassessment_metrics(cases, scores, baseline=None):
    families = {family: Counter(total=count) for family, count in reassessment.CASE_COUNTS.items()}
    totals = Counter()
    paired = []
    for task, _, truth in cases:
        identifier, family = task["case_id"], truth["latent"]["family"]
        case = scores[identifier]
        gold = truth["expected"]
        wanted = pilot.transitions(gold, "decision")
        actual = pilot.transitions(case, "effective_decision") if case else set()
        submitted = pilot.transitions(case, "submitted") if case else set()
        count = families[family]
        exact = len(wanted & actual)
        count["exact"] += exact
        count["submitted_transition_cases"] += bool(submitted)
        totals["missed"] += len(wanted - actual)
        totals["extra_qualified"] += len(actual - wanted)
        totals["no_target_submitted_transition_cases"] += bool(submitted) and not wanted
        for before, after in submitted - wanted:
            directions = {(a[1], b[1]) for a, b in wanted}
            if (before[1], after[1]) in directions:
                totals["wrong_windows"] += 1
            elif (after[1], before[1]) in directions:
                totals["reversed"] += 1
            else:
                totals["unsupported"] += 1
        if case:
            windows = case["relationship"].values()
            totals["correct_windows"] += sum(v["correct"] for v in windows)
            totals["correct_window_abstentions"] += sum(v["correct"] and v["expected"] == "inconclusive"
                                                         for v in windows)
        if baseline is not None and wanted:
            prior = baseline[identifier]
            previous = pilot.transitions(prior, "effective_decision") if prior else set()
            paired.append(exact - len(wanted & previous))
    by_direction = {direction: sum(families[k]["exact"] for k, label in reassessment.POSITIVE.items()
                                   if label == direction) for direction in reassessment.DIRECTION}
    result = {"families": families, "exact_by_direction": by_direction, "diagnostics": totals}
    if paired:
        result["paired"] = {"count_difference": sum(paired), "cases": len(paired),
                            "case_bootstrap_95_interval": pilot.interval(paired)}
    return result


def reassessment_gates(baseline, candidate, execution):
    old, new = baseline["exact_by_direction"], candidate["exact_by_direction"]
    before, after = baseline["diagnostics"], candidate["diagnostics"]
    return {
        "exact_reassessment": (all(new[d] >= max(20, old[d]) for d in reassessment.DIRECTION)
                               and sum(new.values()) - sum(old.values()) >= 4),
        "reassessment_guardrails": (after["no_target_submitted_transition_cases"] <= 4
                                    and after["wrong_windows"] <= before["wrong_windows"]
                                    and after["extra_qualified"] <= before["extra_qualified"]),
        "execution_and_replay": all(r["statuses"] == {"completed": reassessment.CASE_COUNT}
                                    and r["replays"] == r["matched"] == 8 for r in execution),
    }


def calibrate(workspace, baseline_source):
    from worker import execute

    _, _, index = suite(workspace)
    if index["development"] is not True or index["suite_version"] != 5 or not audit(workspace)["passed"]:
        raise ValueError("Use the complete, audited public revision 5 panel for calibration")
    head = subprocess.check_output(["git", "-C", str(baseline_source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(baseline_source), "status", "--porcelain", "--untracked-files=all"])
    if head != BASELINE_TAG or dirty:
        raise ValueError("Calibration requires the clean published v0.2.0 checkout")
    cases = list(load(workspace))
    baseline, candidate = {}, {}
    for task, path, truth in cases:
        raw = subprocess.check_output([sys.executable, "-B", str(baseline_source / "benchmark/worker.py"),
                                       str(path.parent), "--worker", "drift-aware"], timeout=30)
        if len(raw) > protocol.MAX_SUBMISSION_SIZE:
            raise ValueError("Public reference output exceeds the protocol")
        original_scores = scoring.submission(json.loads(raw), task)
        candidate_scores = scoring.submission(execute(path.parent, "evidence-aware"), task)
        identifier = task["case_id"]
        baseline[identifier] = scoring.score_case(path, task, truth["expected"], original_scores)
        candidate[identifier] = scoring.score_case(path, task, truth["expected"], candidate_scores)
    old = reassessment_metrics(cases, baseline)
    new = reassessment_metrics(cases, candidate, baseline)
    headroom = (all(15 <= n <= 20 for n in old["exact_by_direction"].values())
                and all(old["families"][f]["exact"] >= 7 for f in reassessment.POSITIVE if f.endswith("_anchor"))
                and all(old["families"][f]["exact"] < 8 for f in reassessment.POSITIVE if not f.endswith("_anchor")))
    return {"passed": headroom, "baseline": old, "candidate": new,
            "design_sha256": design_sha256(), "source_sha256": protocol.hash_file(Path(__file__)),
            "public_bindings_sha256": protocol.digest(index["cases"]), "baseline_commit": BASELINE_TAG}


def evaluate(workspace, original, candidate, profile, audit_record):
    _, _, index = suite(workspace)
    if index["development"] or audit(workspace) != audit_record or not audit_record["passed"]:
        raise ValueError("Compare only the frozen audited verification suite")
    cases = list(load(workspace))
    previous, first = results(workspace, original, audit_record, profile, profile["baseline_image"], "drift-aware")
    new, second = results(workspace, candidate, audit_record, profile, profile["image"], "evidence-aware")
    abstain = {task["case_id"]: scoring.score_case(data, task, truth["expected"], pilot.abstain(task))
               for task, data, truth in cases}
    if index["suite_version"] == 5:
        old_metrics, new_metrics = reassessment_metrics(cases, previous), reassessment_metrics(cases, new, previous)
        summary = {"suite_version": 5, "scoring_version": 6, "baseline": old_metrics, "candidate": new_metrics,
                   "always_abstain": reassessment_metrics(cases, abstain), "baseline_execution": first,
                   "candidate_execution": second, "gates": reassessment_gates(old_metrics, new_metrics, (first, second))}
        # Preserve the original per-case scoring results for audit.
        return summary, {"baseline": previous, "candidate": new}
    old_metrics, new_metrics = compare_metrics(cases, previous), compare_metrics(cases, new, previous)
    summary = {"suite_version": SUITE_VERSION, "scoring_version": SCORING_VERSION,
               "baseline": old_metrics, "candidate": new_metrics,
               "always_abstain": compare_metrics(cases, abstain), "baseline_execution": first,
               "candidate_execution": second, "gates": gates(old_metrics, new_metrics, (first, second))}
    return summary, {"baseline": previous, "candidate": new}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("workspace", type=Path)
    build.add_argument("--development", action="store_true")
    build.add_argument("--seed-file", type=Path)
    build.add_argument("--revision", type=int, choices=DESIGNS, default=4)
    build.add_argument("--calibration", type=Path)
    examine = commands.add_parser("audit")
    examine.add_argument("workspace", type=Path)
    examine.add_argument("--output", type=Path, required=True)
    public = commands.add_parser("calibrate")
    public.add_argument("workspace", type=Path)
    public.add_argument("--baseline-source", type=Path, required=True)
    public.add_argument("--output", type=Path, required=True)
    score = commands.add_parser("score")
    for option in ("workspace", "baseline", "candidate", "profile", "audit", "output"):
        score.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            receipt = protocol.read_json(args.calibration) if args.calibration else None
            value = prepare(args.workspace, development=args.development, seed_file=args.seed_file,
                            revision=args.revision, calibration=receipt)
        elif args.command == "calibrate":
            value = calibrate(args.workspace, args.baseline_source)
            pilot.write_json(args.output, value)
            print(json.dumps(value, sort_keys=True))
            if not value["passed"]:
                parser.exit(1, "Public calibration did not establish the declared baseline headroom.\n")
            return
        elif args.command == "audit":
            _, evaluator, _ = suite(args.workspace)
            if args.output.resolve().parent != evaluator:
                raise ValueError("Write the audit only inside the evaluator directory")
            value = audit(args.workspace)
            pilot.write_json(args.output, value)
            passed = value["passed"]
            value = {key: item for key, item in value.items() if key not in {"replay", "bindings_sha256"}}
            print(json.dumps(value, sort_keys=True))
            if not passed:
                parser.exit(1, "Suite audit failed before scoring.\n")
            return
        else:
            _, evaluator, _ = suite(args.workspace)
            if args.output.resolve().parent != evaluator:
                raise ValueError("Write case-level results only inside the evaluator directory")
            value, cases = evaluate(args.workspace, args.baseline, args.candidate, protocol.read_json(args.profile),
                                    protocol.read_json(args.audit))
            pilot.write_json(args.output, {"summary": value, "cases": cases})
        print(json.dumps(value, sort_keys=True))
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
