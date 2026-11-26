"""Parameter validation and deterministic observations from a fictional day model."""

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.0.0"
DOMAINS = ("nutrition", "sleep", "steps", "heart_rate", "hrv", "weight")
DEFAULTS = {
    "sleep_minutes": 450, "sleep_noise": 24, "late_effect_minutes": 0,
    "late_probability_quiet": 0.38, "late_probability_training": 0.38,
    "weight_delta_kg": 0, "offset_minutes": -300, "wake_minute": 420, "wake_jitter": 20,
    "missing": {"nutrition": 0.05, "sleep": 0.04, "steps": 0.04,
                "heart_rate": 0.10, "hrv": 0.23, "weight": 0.31},
}
PARAMETER_LIMITS = {
    "sleep_minutes": (350, 540), "sleep_noise": (0, 65), "late_effect_minutes": (-90, 90),
    "offset_minutes": (-720, 840), "wake_minute": (300, 660), "wake_jitter": (0, 120),
}


@dataclass(frozen=True)
class Phase:
    from_day: int
    until_day: int
    settings: dict


@dataclass(frozen=True)
class Blackout:
    from_day: int
    until_day: int
    domains: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    key: str
    seed: int
    first_day: date
    days: int
    phases: tuple[Phase, ...]
    blackouts: tuple[Blackout, ...]


@dataclass(frozen=True)
class Day:
    index: int
    civil: date
    offset: int
    wake_offset: int
    wake_minute: int
    workout: bool
    late_dose: bool
    sleep_minutes: int
    late_effect_minutes: int
    steps: int
    resting_bpm: int
    hrv_ms: float
    weight_kg: float
    serving_factor: float
    omitted: frozenset[str]
    dose_factor: float = 1.0


def numeric(value, lower, upper, field, integral=False):
    kinds = (int,) if integral else (int, float)
    if type(value) not in kinds or not lower <= value <= upper or not math.isfinite(value):
        raise ValueError(f"{field} must be {'an integer' if integral else 'a number'} between {lower} and {upper}")
    return value


def shape(value, fields, required, label):
    if not isinstance(value, dict) or set(value) - fields or required - set(value):
        raise ValueError(f"{label} contains missing or unsupported fields")


def phase_settings(previous, changes):
    shape(changes, set(DEFAULTS) | {"from_day"}, {"from_day"}, "Scenario phase")
    settings = dict(previous)
    for key, value in changes.items():
        if key == "from_day":
            continue
        if key == "missing":
            shape(value, set(DOMAINS), set(), "Missingness probabilities")
            settings[key] = {**previous[key], **{
                domain: numeric(probability, 0, 1, domain) for domain, probability in value.items()
            }}
        elif key in PARAMETER_LIMITS:
            settings[key] = numeric(value, *PARAMETER_LIMITS[key], key, integral=True)
        elif key == "weight_delta_kg":
            settings[key] = numeric(value, -15, 15, key)
        else:
            settings[key] = numeric(value, 0, 1, key)
    return settings


def load_scenario(path: Path, key: str, seed=None):
    raw = json.loads(path.read_text(encoding="utf-8"))
    shape(raw, {"format_version", "scenarios"}, {"format_version", "scenarios"}, "Scenario configuration")
    if type(raw["format_version"]) is not int or raw["format_version"] != 1 or not isinstance(raw["scenarios"], dict):
        raise ValueError("Unsupported scenario configuration format")
    if key not in raw["scenarios"]:
        raise ValueError("Unknown scenario")
    value = raw["scenarios"][key]
    required = {"seed", "start_date", "days", "phases"}
    shape(value, required | {"blackouts"}, required, "Scenario")
    numeric(value["seed"], 0, 2**64 - 1, "configured seed", integral=True)
    seed = numeric(value["seed"] if seed is None else seed, 0, 2**64 - 1, "seed", integral=True)
    days = numeric(value["days"], 180, 365, "days", integral=True)
    if not isinstance(value["start_date"], str):
        raise ValueError("start_date must be an ISO calendar date")
    first = date.fromisoformat(value["start_date"])
    if first.isoformat() != value["start_date"] or not 2000 <= first.year <= 2098:
        raise ValueError("start_date must be YYYY-MM-DD in years 2000–2098")

    changes = value["phases"]
    if not isinstance(changes, list) or not changes:
        raise ValueError("A scenario needs an initial phase")
    starts = []
    for change in changes:
        shape(change, set(DEFAULTS) | {"from_day"}, {"from_day"}, "Scenario phase")
        starts.append(numeric(change["from_day"], 0, days - 1, "phase start", integral=True))
    if starts[0] != 0 or starts != sorted(set(starts)):
        raise ValueError("Phase start days must be unique, increasing, and begin at zero")

    phases = []
    current = DEFAULTS
    for change, start, end in zip(changes, starts, starts[1:] + [days], strict=True):
        current = phase_settings(current, change)
        phases.append(Phase(start, end, current))

    blackouts = []
    blackout_config = value.get("blackouts", [])
    if not isinstance(blackout_config, list):
        raise ValueError("Blackouts must be a list")
    for blackout in blackout_config:
        fields = {"from_day", "until_day", "domains"}
        shape(blackout, fields, fields, "Blackout")
        start = numeric(blackout["from_day"], 0, days - 1, "blackout start", integral=True)
        end = numeric(blackout["until_day"], start + 1, days, "blackout end", integral=True)
        domains = blackout["domains"]
        if (not isinstance(domains, list) or not domains
                or any(domain not in DOMAINS for domain in domains)
                or len(domains) != len(set(domains))):
            raise ValueError("Blackout domains must be distinct known measurement domains")
        blackouts.append(Blackout(start, end, tuple(sorted(domains))))
    return Scenario(key, seed, first, days, tuple(phases), tuple(blackouts))


def rng(seed, channel):
    material = hashlib.sha256(f"{VERSION}:{seed}:{channel}".encode("ascii")).digest()
    return random.Random(int.from_bytes(material, "big"))


def spread(stream, width):
    """Zero-centred triangular noise, rounded to an integer in ±width."""
    return round((stream.random() - stream.random()) * width)


def simulate(scenario):
    timeline = [phase.settings for phase in scenario.phases for _ in range(phase.from_day, phase.until_day)]
    assignment = rng(scenario.seed, "caffeine-assignment")
    sleep_noise = rng(scenario.seed, "sleep-duration")
    wake_noise = rng(scenario.seed, "wake-clock")
    physical = rng(scenario.seed, "other-measurements")
    serving = rng(scenario.seed, "portion-estimates")
    missing = {domain: rng(scenario.seed, "missing:" + domain) for domain in DOMAINS}
    baseline_weight = 70 + 12 * rng(scenario.seed, "body-weight-baseline").random()

    for index, current in enumerate(timeline):
        civil = scenario.first_day + timedelta(days=index)
        weekday = civil.weekday()
        workout = weekday in (0, 2, 4, 5)
        late_probability = current["late_probability_training" if workout else "late_probability_quiet"]
        late = assignment.random() < late_probability
        sleep = (current["sleep_minutes"] + (12 if weekday >= 5 else 0)
                 - (12 if workout else 0) + (current["late_effect_minutes"] if late else 0)
                 + spread(sleep_noise, current["sleep_noise"]))
        omitted = {domain for domain in DOMAINS if missing[domain].random() < current["missing"][domain]}
        for block in scenario.blackouts:
            if block.from_day <= index < block.until_day:
                omitted.update(block.domains)
        yield Day(
            index=index, civil=civil, offset=current["offset_minutes"],
            wake_offset=timeline[min(index + 1, scenario.days - 1)]["offset_minutes"],
            wake_minute=current["wake_minute"] + spread(wake_noise, current["wake_jitter"]),
            workout=workout, late_dose=late, sleep_minutes=sleep,
            late_effect_minutes=current["late_effect_minutes"],
            steps=6600 + (1900 if workout else 0) + (500 if weekday >= 5 else 0) + spread(physical, 1000),
            resting_bpm=62 + (2 if workout else 0) + spread(physical, 5),
            hrv_ms=round(46 + (sleep - 450) / 15 + spread(physical, 9) / 2, 1),
            weight_kg=round(baseline_weight + current["weight_delta_kg"] + spread(physical, 6) / 10, 1),
            serving_factor=round(1 + spread(serving, 12) / 100, 2),
            omitted=frozenset(omitted),
        )


def local_instant(day, minute=0, offset=0):
    local = datetime(day.year, day.month, day.day, tzinfo=timezone(timedelta(minutes=offset)))
    return int((local + timedelta(minutes=minute)).timestamp())


def day_key(day):
    return day.year * 10000 + day.month * 100 + day.day
