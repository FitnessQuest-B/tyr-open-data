"""Observation-only v0.3 weight and relationship methods."""

from datetime import timedelta
from statistics import fmean

import protocol
from tyr_brain_lab import analysis
from weight_break import contrast

WEIGHT_MARGIN = 0.23
WEIGHT_NEAR_DAYS = 7
WEIGHT_MAX_GAP = 11


def weight_decision(points, start, end):
    result = {"decision": "inconclusive", "effect": None, "split": None, "references": [],
              "claim_type": "descriptive"}
    origin, finish = map(protocol.civil, (start, end))
    span = (finish - origin).days
    rows = [((protocol.civil(point["day"]) - origin).days, point["value"]) for point in points]
    days = [d for d, _ in rows]
    quarter = span // 4
    if not quarter or any(sum(i * quarter <= d < (i + 1) * quarter for d in days) < 12 for i in range(4)):
        return result

    # Adjacent discovery and confirmation blocks are separated by two unused days.
    folds = [[row for row in rows if (row[0] // 8) % 2 == fold and row[0] % 8 < 6] for fold in (0, 1)]
    fits = {}
    for split in range(42, span - 41):
        sides = [[sum(lo <= d < hi for d, _ in fold)
                  for lo, hi in ((split - 42, split), (split, split + 42))] for fold in folds]
        if all(min(n) >= 4 for n in sides) and min(map(sum, zip(*sides))) >= 12:
            fits[split] = tuple(contrast(fold, split) for fold in folds)
    if not fits:
        return result

    split = max(fits, key=lambda day: fits[day][0][1])
    (estimate, gain), (confirmation, confirm_gain) = fits[split]
    plausible = [day for day, (fit, _) in fits.items() if fit[1] >= 0.9 * gain]

    def local_support(cut):
        left = cut - max(d for d in days if d < cut)
        right = min(d for d in days if d >= cut) - cut
        return max(left, right) <= WEIGHT_NEAR_DAYS and left + right <= WEIGHT_MAX_GAP

    minimum = protocol.MIN_WEIGHT_CHANGE_KG
    if (min(gain, confirm_gain) >= 0.20 and estimate * confirmation > 0
            and min(abs(estimate), abs(confirmation)) >= minimum + WEIGHT_MARGIN
            and max(plausible) - min(plausible) <= 14 and all(local_support(day) for day in plausible)):
        direction = 1 if estimate > 0 else -1
        confirmation_rows = folds[1]
        # Preserve the nominated date and omit one complete observed block at a time.
        samples = []
        for block in sorted({day // 16 for day, _ in confirmation_rows}):
            retained = [row for row in confirmation_rows if row[0] // 16 != block]
            if min(sum((day < split) == side for day, _ in retained) for side in (True, False)) >= 4:
                samples.append(direction * contrast(retained, split)[0])
        pooled = contrast(rows, split)[0]
        if len(samples) >= 3 and min(samples) >= minimum and direction * pooled >= minimum:
            result.update(decision="change", effect=round(pooled, 6),
                          split=(origin + timedelta(days=split)).isoformat())
    largest = max(abs(estimate) for values in fits.values() for estimate, _ in values)
    if (result["decision"] == "inconclusive" and len(fits) == span - 83
            and all(local_support(day) for day in fits) and largest + WEIGHT_MARGIN < minimum):
        result["decision"] = "no_change"
    if result["decision"] != "inconclusive":
        when = (origin + timedelta(days=split)).isoformat()
        used = [p for p in points if p["day"] < when][-2:] + [p for p in points if p["day"] >= when][:2]
        result["references"] = [ref_fields(ref) for point in used for ref in point["references"]]
    return result


def ref_fields(ref, column=None):
    return {"table": ref["table"], "row_id": ref["row_id"], "column": column or ref["column"]}


def mix(groups, minimum=3):
    return {key: min(map(len, arms)) for key, arms in groups.items() if min(map(len, arms)) >= minimum}


def effect(groups, weights):
    if not weights:
        return None
    return sum(weights[key] * (fmean(groups[key][1]) - fmean(groups[key][0]))
               for key in weights) / sum(weights.values())


def decision(estimate):
    return "supported" if estimate <= -protocol.MIN_SLEEP_REDUCTION_MINUTES else "notSupported"


def window_evidence(source, window):
    start, end = map(protocol.civil, (window["start"], window["end"]))
    paired, _ = analysis._paired_sleep(source, start, end, protocol.LATE_DOSE_MINUTE)
    groups = analysis._strata(paired)
    weights = mix(groups)
    retained = [row for row in paired if row["stratum"] in weights]
    arms = [sum(row["late"] == arm for row in retained) for arm in (0, 1)]
    days = (end - start).days
    estimate = effect(groups, weights)
    value = {"decision": "inconclusive", "effect": None if estimate is None else round(estimate, 6),
             "references": [], "claim_type": "association", "confounders": []}
    if len(paired) * 4 < days * 3:
        value["confounders"].append("logging_gaps")
    if len({p["dose_mg"] for p in retained}) > 1:
        value["confounders"].append("dose_size")
    rates = []
    for training in ("training_", "quiet_"):
        relevant = [p["late"] for p in paired if p["stratum"].startswith(training)]
        if relevant:
            rates.append(fmean(relevant))
    if len(rates) == 2 and abs(rates[0] - rates[1]) >= 0.18:
        value["confounders"].append("training_day")
    if len(paired) < 30 or len(paired) * 2 < days or min(arms) < 10 or len(retained) * 2 < len(paired):
        return value, groups, weights

    # Compare prespecified time halves on the same strata and weights.
    midpoint = (start + timedelta(days=days // 2)).isoformat()
    halves = [analysis._strata([row for row in retained if (row["day"] < midpoint) == before])
              for before in (True, False)]
    shared = {key: weight for key, weight in weights.items()
              if all(key in half and min(map(len, half[key])) >= 2 for half in halves)}
    halves_usable = shared and all(min(sum(len(half[key][arm]) for key in shared) for arm in (0, 1)) >= 6
                                  for half in halves)
    if halves_usable:
        early, late = (effect(half, shared) for half in halves)
        if decision(early) != decision(late) and abs(early - late) >= 12:
            value["confounders"].append("baseline_change")
            return value, groups, weights

    def unchanged(rows):
        cells = analysis._strata(rows)
        observed = {key: weight for key, weight in weights.items() if key in cells and all(cells[key])}
        return effect(cells, observed) if sum(observed.values()) * 4 >= sum(weights.values()) * 3 else None

    span = analysis._sensitivity(retained, start, unchanged)
    if span is None or decision(span[0]) != decision(span[1]):
        return value, groups, weights
    value["decision"] = decision(estimate)
    for arm in (0, 1):
        row = next(p for p in retained if p["late"] == arm)
        dose, wake = row["references"]
        value["references"].extend([ref_fields(dose, "caffeine_last_dose_minute"), ref_fields(wake, "total_minutes")])
    return value, groups, weights


def predict(task, source):
    windows = {w["id"]: window_evidence(source, w) for w in task["relationship"]}
    eligible = [weights for _, _, weights in windows.values() if weights]
    if len(eligible) >= 2:
        common = set.intersection(*(set(weights) for weights in eligible))
        shared = {key: min(weights[key] for weights in eligible) for key in sorted(common)}
        if shared:
            for value, groups, weights in windows.values():
                if value["decision"] == "inconclusive":
                    continue
                comparable = effect(groups, shared)
                if (sum(weights[key] for key in shared) * 2 >= sum(weights.values())
                        and decision(comparable) != value["decision"] and abs(comparable - value["effect"]) >= 5):
                    value.update(decision="inconclusive", references=[])
    start, end = task["change"]["start"], task["change"]["end"]
    points = analysis._points(source, "body_weight", analysis.day(start), analysis.day(end))
    return {"version": protocol.VERSION, "case_id": task["case_id"], "change": weight_decision(points, start, end),
            "relationship": {key: result for key, (result, _, _) in windows.items()}}
