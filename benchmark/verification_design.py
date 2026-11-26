"""Evaluator-only revision 4 designs and criteria applied to emitted records."""

import hashlib
import hmac
import math
import random
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import replace
from datetime import date, timedelta

import protocol
from pilot_design import DAY, labels
from synthetic_model import Blackout, DEFAULTS, Phase, Scenario, simulate

SUITE_VERSION = 4
CASE_COUNTS = {
    "weight_threshold": 12, "weight_gap": 12, "weight_step": 18,
    "weight_drift": 10, "weight_steady": 4, "weight_small": 4,
    "sleep_loss": 15, "sleep_gain": 15, "sleep_stable": 10, "sleep_composition": 10, "sleep_sparse": 10,
}
CASE_COUNT = sum(CASE_COUNTS.values())
DEVELOPMENT_SEED = hashlib.sha256(b"TYR v0.3 public development suite").digest()
REPLAY_FAMILIES = ("weight_threshold", "weight_gap", "weight_step", "weight_drift",
                   "sleep_loss", "sleep_gain", "sleep_composition", "sleep_sparse")


def rng_key(seed, family, replica, channel):
    return hmac.new(seed, f"tyr-verify-4/{family}/{replica}/{channel}".encode(), hashlib.sha256).digest()


def layout(calendar):
    start = date(2024, 1, 1) + timedelta(days=calendar.randrange(1461))
    lengths = [calendar.randint(48, 78) for _ in range(3)]
    duration = max(sum(lengths) + 18, calendar.randint(236, 306))
    free = duration - sum(lengths)
    windows = []
    end = 0
    for length in lengths:
        gap = calendar.randint(0, free // 2)
        free -= gap
        end += length + gap
        windows.append((end - length, end))
    return start, duration, windows


def make_case(seed, family, replica):
    key = lambda channel: rng_key(seed, family, replica, channel)
    calendar, design, noise, allocation = (random.Random(key(k)) for k in ("calendar", "design", "noise", "timing"))
    first, duration, windows = layout(calendar)
    direction = 1 if replica % 2 else -1
    joint = design.randint(68, duration - 67)
    initial = design.choice((-35, -30, -8, -4, 3))
    later = initial
    sleep_split = duration // 2
    if family in ("sleep_loss", "sleep_gain"):
        strong, weak = design.uniform(-43, -34), design.uniform(-4, 8)
        initial, later = (strong, weak) if family == "sleep_loss" else (weak, strong)
        if replica < 8:
            left, right = windows[1]
            sleep_split = left + round((right - left) * design.uniform(0.46, 0.58))
        else:
            last_before = replica % 2
            sleep_split = calendar.randint(windows[last_before][1], windows[last_before + 1][0])
    elif family == "sleep_composition":
        initial = later = design.choice((-23, -9, -7, 0))
    elif family == "sleep_sparse":
        initial = later = design.choice((-32, -6, 3))

    step, drift, curve = 0.0, design.uniform(-1.0, 1.0), design.uniform(-0.14, 0.14)
    if family == "weight_threshold":
        step = direction * design.uniform(1.035, 1.19)
    elif family in ("weight_gap", "weight_step"):
        step = direction * design.uniform(1.75, 3.1)
        if replica % 3 != 0:
            drift = design.uniform(-2.2, 2.2)
    elif family == "weight_drift":
        drift = direction * design.uniform(1.8, 3.4)
        if replica % 2:
            curve = design.uniform(-0.48, 0.48)
    elif family == "weight_steady":
        drift = curve = 0
    elif family == "weight_small":
        step = direction * design.uniform(0.18, 0.47)

    omissions = []
    if family == "weight_gap":
        left, right = design.randint(10, 17), design.randint(10, 17)
        omissions.append(Blackout(joint - left, joint + right, ("weight",)))
    elif family == "weight_step" and replica % 3 == 0:
        # Similar gaps with dense evidence at the actual step.
        gap_at = joint - 45 if joint > duration // 2 else joint + 45
        omissions.append(Blackout(gap_at - 12, gap_at + 13, ("weight",)))
    if family == "sleep_sparse":
        edge = windows[calendar.randrange(3)]
        start = calendar.randint(edge[0], edge[1] - 33)
        omissions.append(Blackout(start, start + 30, (design.choice(("sleep", "nutrition")),)))
    settings = dict(DEFAULTS, sleep_noise=design.randint(12, 26), missing={
        **DEFAULTS["missing"], "weight": design.uniform(0.04, 0.13),
        "sleep": design.uniform(0.01, 0.04), "nutrition": design.uniform(0.01, 0.04),
    })
    scenario = Scenario("verification", int.from_bytes(key("observations")[:8], "big"), first, duration,
                        (Phase(0, duration, settings),), tuple(omissions))
    pending, days = {}, []
    serial_weight, serial_sleep = 0, 0
    for row in simulate(scenario):
        day = row.index
        stratum = row.workout, row.civil.weekday() >= 5
        if family == "sleep_composition":
            early = day < duration // 2
            late = allocation.random() < (0.72 if row.workout == early else 0.28)
        elif stratum in pending:
            late = pending.pop(stratum)
        else:
            late = bool(allocation.getrandbits(1))
            pending[stratum] = not late
        serial_weight = 0.62 * serial_weight + noise.gauss(0, 0.095)
        serial_sleep = 0.47 * serial_sleep + noise.gauss(0, 4.5)
        sleep_effect = later if day >= sleep_split else initial
        sleep = row.sleep_minutes + late * sleep_effect + serial_sleep
        if family == "sleep_composition" and row.workout:
            sleep -= 19
        progress = day / (duration - 1)
        weight = row.weight_kg + drift * progress + curve * math.sin(math.pi * progress)
        weight += (step if day >= joint else 0) + serial_weight
        dose = design.choice((0.75, 1.0, 1.25)) if day % 4 else 1.5
        days.append(replace(row, late_dose=late, sleep_minutes=round(sleep), weight_kg=round(weight, 1),
                            hrv_ms=round(row.hrv_ms + (sleep - row.sleep_minutes) / 15, 1), dose_factor=dose))
    mechanism = {
        "family": family, "replica": replica, "first": first.isoformat(), "duration": duration, "windows": windows,
        "sleep_split": sleep_split, "sleep_effects": [initial, later],
        "weight_day": joint, "step_kg": step, "drift_kg": drift, "curve_kg": curve,
        "missing_probability": settings["missing"], "omissions": [vars(gap) for gap in omissions],
        "serial_noise": {"weight_ar": 0.62, "weight_sd": 0.095, "sleep_ar": 0.47, "sleep_sd": 4.5},
    }
    return key("identity")[:16].hex(), first, days, windows, mechanism


def emitted(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        pairs = db.execute("""
            SELECT n.snapshot_date, n.caffeine_last_dose_minute >= 900, n.workout_session_count > 0
            FROM daily_snapshot n JOIN daily_sleep s
              ON date(s.date, 'unixepoch') = date(n.snapshot_date, '+1 day')
            WHERE n.caffeine_mg > 0 AND n.caffeine_last_dose_minute BETWEEN 180 AND 1439
              AND n.workout_session_count >= 0 AND s.total_minutes >= 0
              AND s.deleted_at IS NULL AND s.source NOT IN ('fake', 'devSeed')
              AND s.sleep_start_minute BETWEEN 0 AND 1439 AND s.sleep_end_minute BETWEEN 0 AND 1439
              AND (s.sleep_start_minute < s.sleep_end_minute OR n.caffeine_last_dose_minute < s.sleep_start_minute)
        """).fetchall()
        weight = db.execute("SELECT snapshot_date FROM daily_snapshot WHERE body_weight > 0").fetchall()
    return [(protocol.civil(d), late, training) for d, late, training in pairs], {protocol.civil(d) for d, in weight}


def expected(database, task, mechanism):
    pairs, observed = emitted(database)
    first = protocol.civil(mechanism["first"])
    windows = {}
    for window in task["relationship"]:
        start, end = map(protocol.civil, (window["start"], window["end"]))
        usable = [(day, arm, (training, day.weekday() >= 5)) for day, arm, training in pairs if start <= day < end]
        counts = Counter((cell, arm) for _, arm, cell in usable)
        common = [(day, arm) for day, arm, cell in usable if min(counts[cell, 0], counts[cell, 1]) >= 3]
        arms = [sum(arm == code for _, arm, _ in usable) for code in (0, 1)]
        support = [sum(arm == code for _, arm in common) for code in (0, 1)]
        effects = [mechanism["sleep_effects"][(day - first).days >= mechanism["sleep_split"]] for day, _ in common]
        decision, reasons, contrast = labels(effects, support, (end - start).days, len(usable), arms)
        windows[window["id"]] = {
            "decision": decision, "embedded_effect_minutes": contrast,
            "confounders": ["training_day"] if mechanism["family"] == "sleep_composition" else [],
            "adequacy": {"reasons": reasons, "pairs": len(usable), "arms": arms, "common_support": support},
        }

    start, end = map(protocol.civil, (task["change"]["start"], task["change"]["end"]))
    quarter = (end - start).days // 4
    quarters = [sum(start + i * quarter * DAY <= day < start + (i + 1) * quarter * DAY for day in observed)
                for i in range(4)]
    effect = mechanism["step_kg"]
    reasons = ["weight_coverage"] if min(quarters) < 12 else []
    changes = []
    if abs(effect) >= 0.8:
        cut = first + mechanism["weight_day"] * DAY
        left = [(cut - day).days for day in observed if cut - 42 * DAY <= day < cut]
        right = [(day - cut).days for day in observed if cut <= day < cut + 42 * DAY]
        if min(len(left), len(right)) < 12 or min(left) > 7 or min(right) > 7 or min(left) + min(right) > 11:
            reasons.append("weight_local_support")
        if abs(effect) <= 1.2:
            reasons.append("weight_threshold_gray_zone")
        if abs(effect) >= protocol.MIN_WEIGHT_CHANGE_KG:
            changes.append({"split": cut.isoformat(), "effect_kg": effect})
    return {"relationship": windows, "change": changes,
            "weight_decision": "inconclusive" if reasons else "change" if changes else "no_change",
            "weight_adequacy": {"quarter_counts": quarters, "reasons": reasons}}
