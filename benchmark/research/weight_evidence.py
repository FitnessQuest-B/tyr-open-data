"""Reproducible host-side weight evidence for the public research packet."""

from statistics import median

import evidence_method
import protocol
import weight_break
from tyr_brain_lab import analysis

WEIGHT_METHOD = "grounded-weight-v1"
WEIGHT_VERIFICATION_METHOD = "local-weight-step-v1"
STRONG_STEP_KG = 2 * protocol.MIN_WEIGHT_CHANGE_KG
VERIFY_MARGIN_KG = 0.5
WEIGHT_CHALLENGE_REASONS = (
    "inadequate_local_coverage", "local_effect_below_threshold", "near_threshold_local_step",
)


def _local_shift(points, finding):
    cut = protocol.civil(finding["split"])
    dated = [((protocol.civil(p["day"]) - cut).days, p["value"]) for p in points]
    before = [(day, kg) for day, kg in dated if -28 <= day < 0]
    after = [(day, kg) for day, kg in dated if 0 <= day < 28]
    if min(len(before), len(after)) < 12:
        return False
    left, right = -before[-1][0], after[0][0]
    if max(left, right) > evidence_method.WEIGHT_NEAR_DAYS or left + right > evidence_method.WEIGHT_MAX_GAP:
        return False
    shift = median(kg for _, kg in after) - median(kg for _, kg in before)
    effect = finding["effect"]
    return abs(shift) >= STRONG_STEP_KG and shift * effect > 0


def weight_evidence(source, task):
    start, end = (task["change"][key] for key in ("start", "end"))
    points = analysis._points(source, "body_weight", analysis.day(start), analysis.day(end))
    finding = evidence_method.weight_decision(points, start, end)
    method = "v0.3.0-evidence-aware"
    if finding["decision"] == "inconclusive":
        fallback = weight_break.detect(points, start, end)
        if (fallback["decision"] == "change" and abs(fallback["effect"]) >= STRONG_STEP_KG
                and _local_shift(points, fallback)):
            finding, method = fallback, "confirmed-drift-aware-step"
    evidence = f"weight-{task['case_id']}" if finding["references"] else None
    return {
        "version": WEIGHT_METHOD, "method": method, "unit": "kg",
        "start": start, "end_exclusive": end, "observed_days": len(points),
        "expected_days": (protocol.civil(end) - protocol.civil(start)).days,
        "decision": finding["decision"], "effect": finding["effect"],
        "split": finding["split"], "evidence": evidence,
    }, finding["references"]


def verify_weight_step(source, weight):
    result = {"method": WEIGHT_VERIFICATION_METHOD, "unit": "kg", "split": weight["split"],
              "effect_kg": None, "signed_sensitivity_range_kg": None, "observations": None,
              "abstention_reason": None}
    if weight["decision"] != "change":
        return {**result, "status": "no_nominated_step"}
    points = analysis._points(source, "body_weight", analysis.day(weight["start"]),
                              analysis.day(weight["end_exclusive"]))
    cut = protocol.civil(weight["split"])
    dated = [((protocol.civil(p["day"]) - cut).days, p["value"]) for p in points]
    rows = [(day, kg) for day, kg in dated if -42 <= day < 42]
    before = [day for day, _ in rows if day < 0]
    after = [day for day, _ in rows if day >= 0]
    result["observations"] = [len(before), len(after)]
    if (min(len(before), len(after)) < 12
            or max(-before[-1], after[0]) > evidence_method.WEIGHT_NEAR_DAYS
            or after[0] - before[-1] > evidence_method.WEIGHT_MAX_GAP):
        return {**result, "status": "challenge", "abstention_reason": "inadequate_local_coverage"}
    direction = 1 if weight["effect"] > 0 else -1
    effect, _ = weight_break.contrast(rows, 0)
    estimates = [direction * effect]
    for block in sorted({day // 7 for day, _ in rows}):
        sample = [(day, kg) for day, kg in rows if day // 7 != block]
        if min(sum(day < 0 for day, _ in sample), sum(day >= 0 for day, _ in sample)) >= 8:
            estimates.append(direction * weight_break.contrast(sample, 0)[0])
    lower, upper = min(estimates), max(estimates)
    cutoff = protocol.MIN_WEIGHT_CHANGE_KG
    clearance = cutoff + VERIFY_MARGIN_KG
    reason = None
    if upper < cutoff:
        reason = "local_effect_below_threshold"
    elif abs(weight["effect"]) < clearance and lower < clearance:
        reason = "near_threshold_local_step"
    status = "challenge" if reason else ("sensitivity_warning" if lower < cutoff else "confirmed")
    return {**result, "status": status,
            "effect_kg": round(effect, 6),
            "signed_sensitivity_range_kg": [round(lower, 6), round(upper, 6)],
            "abstention_reason": reason}


def required_weight_output(packet, tool, arm):
    weight = packet.get("weight_summary")
    if arm != "C" or weight is None:
        return None
    check = None
    if tool and (tool["operation"], tool["target"]) == ("evaluate", "weight"):
        check = tool.get("weight_verification")
    if (weight["decision"] == "change" and check and check["method"] == WEIGHT_VERIFICATION_METHOD
            and check["split"] == weight["split"] and check["status"] == "challenge"
            and check["abstention_reason"] in WEIGHT_CHALLENGE_REASONS):
        return {"decision": "inconclusive", "effect": None, "split": None, "evidence": None}
    return {key: weight[key] for key in ("decision", "effect", "split", "evidence")}
