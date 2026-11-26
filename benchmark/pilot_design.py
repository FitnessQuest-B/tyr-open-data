"""Evaluator-only synthetic pilot designs and truth tied to emitted observations."""

import hashlib
import hmac
import random
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import replace
from datetime import date, timedelta
from statistics import fmean

import protocol
from synthetic_model import Blackout, DEFAULTS, Phase, Scenario, simulate

FAMILIES = ("adequate_null", "detectable", "confounded", "changing", "calendar_gaps", "weight_shift")
DAY = timedelta(days=1)
LABELS = ("supported", "notSupported", "inconclusive")


def stream(master, family, replica, purpose):
    label = f"tyr-pilot-3/{family}/{replica}/{purpose}".encode("ascii")
    return hmac.new(master, label, hashlib.sha256).digest()


def labels(effects, support, window_days, raw_pairs, arm_counts):
    reasons = []
    if raw_pairs < 30 or min(arm_counts) < 10 or raw_pairs * 2 < window_days:
        reasons.append("paired_coverage")
    if min(support) < 10 or sum(support) * 2 < raw_pairs:
        reasons.append("common_support")
    if len(effects) > 1 and max(effects) - min(effects) > 10:
        reasons.append("mixed_regimes")
    contrast = fmean(effects) if effects else None
    if contrast is not None and abs(contrast + protocol.MIN_SLEEP_REDUCTION_MINUTES) <= 2:
        reasons.append("threshold_gray_zone")
    decision = "inconclusive"
    if contrast is not None and not reasons:
        decision = "supported" if contrast <= -protocol.MIN_SLEEP_REDUCTION_MINUTES else "notSupported"
    return decision, reasons, contrast


def make_case(master, family, replica):
    design = random.Random(stream(master, family, replica, "design"))
    calendar = random.Random(stream(master, family, replica, "calendar"))
    observation_seed = int.from_bytes(stream(master, family, replica, "observations")[:8], "big")
    case_id = stream(master, family, replica, "identity")[:16].hex()
    duration = calendar.randint(224, 300)
    first = date(2024, 1, 1) + timedelta(days=calendar.randrange(1461))
    lengths = [calendar.randint(48, 72) for _ in range(3)]
    free = duration - sum(lengths)
    offset = 0
    windows = []
    for length in lengths:
        gap = calendar.randint(0, free // 2)
        free -= gap
        offset += gap
        windows.append((offset, offset + length))
        offset += length

    effect = design.choice((-31, -24, -15, -8, 0, 6))
    later = effect
    if family == "adequate_null":
        effect = later = design.choice((-11, -7, 0, 5))
    if family == "detectable":
        effect = later = design.choice((-36, -28, -21, -16))
    if family == "changing":
        strong, weak = design.choice((-40, -36, -32)), design.choice((-5, 0, 5))
        effect, later = (strong, weak) if replica % 2 == 0 else (weak, strong)
    split = calendar.randint(78, duration - 62)
    if family == "changing":
        split = calendar.randint(windows[0][1], windows[2][0])
    travel = calendar.randint(54, duration - 48)
    weight_day = calendar.randint(49, duration - 48)
    weight_kind = design.choice(("step", "drift", "steady"))
    delta = design.choice((-3.0, -2.4, -1.05, 0.75, 1.1, 2.3, 3.0))
    if family == "weight_shift":
        weight_kind = ("step", "drift", "step", "steady")[replica % 4]
    if weight_kind == "drift" or (family == "weight_shift" and weight_kind == "step"):
        delta = design.choice((-3.0, -2.4, 2.3, 3.0))
    confounded = family == "confounded"
    balanced = family in {"changing", "adequate_null", "detectable"}
    hidden_shift = -18 if confounded and replica % 3 == 0 else 0
    offset_minutes = -300
    initial = {
        **DEFAULTS, "late_effect_minutes": effect, "sleep_noise": design.randint(15, 40),
        "late_probability_quiet": 0.23 if confounded else 0.45,
        "late_probability_training": 0.76 if confounded else 0.49,
        "offset_minutes": offset_minutes,
        "missing": {**DEFAULTS["missing"], "weight": 0.82 if family == "weight_shift" and replica % 4 == 3 else 0.24},
    }
    if balanced:
        initial["missing"].update(nutrition=0.02, sleep=0.02)
    settings_at = {
        split: {"late_effect_minutes": later},
    }
    settings_at.setdefault(travel, {}).update(offset_minutes=design.choice((-480, -240, 60, 330)))
    points = sorted(set(settings_at) | {0, duration})
    phases = []
    current = initial
    for left, right in zip(points, points[1:]):
        current = {**current, **settings_at.get(left, {})}
        phases.append(Phase(left, right, current))

    blackouts = []
    if family == "calendar_gaps" or design.randrange(4) == 0:
        begin, end = windows[1] if balanced else design.choice(windows)
        width = min(end - begin - 12, design.randint(32, 48))
        start = design.randint(begin, end - width)
        blackouts.append(Blackout(start, start + width, (design.choice(("sleep", "nutrition")),)))
    if weight_kind == "step" and family == "weight_shift" and replica % 4 == 2:
        blackouts.append(Blackout(weight_day - 35, weight_day + 35, ("weight",)))

    scenario = Scenario("private-pilot", observation_seed, first, duration, tuple(phases), tuple(blackouts))
    dose = random.Random(stream(master, family, replica, "dose"))
    latent = random.Random(stream(master, family, replica, "hidden"))
    allocation = random.Random(stream(master, family, replica, "balanced-timing"))
    pending = {}
    days = []
    for row in simulate(scenario):
        if balanced:
            # Match changing and stable controls on timing given workout and weekday type.
            # Randomize order within pairs to preserve both arms in the short weekend strata.
            stratum = (row.workout, row.civil.weekday() >= 5)
            if stratum in pending:
                late = pending.pop(stratum)
            else:
                late = bool(allocation.getrandbits(1))
                pending[stratum] = not late
            sleep = row.sleep_minutes + (late - row.late_dose) * row.late_effect_minutes
            row = replace(row, late_dose=late, sleep_minutes=sleep,
                          hrv_ms=round(row.hrv_ms + (sleep - row.sleep_minutes) / 15, 1))
        hidden = latent.random() < (0.75 if row.late_dose else 0.25)
        drift = delta * row.index / (duration - 1) if weight_kind == "drift" else 0
        step = delta if weight_kind == "step" and row.index >= weight_day else 0
        sleep_minutes = row.sleep_minutes - (23 if row.workout and confounded else 0) + (hidden_shift if hidden else 0)
        days.append(replace(row, dose_factor=dose.choice((0.75, 1.0, 1.5)), sleep_minutes=sleep_minutes,
                            weight_kg=round(row.weight_kg + drift + step, 1)))
    private = {
        "family": family, "days": duration, "first": first.isoformat(), "phase_split": split,
        "sleep_effects": [effect, later], "observed_training_confounding": confounded,
        "hidden_sleep_shift": hidden_shift, "weight_kind": weight_kind,
        "weight_day": weight_day, "weight_delta": delta,
        "windows": windows, "blackouts": [vars(block) for block in blackouts],
    }
    return case_id, first, tuple(days), windows, private


def task_record(identifier, first, duration, windows, source_hash):
    day = lambda n: (first + n * DAY).isoformat()
    return protocol.validate_task({
        "version": protocol.VERSION, "case_id": identifier, "source_sha256": source_hash,
        "relationship": [{"id": key, "start": day(left), "end": day(right)}
                         for key, (left, right) in zip(protocol.WINDOWS, windows, strict=True)],
        "change": {"start": day(0), "end": day(duration)},
    })


def observed(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        pairs = db.execute("""
            SELECT n.snapshot_date, n.caffeine_last_dose_minute >= ?, n.workout_session_count > 0
              FROM daily_snapshot n JOIN daily_sleep s
                ON date(s.date, 'unixepoch') = date(n.snapshot_date, '+1 day')
             WHERE n.caffeine_mg > 0 AND n.caffeine_last_dose_minute BETWEEN 180 AND 1439
               AND n.workout_session_count >= 0 AND s.total_minutes >= 0 AND s.deleted_at IS NULL
             ORDER BY n.snapshot_date
        """, (protocol.LATE_DOSE_MINUTE,)).fetchall()
        weights = db.execute("SELECT snapshot_date FROM daily_snapshot WHERE body_weight > 0").fetchall()
    return [(protocol.civil(day), late, training) for day, late, training in pairs], {
        protocol.civil(day) for day, in weights
    }


def expected(database, task, private):
    pairs, weights = observed(database)
    origin = protocol.civil(private["first"])
    contrasts = private["sleep_effects"]
    results = {}
    for window in task["relationship"]:
        start, end = map(protocol.civil, (window["start"], window["end"]))
        used = [row for row in pairs if start <= row[0] < end]
        stratum = lambda row: (row[2], row[0].weekday() >= 5)
        counts = Counter((stratum(row), row[1]) for row in used)
        common = [r for r in used if min(counts[(stratum(r), 0)], counts[(stratum(r), 1)]) >= 3]
        overlap = [sum(row[1] == arm for row in common) for arm in (0, 1)]
        arms = [sum(row[1] == arm for row in used) for arm in (0, 1)]
        # The hidden shift has a 0.5 exposure-arm probability difference by design.
        # This is the expected observable contrast, separate from the direct effect.
        effects = [contrasts[(row[0] - origin).days >= private["phase_split"]] + private["hidden_sleep_shift"] / 2
                   for row in common]
        decision, reasons, contrast = labels(effects, overlap, (end - start).days, len(used), arms)
        results[window["id"]] = {
            "decision": decision, "embedded_effect_minutes": contrast,
            "confounders": ["training_day"] if private["observed_training_confounding"] else [],
            "adequacy": {"reasons": reasons, "pairs": len(used), "arms": arms, "common_support": overlap},
        }

    start, end = map(protocol.civil, (task["change"]["start"], task["change"]["end"]))
    quarter = (end - start).days // 4
    groups = [sum(start + i * quarter * DAY <= day < start + (i + 1) * quarter * DAY
                  for day in weights) for i in range(4)]
    reasons = ["weight_coverage"] if min(groups) < 12 else []
    changes = []
    if private["weight_kind"] == "step":
        point = origin + private["weight_day"] * DAY
        before = sum(point - 42 * DAY <= day < point for day in weights)
        after = sum(point <= day < point + 42 * DAY for day in weights)
        if min(before, after) < 12:
            reasons.append("weight_overlap")
        if 0.8 <= abs(private["weight_delta"]) <= 1.2:
            reasons.append("weight_threshold_gray_zone")
        if abs(private["weight_delta"]) >= protocol.MIN_WEIGHT_CHANGE_KG:
            changes.append({"split": point.isoformat(), "effect_kg": private["weight_delta"]})
    return {"relationship": results, "change": changes,
            "weight_decision": "inconclusive" if reasons else "change" if changes else "no_change",
            "weight_adequacy": {"quarter_counts": groups, "reasons": reasons}}
