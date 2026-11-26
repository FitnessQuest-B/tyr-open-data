"""Revision 5 reassessment challenge designs. Evaluator code stays off the VM."""

import hashlib
import random
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import protocol
from synthetic_model import Blackout, DEFAULTS, Phase, Scenario, simulate
from verification_design import emitted, expected as observation_truth, rng_key

SUITE_VERSION = 5
DEVELOPMENT_SEED = hashlib.sha256(b"TYR public reassessment calibration panel v1").digest()
DIRECTION = {"loss": ("supported", "notSupported"), "gain": ("notSupported", "supported")}
POSITIVE = {f"{direction}_{shape}": direction for direction in DIRECTION
            for shape in ("anchor", "bridge", "moderate")}
CONTROLS = ("stable_controls", "clock_controls", "mixed_controls")
CASE_COUNTS = {**dict.fromkeys(POSITIVE, 8), **dict.fromkeys(CONTROLS, 16)}
CASE_COUNT = sum(CASE_COUNTS.values())
REPLAY_FAMILIES = (*POSITIVE, "clock_controls", "mixed_controls")


def make_case(seed, family, replica):
    key = lambda purpose: rng_key(seed, "reassessment/" + family, replica, purpose)
    cal, design, arm, noise = (random.Random(key(role)) for role in ("calendar", "design", "timing", "noise"))
    logging = random.Random(key("training-log-mask"))
    first = date(2024, 1, 1) + timedelta(days=cal.randrange(1461))
    lengths = [cal.randint(64, 89) for _ in range(3)]
    duration = max(sum(lengths) + 30, cal.randint(250, 313))
    free = duration - sum(lengths)
    windows = []
    right = 0
    for length in lengths:
        gap = cal.randint(0, free // 2)
        free -= gap
        right += gap + length
        windows.append((right - length, right))

    split = duration // 2
    early = late = design.choice((-39, -30, -8, 0, 5))
    skew_window = None
    blackouts = []
    if family in POSITIVE:
        direction, shape = family.split("_")
        support = design.uniform(-43, -34)
        weak = design.uniform(-3, 6)
        if shape == "moderate":
            support, weak = design.uniform(-26, -21), design.uniform(-10, -5)
        early, late = (support, weak) if direction == "loss" else (weak, support)
        if shape == "bridge" or (shape == "anchor" and replica % 2 == 0):
            a, b = windows[1]
            fraction = (design.uniform(0.33, 0.38) if replica % 2 == 0 else design.uniform(0.62, 0.67))
            # Anchor bridges have well-separated endpoints and a middle contrast near the boundary.
            if shape == "anchor":
                fraction = (-protocol.MIN_SLEEP_REDUCTION_MINUTES - late) / (early - late)
            split = a + round((b - a) * fraction)
        else:
            earlier = replica % 2
            split = cal.randint(windows[earlier][1], windows[earlier + 1][0])
            if shape == "moderate" and replica < 2:
                skew_window = windows[earlier + replica]
    elif family == "stable_controls":
        early = late = design.choice((-38, -23, -9, -4))
        if replica % 3:
            skew_window = windows[replica % 3]
    elif family == "clock_controls":
        a, b = windows[replica % 3]
        left = cal.randint(a, b - 39)
        blackouts.append(Blackout(left, left + design.randint(30, 39), (design.choice(("sleep", "nutrition")),)))
        if replica % 2:
            early = late = design.choice((-24, -6))
    elif family == "mixed_controls":
        # A gray-zone interval or a mixed edge with no eligible opposing endpoints.
        early = late = design.uniform(-16.5, -13.5)
        if replica % 2:
            k = 0 if replica % 4 == 1 else 2
            left, right = windows[k]
            split = (left + right) // 2
            early, late = ((-37, -4) if k == 0 else (-4, -37))
    common = dict(DEFAULTS, late_effect_minutes=0, sleep_noise=design.randint(13, 24), missing={
        **DEFAULTS["missing"], "weight": design.uniform(0.08, 0.17),
        "sleep": design.uniform(0.006, 0.019), "nutrition": design.uniform(0.006, 0.019),
    })
    phases = (Phase(0, duration, common),)
    if family == "clock_controls":
        turn = cal.randint(55, duration - 55)
        phases = (Phase(0, turn, common), Phase(turn, duration, dict(common, offset_minutes=cal.choice((-450, 60, 330)),
                                                                  wake_jitter=70, sleep_noise=29)))
    scenario = Scenario("reassessment", int.from_bytes(key("observations")[:8], "big"), first, duration,
                        phases, tuple(blackouts))
    day_rows, pending, residual = [], {}, 0
    for row in simulate(scenario):
        stratum = (row.workout, row.civil.weekday() >= 5)
        if stratum in pending:
            timed_late = pending.pop(stratum)
        else:
            timed_late = bool(arm.getrandbits(1))
            pending[stratum] = not timed_late
        omitted = row.omitted
        if skew_window and skew_window[0] <= row.index < skew_window[1] and row.workout:
            timed_late = replica % 2 == 0
            # Exercise a change in usable training-day observations while retaining both quiet-day arms.
            if logging.random() < 0.55:
                omitted = omitted | {"sleep"}
        residual = 0.55 * residual + noise.gauss(0, 4.8)
        effect = early if row.index < split else late
        sleep = row.sleep_minutes + timed_late * effect + residual
        sleep -= 15 if family == "stable_controls" and row.workout and row.index >= duration // 2 else 0
        dose = design.choice((0.75, 1.0, 1.25)) if skew_window is None else (1.0 if timed_late else 0.75)
        day_rows.append(replace(row, late_dose=bool(timed_late), sleep_minutes=round(sleep), omitted=omitted,
                                hrv_ms=round(row.hrv_ms + (sleep - row.sleep_minutes) / 15, 1), dose_factor=dose))
    mechanism = {
        "family": family, "replica": replica, "first": first.isoformat(), "duration": duration, "windows": windows,
        "sleep_split": split, "sleep_effects": [early, late], "skew_window": skew_window,
        "skew_training_sleep_omission_probability": 0.55 if skew_window else 0,
        "weight_day": duration // 2, "step_kg": 0.0,
        "missing_probability": common["missing"], "omissions": [vars(block) for block in blackouts],
        "sleep_serial_noise": {"ar": 0.55, "sd": 4.8},
    }
    return key("identity")[:16].hex(), first, day_rows, windows, mechanism


def expected(database, task, mechanism):
    gold = observation_truth(database, task, mechanism)
    if mechanism["family"].endswith("_bridge"):
        pairs, _ = emitted(database)
        lower, upper = (protocol.civil(task["relationship"][1][k]) for k in ("start", "end"))
        cutoff = protocol.civil(mechanism["first"]) + timedelta(days=mechanism["sleep_split"])
        early = [((training, day.weekday() >= 5), bool(late)) for day, late, training in pairs if lower <= day < cutoff]
        later = [((training, day.weekday() >= 5), bool(late)) for day, late, training in pairs if cutoff <= day < upper]
        cells = [Counter(window) for window in (early, later)]
        shared = {cell for cell, _ in early if all(table[cell, arm] >= 1 for table in cells for arm in (False, True))}
        totals = [[sum(table[cell, arm] for cell in shared) for arm in (False, True)] for table in cells]
        gold["bridge_evidence"] = {"paired_rows": [len(early), len(later)], "arms_in_shared_strata": totals}
    return gold
