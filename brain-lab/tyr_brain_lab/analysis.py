"""Deterministic descriptive analyses over stored civil-day observations."""

from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import fmean, median, pstdev

from schema_support import digest

VERSION = "1.0.0"
BLOCK_DAYS = 14
MAX_DAYS = 730
METRICS = {
    "total_sleep_minutes": ("daily_sleep", "total_minutes", "minutes"),
    "total_steps": ("daily_steps", "total_steps", "steps"),
    "body_weight": ("daily_snapshot", "body_weight", "kg"),
    "resting_hr": ("daily_heart_rate", "resting_bpm", "bpm"),
    "average_hr": ("daily_heart_rate", "avg_bpm", "bpm"),
    "hrv_morning": ("morning_hrv", "value_ms", "ms"),
    "workout_session_count": ("daily_snapshot", "workout_session_count", "count"),
}
METHODS = ("late-caffeine-sleep", "baseline-change")
EPOCH = date(1970, 1, 1)
ONE_DAY = timedelta(days=1)


def day(value):
    if not isinstance(value, str):
        raise ValueError("Use YYYY-MM-DD civil dates")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or not 1900 <= parsed.year <= 2199:
        raise ValueError("Use YYYY-MM-DD civil dates between 1900 and 2199")
    return parsed


def seconds(value):
    return (value - EPOCH).days * 86400


def config(method, metric, start, end, split=None, minimum_milli=None, late_minute=None):
    start_day, end_day = day(start), day(end)
    if not 1 <= (end_day - start_day).days <= MAX_DAYS:
        raise ValueError("Analysis windows must span 1 to 730 calendar days")
    if method not in METHODS or metric not in METRICS:
        raise ValueError("Unsupported Lab method or metric")
    if method == "late-caffeine-sleep":
        if metric != "total_sleep_minutes" or split is not None:
            raise ValueError("The caffeine method uses the sleep-duration metric and a single exposure window")
        late_minute = 900 if late_minute is None else late_minute
        if type(late_minute) is not int or not 181 <= late_minute <= 1439:
            raise ValueError("Late cutoff must be an integer nutrition clock minute from 181 through 1439")
    elif late_minute is not None or split is None or not start_day < day(split) < end_day:
        raise ValueError("Baseline-change needs a split inside the calendar window")
    if minimum_milli is None:
        if method == "late-caffeine-sleep":
            minimum_milli = 15_000
        elif metric == "body_weight":
            minimum_milli = 1_000
        else:
            raise ValueError("Supply a meaningful change threshold in thousandths of the metric unit")
    if type(minimum_milli) is not int or not 1 <= minimum_milli <= 100_000_000:
        raise ValueError("Meaningful change must be a positive integer in thousandths of the metric unit")
    return {
        "version": 1, "method": method, "metric": metric, "start": start, "end_exclusive": end,
        "split": split, "minimum_change_milli": minimum_milli, "late_clock_minute": late_minute,
    }


def check_plan(plan):
    keys = {"version", "method", "metric", "start", "end_exclusive", "split", "minimum_change_milli", "late_clock_minute"}
    if type(plan) is not dict or set(plan) != keys or type(plan["version"]) is not int or plan["version"] != 1:
        raise ValueError("Unsupported analysis plan")
    configured = config(plan["method"], plan["metric"], plan["start"], plan["end_exclusive"],
                        plan["split"], plan["minimum_change_milli"], plan["late_clock_minute"])
    if configured != plan:
        raise ValueError("The analysis plan must include all resolved parameters")
    return configured


def _day_key(row, table):
    if table == "daily_snapshot":
        return day(row["snapshot_date"])
    stamp = row["date"]
    if type(stamp) is not int or stamp % 86400:
        raise ValueError(f"{table}.date must encode a UTC-midnight civil label")
    return EPOCH + timedelta(days=stamp // 86400)


def _indexed(source, table):
    indexed = {}
    for row in source.rows(table, snapshot_columns=table == "daily_snapshot"):
        key = _day_key(row, table)
        if key in indexed:
            raise ValueError(f"Multiple {table} rows share one local date")
        indexed[key] = row
    return indexed


def _measure(row, table, column, metric):
    if row is None or row.get("deleted_at") is not None:
        return None
    value = row[column]
    if value is None or value < 0:
        return None
    if table == "daily_snapshot":
        return None if metric == "body_weight" and value <= 0 else value
    if row.get("source") in {"fake", "devSeed"}:
        return None
    if metric == "hrv_morning" and (row["metric"].lower() != "rmssd" or row["source"] == "synced" or value <= 0):
        return None
    if metric in {"average_hr", "resting_hr"} and (value <= 0 or (metric == "average_hr" and not row["sample_count"])):
        return None
    return value


def _days(start, end):
    return (start + timedelta(days=index) for index in range((end - start).days))


def _points(source, metric, start, end):
    table, col, _ = METRICS[metric]
    rows = _indexed(source, table)
    result = []
    for when in _days(start, end):
        row = rows.get(when)
        value = _measure(row, table, col, metric)
        if value is not None:
            ref = {"table": table, "row_id": row["id"], "column": col, "day": when.isoformat()}
            provenance = row.get("source") or f"snapshot_calculation_{row.get('calculation_version')}"
            result.append({"day": when.isoformat(), "value": value, "references": [ref], "provenance": provenance})
    return result


def statistics(points):
    values = [p["value"] for p in points]
    if not values:
        return {"n": 0, "mean": None, "median": None, "population_sd": None, "min": None, "max": None}
    return {
        "n": len(values), "mean": min(max(fmean(values), min(values)), max(values)), "median": median(values),
        "population_sd": pstdev(values), "min": min(values), "max": max(values),
    }


def describe(source, metric, start, end):
    start, end = day(start), day(end)
    if metric not in METRICS or not 1 <= (end - start).days <= MAX_DAYS:
        raise ValueError("Select a supported metric and a 1 to 730-day window")
    table, column, unit = METRICS[metric]
    points = _points(source, metric, start, end)
    expected = (end - start).days
    return {
        "metric": metric, "unit": unit, "start": start.isoformat(), "end_exclusive": end.isoformat(),
        "projection": table, "column": column, "storage_capability": source.capabilities[table],
        "expected_days": expected, "missing_or_excluded": expected - len(points),
        "coverage_ratio": round(len(points) / expected, 6),
        "source_classes": dict(Counter(point["provenance"] for point in points)),
        "statistics": statistics(points),
    }


def discover(source):
    return {
        "source": source.manifest, "measurements": {
            key: {"table": table, "column": col, "unit": unit, "storage_capability": source.capabilities[table],
                  "portable_snapshot_fields_only": table == "daily_snapshot"}
            for key, (table, col, unit) in METRICS.items()
        },
        "methods": list(METHODS),
    }


def _evidence(role, points, start, end, expected=None):
    return {
        "role": role, "window_start": start.isoformat(), "window_end_exclusive": end.isoformat(),
        "expected_days": expected, "statistics": statistics(points),
        "source_classes": dict(Counter(point["provenance"] for point in points)),
        "reference_rows": [ref for point in points for ref in point["references"]],
        "input_sha256": digest(points),
    }


def _sensitivity(points, start, estimate):
    blocks = {_block(point, start) for point in points}
    if len(blocks) < 3:
        return None
    samples = [estimate([point for point in points if _block(point, start) != block]) for block in sorted(blocks)]
    if any(value is None for value in samples):
        return None
    samples.append(estimate(points))
    return [round(min(samples), 6), round(max(samples), 6)]


def _block(point, start):
    return (day(point["day"]) - start).days // BLOCK_DAYS


def _enough(observed, expected):
    return observed >= 5 and observed * 2 >= expected


def _strata(points):
    strata = defaultdict(lambda: [[], []])
    for point in points:
        strata[point["stratum"]][point["late"]].append(point["value"])
    return strata



def _valid_sleep_clock(row):
    return all(type(row[key]) is int and 0 <= row[key] <= 1439
               for key in ("sleep_start_minute", "sleep_end_minute"))

def _paired_sleep(source, start, end, late_minute):
    snapshots = _indexed(source, "daily_snapshot")
    sleep = _indexed(source, "daily_sleep")
    paired = []
    excluded = Counter()
    for when in _days(start, end):
        exposure = snapshots.get(when)
        wake = when + ONE_DAY
        observation = sleep.get(wake)
        value = _measure(observation, "daily_sleep", "total_minutes", "total_sleep_minutes")
        if not exposure or exposure["caffeine_mg"] is None or exposure["caffeine_mg"] <= 0 or exposure["caffeine_last_dose_minute"] is None:
            excluded["missing_positive_timed_caffeine"] += 1
        elif not 180 <= exposure["caffeine_last_dose_minute"] <= 1439 or exposure["workout_session_count"] is None or exposure["workout_session_count"] < 0:
            excluded["missing_training_or_ambiguous_exposure_clock"] += 1
        elif value is None:
            excluded["missing_following_sleep"] += 1
        elif not _valid_sleep_clock(observation):
            excluded["missing_or_invalid_sleep_clock"] += 1
        elif (observation["sleep_start_minute"] >= observation["sleep_end_minute"]
              and exposure["caffeine_last_dose_minute"] >= observation["sleep_start_minute"]):
            excluded["exposure_not_before_overnight_start"] += 1
        else:
            paired.append({
                "day": when.isoformat(), "value": value, "provenance": observation["source"],
                "late": int(exposure["caffeine_last_dose_minute"] >= late_minute),
                "stratum": f'{"training" if exposure["workout_session_count"] > 0 else "quiet"}_{"weekend" if when.weekday() >= 5 else "weekday"}',
                "dose_mg": exposure["caffeine_mg"],
                "sleep_clock": [observation["sleep_start_minute"], observation["sleep_end_minute"]],
                "references": [
                    {"table": "daily_snapshot", "row_id": exposure["id"], "day": when.isoformat(),
                     "columns": ["caffeine_mg", "caffeine_last_dose_minute", "workout_session_count"]},
                    {"table": "daily_sleep", "row_id": observation["id"], "day": wake.isoformat(),
                     "columns": ["total_minutes", "sleep_start_minute", "sleep_end_minute"]},
                ],
            })

    return paired, excluded


def _caffeine(source, plan, start, end):
    paired, excluded = _paired_sleep(source, start, end, plan["late_clock_minute"])
    groups = _strata(paired)
    common = sorted(key for key, arms in groups.items() if min(map(len, arms)) >= 3)
    retained = [point for point in paired if point["stratum"] in common]
    groups_report = {
        key: {"early": len(arms[0]), "late": len(arms[1]), "used": key in common}
        for key, arms in sorted(groups.items())
    }
    excluded["insufficient_common_support"] += len(paired) - len(retained)

    def estimate(points):
        cells = _strata(points)
        if not common or any(key not in cells or not all(cells[key]) for key in common):
            return None
        deltas = []
        weights = []
        for key in common:
            early, late = cells[key]
            weights.append(min(len(early), len(late)))
            deltas.append(fmean(late) - fmean(early))
        return sum(delta * weight for delta, weight in zip(deltas, weights, strict=True)) / sum(weights)

    point = estimate(retained)
    early = [p for p in retained if not p["late"]]
    late = [p for p in retained if p["late"]]
    attempted = (end - start).days
    stable = _sensitivity(retained, start, estimate) if min(len(early), len(late)) >= 8 and _enough(len(retained), attempted) else None
    threshold = plan["minimum_change_milli"] / 1000
    decision = "inconclusive"
    if stable is not None:
        if stable[1] <= -threshold:
            decision = "supported"
        elif stable[0] > -threshold:
            decision = "notSupported"

    return {
        "evidence_decision": decision, "claim_type": "association", "effect": None if point is None else round(point, 6),
        "sensitivity_range": stable, "eligible_days": len(retained), "expected_days": attempted,
        "exclusions": dict(excluded), "confounders": ["recorded_training_day", "weekend", "total_logged_caffeine", "unmeasured_sleep_influences"],
        "strata": groups_report, "different_logged_doses": len({p["dose_mg"] for p in retained}) > 1,
        "mean_logged_dose_mg_by_timing": {
            "earlier": round(fmean(p["dose_mg"] for p in early), 6) if early else None,
            "late": round(fmean(p["dose_mg"] for p in late), 6) if late else None,
        },
        "limitations": ["observational_comparison", "logged_caffeine_and_training_are_proxies", "no_dose_adjustment",
                        "daily_snapshot_route_metadata_does_not_reconstruct_health_history",
                        "civil_pairing_does_not_recover_historical_offsets"],
        "evidence": [_evidence("comparator", early, start + ONE_DAY, end + ONE_DAY),
                     _evidence("exposure", late, start + ONE_DAY, end + ONE_DAY)],
        "input_sha256": digest({"paired": paired, "exclusions": excluded}),
    }


def _baseline(source, plan, start, end):
    split = day(plan["split"])
    metric = plan["metric"]
    points = _points(source, metric, start, end)

    def arms(rows):
        return [p for p in rows if day(p["day"]) < split], [p for p in rows if day(p["day"]) >= split]

    before, after = arms(points)
    expected_before, expected_after = (split - start).days, (end - split).days

    def estimate(rows):
        prior, later = arms(rows)
        if not prior or not later:
            return None
        return fmean(p["value"] for p in later) - fmean(p["value"] for p in prior)

    value = estimate(points)
    stable = None
    if _enough(len(before), expected_before) and _enough(len(after), expected_after):
        stable = _sensitivity(points, start, estimate)
    threshold = plan["minimum_change_milli"] / 1000
    decision = "inconclusive"
    if stable is not None:
        if stable[0] >= threshold or stable[1] <= -threshold:
            decision = "supported"
        elif stable[0] > -threshold and stable[1] < threshold:
            decision = "notSupported"
    return {
        "evidence_decision": decision, "claim_type": "descriptive", "effect": None if value is None else round(value, 6),
        "sensitivity_range": stable, "eligible_days": len(points), "expected_days": expected_before + expected_after,
        "exclusions": {"missing_or_ineligible": expected_before + expected_after - len(points)},
        "confounders": ["measurement_or_device_change", "time_trends", "logging_changes"],
        "limitations": ["declared_split", "no_causal_attribution", "recorded_observations_only"],
        "evidence": [_evidence("baseline", before, start, split, expected_before),
                     _evidence("followUp", after, split, end, expected_after)],
        "input_sha256": digest(points),
    }


def analyze(source, plan):
    plan = check_plan(plan)
    start, end = day(plan["start"]), day(plan["end_exclusive"])
    is_caffeine = plan["method"] == "late-caffeine-sleep"
    result = (_caffeine if is_caffeine else _baseline)(source, plan, start, end)
    result.update({
        "plan": plan, "algorithm_version": VERSION, "source": source.manifest,
        "unit": METRICS[plan["metric"]][2], "mode": "exploratory",
        "analysis_window_end_exclusive": (end + ONE_DAY if is_caffeine else end).isoformat(),
        "coverage_ratio": round(result["eligible_days"] / result["expected_days"], 6),
        "sensitivity_method": "leave_one_14_day_block_out_range",
        "recommendations_allowed": False,
        "requested_window_reaches_90_calendar_days": (end - start).days >= 90,
    })
    return result


def scan_baseline(source, metric, start, end):
    start, end = day(start), day(end)
    if metric not in METRICS or not 28 <= (end - start).days <= MAX_DAYS:
        raise ValueError("Scan needs a supported metric and a 28 to 730-day window")
    points = _points(source, metric, start, end)
    candidates = []
    for offset in range(14, (end - start).days - 13, 7):
        split = start + timedelta(days=offset)
        before = [p["value"] for p in points if day(p["day"]) < split]
        after = [p["value"] for p in points if day(p["day"]) >= split]
        if _enough(len(before), offset) and _enough(len(after), (end - split).days):
            candidates.append({"split": split.isoformat(), "after_minus_before": round(fmean(after) - fmean(before), 6),
                               "observed_before": len(before), "observed_after": len(after)})
    candidates.sort(key=lambda item: (-abs(item["after_minus_before"]), item["split"]))
    return {"source": source.manifest["sha256"], "metric": metric, "unit": METRICS[metric][2],
            "status": "exploratory_candidates", "scanned_start": start.isoformat(), "scanned_end_exclusive": end.isoformat(),
            "eligible_splits": len(candidates), "candidates": candidates[:5],
            "interpretation": "Split selection uses the same data and requires later or independent evaluation."}
