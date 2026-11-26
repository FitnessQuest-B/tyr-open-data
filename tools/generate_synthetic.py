"""Create or verify a standalone synthetic TYR records package."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from contextlib import ExitStack, closing
from datetime import timedelta
from pathlib import Path

from schema_support import ROOT, load_contract, require_sqlite
from synthetic_model import DOMAINS, VERSION, load_scenario, simulate
from synthetic_storage import build_records, records_summary

DEFAULT_CONFIG = ROOT / "scenarios" / "starter.json"
ID_PATTERN = re.compile(r"[0-9a-f]{32}")


def hash_file(path):
    with path.open("rb") as source:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
        return checksum.hexdigest()


def day_text(scenario, index):
    return (scenario.first_day + timedelta(days=index)).isoformat()


def interval(scenario, start, end):
    return {
        "from_day": start, "until_day": end,
        "start_date": day_text(scenario, start), "end_date_exclusive": day_text(scenario, end),
    }


def phase_truth(scenario, phase, days):
    effect = phase.settings["late_effect_minutes"]
    paired = {"quiet_early": 0, "quiet_late": 0, "training_early": 0, "training_late": 0}
    end = min(phase.until_day, scenario.days - 1)
    for day in days[phase.from_day:end]:
        if "nutrition" not in day.omitted and "sleep" not in day.omitted:
            training = "training" if day.workout else "quiet"
            timing = "late" if day.late_dose else "early"
            paired[f"{training}_{timing}"] += 1
    return {
        **interval(scenario, phase.from_day, phase.until_day),
        "parameters": phase.settings,
        "causal_effect": {
            "target": "late_caffeine_to_following_sleep_duration",
            "late_minus_early_minutes": effect,
            "expected_direction": "decrease" if effect < 0 else "increase" if effect > 0 else "none",
        },
        "possible_confounders": (
            ["training_day"] if phase.settings["late_probability_quiet"] != phase.settings["late_probability_training"] else []
        ),
        "observed_pairs_by_training_and_timing": paired,
    }


def make_truth(scenario, days, bundle_id, contract, row_counts, logical_hash, database_hash):
    return {
        "format_version": 1,
        "generator_version": VERSION,
        "scenario": scenario.key,
        "seed": scenario.seed,
        "randomness": "MT19937 random() with SHA-256 separated deterministic streams",
        "provenance": {
            "source": "fictional simulation from blank TYR Open Data records DDL",
            "uses_personal_records": False,
            "scope": "Ground truth describes the simulation only.",
        },
        "observation_package": {
            "id": bundle_id,
            "file": "records.sqlite",
            "sha256": database_hash,
            "logical_sha256": logical_hash,
            "sqlite_version": sqlite3.sqlite_version,
            "specification_version": contract["specification_version"],
            "source_app_schema_version": contract["source_app_schema_version"],
            "observed_row_counts": row_counts,
        },
        "date_window": interval(scenario, 0, scenario.days),
        "time_model": {
            "clock_offsets": "Explicit fictional fixed offsets by phase, in minutes east of UTC.",
            "sleep_alignment": "Exposure day d has an outcome at wake date d+1 when present.",
            "phase_effect_basis": "Exposure day",
            "first_wake_date_has_no_prior_exposure_in_window": True,
            "last_exposure_day_has_no_next_wake_date_in_window": True,
        },
        "target_candidates": [
            {
                "key": "late_caffeine_to_following_sleep_duration",
                "exposure": {"early_minute": 630, "late_minute": 1020, "amount_mg_both_groups": 80},
                "outcome": {"table": "daily_sleep", "column": "total_minutes", "unit": "minutes", "wake_date_lag": 1},
                "hold_fixed": ["phase", "training_day", "weekend", "sleep_noise_draw"],
            }
        ],
        "phases": [phase_truth(scenario, phase, days) for phase in scenario.phases],
        "mechanisms": {
            "training_day": {"weekdays_monday_zero": [0, 2, 4, 5]},
            "caffeine_assignment": {"distribution": "Bernoulli", "probability_depends_on": ["phase", "training_day"]},
            "sleep_duration": {
                "baseline": "phase.sleep_minutes",
                "weekend_add_minutes": 12,
                "training_add_minutes": -12,
                "late_dose_add": "phase.late_effect_minutes",
                "noise": {"distribution": "rounded triangular", "max_abs_minutes": "phase.sleep_noise"},
            },
            "wake_clock": {"center_minutes": "phase.wake_minute", "rounded_triangular_width": "phase.wake_jitter"},
            "weight": {"baseline_range_kg": [70, 82], "phase_shift_kg": "phase.weight_delta_kg",
                       "rounded_triangular_width_kg": 0.6},
            "secondary_dependence": [
                {"cause": "training_day", "effects": ["steps", "resting_hr", "average_hr", "maximum_hr"]},
                {"cause": "weekend", "effects": ["steps", "sleep_duration"]},
                {"cause": "sleep_duration", "effects": ["next_wake_day_hrv", "bedtime_for_fixed_wake_time", "stage_minutes"]},
                {"cause": "body_weight", "effects": ["periodic_waist_measurement"]},
            ],
            "measurement_noise": {
                "body_weight": "Independent rounded triangular day draws up to 0.6 kg.",
                "step_count": "Rounded triangular day draws up to 1000 steps.",
                "resting_hr": "Rounded triangular day draws up to 5 bpm.",
                "hrv": "Rounded triangular day draws up to 4.5 ms.",
                "meal_portions": "Rounded triangular scaling up to 12% on estimated mass. Caffeine drink has fixed dose.",
            },
        },
        "missingness": {
            "mechanism": "Per-domain draws independent conditional on phase, with deterministic blackout overrides.",
            "sleep_missingness_basis": "Exposure day; a blocked night removes the next wake date row.",
            "other_domains_basis": "Stored civil day",
            "omitted_draws_by_domain": {
                domain: sum(domain in day.omitted for day in days) for domain in DOMAINS
            },
        },
        "insufficient_evidence_periods": [
            {**interval(scenario, block.from_day, block.until_day), "domains": list(block.domains),
             "reason": "deliberate blackout"}
            for block in scenario.blackouts
        ],
        "relationships_to_avoid_inferring": [
            {"claim": "A dose-response effect from total caffeine amount", "reason": "Dose is fixed across logged days."},
            {"claim": "A causal effect of future caffeine exposure on past sleep", "reason": "No such edge exists."},
            {"claim": "A direct effect of the synthetic mineral on sleep", "reason": "No such edge exists."},
            *([{"claim": "A constant late-dose effect across phases", "reason": "The configured effect changes."}]
              if len({phase.settings["late_effect_minutes"] for phase in scenario.phases}) > 1 else []),
            {"claim": "A real physiological or medical effect", "reason": "This is a fictional data generator."},
        ],
    }


def separated_roots(agent_root, truth_root):
    agent = agent_root.resolve()
    truth = truth_root.resolve()
    if agent == truth or agent.is_relative_to(truth) or truth.is_relative_to(agent):
        raise ValueError("Agent and evaluator roots must be disjoint directories")
    for directory in (agent, truth):
        if directory == ROOT or directory.is_relative_to(ROOT) or ROOT.is_relative_to(directory):
            raise ValueError("Output roots must be separate from the source checkout")
    return agent, truth


def verify_bundle(bundle):
    require_sqlite()
    if not ID_PATTERN.fullmatch(bundle.name) or bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Expected a standalone opaque-id bundle directory")
    entries = list(bundle.iterdir())
    if len(entries) != 1 or entries[0].name != "records.sqlite" or entries[0].is_symlink() or not entries[0].is_file():
        raise ValueError("The agent bundle must contain only an ordinary records.sqlite file")
    path = entries[0]
    _, contract = load_contract("0.1.0")
    with path.open("rb") as handle:
        header = handle.read(100)
    if len(header) < 100 or header[:16] != b"SQLite format 3\0" or header[18:20] != b"\x01\x01":
        raise ValueError("The agent database must be a closed standalone SQLite file")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        counts, logical_hash = records_summary(db, contract)
    if not 180 <= counts["daily_snapshot"] <= 365 or counts["user"] != 1:
        raise ValueError("The agent database must contain one synthetic subject and 180–365 snapshot days")
    return {"id": bundle.name, "sha256": hash_file(path), "logical_sha256": logical_hash}


def generate(scenario, agent_root, truth_root, bundle_id=None):
    bundle_id = bundle_id if bundle_id is not None else uuid.uuid4().hex
    if not ID_PATTERN.fullmatch(bundle_id):
        raise ValueError("Bundle ID must be 32 lowercase hexadecimal characters")
    agent_root, truth_root = separated_roots(agent_root, truth_root)
    agent_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    truth_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundle = agent_root / bundle_id
    evaluator = truth_root / bundle_id
    days = tuple(simulate(scenario))
    with ExitStack() as rollback:
        bundle.mkdir(mode=0o700)
        rollback.callback(bundle.rmdir)
        evaluator.mkdir(mode=0o700)
        rollback.callback(evaluator.rmdir)

        with tempfile.TemporaryDirectory(dir=agent_root) as stage, tempfile.TemporaryDirectory(dir=truth_root) as truth_stage:
            database = Path(stage) / "records.sqlite"
            contract, row_counts, logical_hash = build_records(database, days)
            database_hash = hash_file(database)

            staged_truth = Path(truth_stage) / "truth.json"
            truth = make_truth(scenario, days, bundle_id, contract, row_counts, logical_hash, database_hash)
            staged_truth.write_text(json.dumps(truth, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            staged_truth.chmod(0o600)
            database.chmod(0o444)
            truth_path = evaluator / "truth.json"
            os.link(staged_truth, truth_path)
            rollback.callback(truth_path.unlink)
            file_path = bundle / "records.sqlite"
            os.link(database, file_path)
            rollback.callback(file_path.unlink)
            verified = verify_bundle(bundle)
            if verified["sha256"] != database_hash or verified["logical_sha256"] != logical_hash:
                raise ValueError("Published agent package differs from verified staging data")
        rollback.pop_all()
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("generate")
    build.add_argument("scenario")
    build.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    build.add_argument("--seed", type=int)
    build.add_argument("--agent-root", required=True, type=Path)
    build.add_argument("--truth-root", required=True, type=Path)
    build.add_argument("--bundle-id")
    check = commands.add_parser("verify-agent")
    check.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            scenario = load_scenario(args.config, args.scenario, args.seed)
            result = generate(scenario, args.agent_root, args.truth_root, args.bundle_id)
        else:
            result = verify_bundle(args.bundle)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
