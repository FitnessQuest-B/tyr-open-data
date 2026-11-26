"""Evaluator-only fixed-target scoring and row-level trace checks."""

import sqlite3
from collections import Counter
from contextlib import closing
from datetime import timedelta

import protocol
from schema_support import require_sqlite


SCORING_VERSION = 2


def submission(value, task):
    protocol.fields(value, "version worker predictions provider elapsed_milliseconds")
    if (type(value["version"]) is not int or value["version"] != protocol.VERSION
            or type(value["worker"]) is not str or not 1 <= len(value["worker"]) <= 100
            or type(value["elapsed_milliseconds"]) is not int or not 0 <= value["elapsed_milliseconds"] <= 86_400_000):
        raise ValueError("Invalid submission header")
    protocol.validate_predictions(value["predictions"], task)
    provider = value["provider"]
    if provider is not None:
        protocol.fields(provider, "request_id adapter model cached input_tokens output_tokens simulated_cost_microusd "
                                  "actual_api_calls actual_cost_microusd reserved_tokens")
        if (type(provider["cached"]) is not bool or type(provider["request_id"]) is not str
                or not protocol.SHA.fullmatch(provider["request_id"])
                or any(type(provider[key]) is not str or not 1 <= len(provider[key]) <= 120
                       for key in ("adapter", "model"))):
            raise ValueError("Invalid provider receipt")
        for key in ("input_tokens", "output_tokens", "simulated_cost_microusd", "actual_api_calls",
                    "actual_cost_microusd", "reserved_tokens"):
            if type(provider[key]) is not int or not 0 <= provider[key] <= 10**9:
                raise ValueError("Malformed usage")
        if provider["actual_api_calls"] or provider["actual_cost_microusd"]:
            raise ValueError("The offline benchmark admits mock provider receipts only")
        if provider["input_tokens"] + provider["output_tokens"] > provider["reserved_tokens"]:
            raise ValueError("Reported usage exceeds the mock reservation")
    return value


def _row(db, ref):
    # Reference names and identifiers have already been checked by the protocol.
    table, column = ref["table"], ref["column"]
    label = "snapshot_date" if table == "daily_snapshot" else "date(date, 'unixepoch')"
    deletion = ", deleted_at" if table == "daily_sleep" else ", NULL"
    positive_dose = " AND caffeine_mg > 0" if column == "caffeine_last_dose_minute" else ""
    row = db.execute(f'SELECT {label}, "{column}"{deletion} FROM "{table}" WHERE id=?{positive_dose}',
                     (ref["row_id"],)).fetchone()
    if not row or row[0] is None or row[1] is None or row[2] is not None:
        return None
    return protocol.civil(row[0]), row[1]


def _trace(db, references, start, end, relationship=False, split=None):
    start, end = protocol.civil(start), protocol.civil(end)
    valid, doses, sleep, weight = 0, [], set(), set()
    for ref in references:
        table, column = ref["table"], ref["column"]
        found = _row(db, ref)
        if not found:
            continue
        day, value = found
        if relationship and table == "daily_sleep":
            if value >= 0 and start + timedelta(days=1) <= day < end + timedelta(days=1):
                sleep.add(day)
                valid += 1
        elif start <= day < end:
            if relationship and column != "body_weight":
                if column == "caffeine_last_dose_minute":
                    if not 180 <= value <= 1439:
                        continue
                    doses.append((day + timedelta(days=1), value >= protocol.LATE_DOSE_MINUTE))
                valid += 1
            elif not relationship and column == "body_weight" and value > 0:
                weight.add(day)
                valid += 1
    if relationship:
        traced = {late for day, late in doses if day in sleep} == {False, True}
    elif split:
        cut = protocol.civil(split)
        traced = any(day < cut for day in weight) and any(day >= cut for day in weight)
    else:
        traced = len(weight) >= 2
    return {"valid_references": valid, "invalid_references": len(references) - valid, "traceable": traced}


def _effective_decision(finding, effect_agrees, trace):
    decision = finding["decision"]
    if finding["claim_type"] == "causal":
        return "invalid_causal"
    if decision == "inconclusive":
        return decision
    if not effect_agrees:
        return "invalid_effect"
    if not trace["traceable"] or trace["invalid_references"]:
        return "invalid_evidence"
    return decision


def score_case(database, task, expected, results):
    require_sqlite()
    output = {}
    predictions = results["predictions"]
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        for window in task["relationship"]:
            key = window["id"]
            finding = predictions["relationship"][key]
            gold = expected["relationship"][key]
            trace = _trace(db, finding["references"], window["start"], window["end"], relationship=True)
            causal = finding["claim_type"] == "causal"
            effect = finding["effect"]
            effect_agrees = effect is not None and (
                (effect <= -protocol.MIN_SLEEP_REDUCTION_MINUTES) == (finding["decision"] == "supported")
            )
            decision = _effective_decision(finding, effect_agrees, trace)
            output[key] = {
                "expected": gold["decision"], "submitted": finding["decision"], "effective_decision": decision,
                "correct": decision == gold["decision"], "unsupported_causal": causal,
                "effect_absolute_error_minutes": (
                    round(abs(effect - gold["embedded_effect_minutes"]), 6)
                    if effect is not None and gold["embedded_effect_minutes"] is not None
                    and gold["decision"] != "inconclusive" and not causal else None
                ),
                "required_confounders": gold["confounders"],
                "recognized_confounders": sorted(set(gold["confounders"]) & set(finding["confounders"])),
                "unverified_confounder_mentions": sorted(set(finding["confounders"]) - set(gold["confounders"])),
                "evidence": trace,
            }

        change = predictions["change"]
        change_truth = expected["change"]
        expected_change = expected.get("weight_decision", "change" if change_truth else "no_change")
        causal = change["claim_type"] == "causal"
        trace = _trace(db, change["references"], task["change"]["start"], task["change"]["end"], split=change["split"])
        effect = change["effect"]
        at_least_minimum = effect is not None and abs(effect) >= protocol.MIN_WEIGHT_CHANGE_KG
        decision = _effective_decision(change, at_least_minimum == (change["decision"] == "change"), trace)
        days_error, direction = None, False
        if change_truth and change["decision"] == "change" and not causal:
            predicted = protocol.civil(change["split"])
            nearest = min(change_truth, key=lambda row: abs((predicted - protocol.civil(row["split"])).days))
            days_error = abs((predicted - protocol.civil(nearest["split"])).days)
            direction = effect * nearest["effect_kg"] > 0
        correct = (
            decision == "change" and days_error is not None and days_error <= 14 and direction
            if expected_change == "change" else decision == expected_change
        )
        change_result = {"expected": expected_change, "submitted": change["decision"],
                         "effective_decision": decision, "correct": correct, "breakpoint_absolute_error_days": days_error,
                         "unsupported_causal": causal, "direction_match": direction, "evidence": trace}
    earlier, later = (output[key] for key in protocol.WINDOWS[:2])
    target = earlier["expected"] == "supported" and later["expected"] == "notSupported"
    reassessed = earlier["effective_decision"] == "supported" and later["effective_decision"] == "notSupported"
    return {"relationship": output, "change": change_result,
            "reassessment": {"target": target, "observed": reassessed, "correct": target == reassessed}}


def _ratio(numerator, denominator):
    return None if not denominator else round(numerator / denominator, 6)


def aggregate(cases, verifications, submissions):
    rows = [window for case in cases for window in case["relationship"].values()]
    count = Counter((row["expected"], row["effective_decision"]) for row in rows)
    true_support = sum(row["expected"] == "supported" for row in rows)
    true_null = sum(row["expected"] == "notSupported" for row in rows)
    true_uncertain = sum(row["expected"] == "inconclusive" for row in rows)
    changes = [case["change"] for case in cases]
    reassessments = [case["reassessment"] for case in cases]
    effects = [row["effect_absolute_error_minutes"] for row in rows if row["effect_absolute_error_minutes"] is not None]
    evidence_claims = [row for row in rows if row["submitted"] != "inconclusive"]
    evidence_claims.extend(row for row in changes if row["submitted"] != "inconclusive")
    reports = [item["provider"] for item in submissions if item["provider"] is not None]
    model_usage = {}
    requests = set()
    for receipt in reports:
        model = receipt["model"]
        account = model_usage.setdefault(model, Counter())
        account["reported_results"] += 1
        if receipt["request_id"] not in requests:
            requests.add(receipt["request_id"])
            for key in ("input_tokens", "output_tokens", "simulated_cost_microusd", "actual_api_calls", "actual_cost_microusd"):
                account[key] += receipt[key]
    hits = count["supported", "supported"]
    false_positives = count["notSupported", "supported"]
    return {
        "cases": len(cases),
        "relationship": {
            "targets": len(rows), "correct_decisions": sum(row["correct"] for row in rows),
            "embedded_positive_windows": true_support, "recovered_positive_windows": hits,
            "recovery_rate": _ratio(hits, true_support),
            "false_negatives_including_abstention": true_support - hits,
            "false_negative_rate_including_abstention": _ratio(true_support - hits, true_support),
            "null_windows": true_null, "false_positives": false_positives,
            "false_positive_rate": _ratio(false_positives, true_null),
            "submitted_false_positives": sum(row["expected"] == "notSupported" and row["submitted"] == "supported"
                                             for row in rows),
            "abstentions": sum(row["effective_decision"] == "inconclusive" for row in rows),
            "insufficient_windows": true_uncertain, "correct_abstentions": count["inconclusive", "inconclusive"],
            "appropriate_abstention_rate": _ratio(count["inconclusive", "inconclusive"], true_uncertain),
            "mean_absolute_effect_error_minutes": None if not effects else round(sum(effects) / len(effects), 6),
        },
        "confounders": {
            "required": sum(len(row["required_confounders"]) for row in rows),
            "recognized": sum(len(row["recognized_confounders"]) for row in rows),
            "unverified_mentions": sum(len(row["unverified_confounder_mentions"]) for row in rows),
        },
        "baseline_change": {"targets": sum(row["expected"] == "change" for row in changes),
                            "detected": sum(row["expected"] == "change" and row["correct"] for row in changes),
                            "false_alarms": sum(row["expected"] == "no_change" and row["effective_decision"] == "change"
                                                for row in changes),
                            "submitted_false_alarms": sum(row["expected"] == "no_change" and row["submitted"] == "change"
                                                          for row in changes),
                            "correct_decisions": sum(row["correct"] for row in changes)},
        "reassessment": {"change_targets": sum(item["target"] for item in reassessments),
                         "recovered_changes": sum(item["target"] and item["observed"] for item in reassessments),
                         "false_reassessments": sum(not item["target"] and item["observed"] for item in reassessments)},
        "traceability": {"decisive_claims": len(evidence_claims),
                         "claims_with_paired_or_enclosing_references": sum(
                             row["evidence"]["traceable"] and not row["evidence"]["invalid_references"]
                             for row in evidence_claims),
                         "invalid_references": sum(row["evidence"]["invalid_references"] for row in rows + changes)},
        "invalid_effect_claims": sum(row["effective_decision"] == "invalid_effect" for row in rows + changes),
        "invalid_evidence_claims": sum(row["effective_decision"] == "invalid_evidence" for row in rows + changes),
        "unsupported_causal_claims": sum(row["unsupported_causal"] for row in rows + changes),
        "reproducibility": {"checked": len(verifications), "matching_predictions": sum(verifications)},
        "compute": {"worker_elapsed_milliseconds": sum(item["elapsed_milliseconds"] for item in submissions),
                    "usage_by_model": {key: dict(value) for key, value in model_usage.items()},
                    "actual_api_calls": 0, "actual_cost_microusd": 0},
    }
