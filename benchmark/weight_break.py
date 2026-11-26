"""Experimental weight step detector for detached synthetic benchmark records."""

from datetime import timedelta
from statistics import fmean

import protocol
from tyr_brain_lab import analysis


def contrast(rows, split):
    """Fit a level step after accounting for one linear trend across the window."""
    time, weight = zip(*rows)
    step = [float(day >= split) for day in time]
    mean_day = fmean(time)
    centered = [day - mean_day for day in time]
    time_ss = sum(day * day for day in centered)

    def residual(values):
        mean = fmean(values)
        slope = sum(day * (value - mean) for day, value in zip(centered, values)) / time_ss
        return [value - mean - slope * day for day, value in zip(centered, values)]

    outcome, exposure = residual(weight), residual(step)
    step_ss = sum(value * value for value in exposure)
    variance = sum(value * value for value in outcome)
    explained = sum(y * x for y, x in zip(outcome, exposure))
    return explained / step_ss, explained**2 / (step_ss * variance) if variance else 0.0


def detect(points, start, end):
    origin, finish = map(protocol.civil, (start, end))
    span = (finish - origin).days
    rows = [((protocol.civil(point["day"]) - origin).days, point) for point in points]
    result = {"decision": "inconclusive", "effect": None, "references": [],
              "claim_type": "descriptive", "split": None}
    quarter = span // 4
    if not quarter or any(sum(i * quarter <= day < (i + 1) * quarter for day, _ in rows) < 12
                          for i in range(4)):
        return result
    folds = [[(day, point["value"]) for day, point in rows if (day // 7) % 2 == fold]
             for fold in (0, 1)]
    candidates = []
    gaps = False
    for split in range(42, span - 41):
        nearby = [[sum(lo <= day < hi for day, _ in fold)
                   for lo, hi in ((split - 42, split), (split, split + 42))] for fold in folds]
        if any(min(counts) < 4 for counts in nearby) or min(map(sum, zip(*nearby))) < 12:
            gaps = True
            continue
        candidates.append((split, contrast(folds[0], split), contrast(folds[1], split)))
    if not candidates:
        return result
    split, (discovery, gain), (confirmation, confirmed_gain) = max(candidates, key=lambda item: item[1][1])
    # The validation fold never selects the breakpoint. Gains compare to the fold's trend-only fit.
    minimum = protocol.MIN_WEIGHT_CHANGE_KG
    if (discovery * confirmation > 0 and min(abs(discovery), abs(confirmation)) >= minimum
            and min(gain, confirmed_gain) >= 0.20):
        result.update(decision="change", split=(origin + timedelta(days=split)).isoformat(),
                      effect=round(contrast([(day, point["value"]) for day, point in rows], split)[0], 6))
    elif not gaps and max(abs(fit[0]) for _, *fits in candidates for fit in fits) < minimum * 0.8:
        result["decision"] = "no_change"
    if result["decision"] != "inconclusive":
        before = [p for day, p in rows if day < split][-2:]
        after = [p for day, p in rows if day >= split][:2]
        result["references"] = [{key: ref[key] for key in ("table", "row_id", "column")}
                                for point in before + after for ref in point["references"]]
    return result


def from_source(source, start, end):
    # Share the Lab's date, validity and row-reference rules for daily_snapshot.
    points = analysis._points(source, "body_weight", analysis.day(start), analysis.day(end))
    return detect(points, start, end)
