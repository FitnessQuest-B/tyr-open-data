"""Private planning, truth derivation and detached packet assembly."""

import hashlib
import hmac
import os
import secrets
import shutil
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import protocol
from generate_synthetic import DEFAULT_CONFIG, generate, separated_roots
from synthetic_model import load_scenario, simulate

SCENARIOS = ("stable", "caffeine_timing", "changing", "travel_gaps")
DAYS = 224
WINDOW_SPANS = ((0, 104), (128, 206), (206, 222))
BENCHMARK_VERSION = 1


def _derive(seed, tag):
    return hmac.new(seed, ("tyr-benchmark-v1:" + tag).encode("ascii"), hashlib.sha256).digest()


def _task(scenario, case_id, source_hash):
    def day(index):
        return (scenario.first_day + timedelta(days=index)).isoformat()

    return protocol.validate_task({
        "version": protocol.VERSION, "case_id": case_id, "source_sha256": source_hash,
        "relationship": [{"id": key, "start": day(start), "end": day(end)}
                         for key, (start, end) in zip(protocol.WINDOWS, WINDOW_SPANS, strict=True)],
        "change": {"start": day(0), "end": day(DAYS)},
    })


def _expected(scenario):
    daily = tuple(simulate(scenario))
    relationships = {}
    for key, (start, end) in zip(protocol.WINDOWS, WINDOW_SPANS, strict=True):
        opportunities = daily[start:end]
        paired = [row for row in opportunities if "nutrition" not in row.omitted and "sleep" not in row.omitted]
        late = sum(row.late_dose for row in paired)
        effects = {row.late_effect_minutes for row in opportunities}
        sufficient = len(paired) >= 30 and min(late, len(paired) - late) >= 10 and len(paired) * 2 >= end - start
        true_effect = next(iter(effects)) if len(effects) == 1 else None
        expected = "inconclusive"
        if sufficient and true_effect is not None:
            expected = "supported" if true_effect <= -protocol.MIN_SLEEP_REDUCTION_MINUTES else "notSupported"
        training_confounder = any(
            phase.from_day < end and phase.until_day > start
            and phase.settings["late_probability_training"] != phase.settings["late_probability_quiet"]
            for phase in scenario.phases
        )
        relationships[key] = {
            "decision": expected, "embedded_effect_minutes": true_effect,
            "opportunity_days": end - start, "paired_observation_days": len(paired),
            "confounders": ["training_day"] if training_confounder else [],
        }

    changes = []
    for previous, current in zip(scenario.phases, scenario.phases[1:]):
        delta = round(current.settings["weight_delta_kg"] - previous.settings["weight_delta_kg"], 6)
        if abs(delta) >= protocol.MIN_WEIGHT_CHANGE_KG:
            split = scenario.first_day + timedelta(days=current.from_day)
            changes.append({"split": split.isoformat(), "effect_kg": delta})
    return {"relationship": relationships, "change": changes}


def _scenario(name, seed):
    scenario = load_scenario(DEFAULT_CONFIG, name, seed)
    return replace(scenario, days=DAYS, phases=(*scenario.phases[:-1], replace(scenario.phases[-1], until_day=DAYS)))


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(protocol.canonical(value) + "\n")
    path.chmod(0o600)


def prepare(agent_root, evaluator_root, replicates=2, master_seed=None):
    if type(replicates) is not int or not 1 <= replicates <= 10:
        raise ValueError("Choose one to ten replicates per starter design")
    if master_seed is None:
        seed = secrets.token_bytes(32)
    else:
        if len(master_seed) != 64 or any(ch not in "0123456789abcdef" for ch in master_seed):
            raise ValueError("An explicit evaluator seed must be 64 lowercase hexadecimal characters")
        seed = bytes.fromhex(master_seed)
    agent_root, evaluator_root = separated_roots(Path(agent_root), Path(evaluator_root))
    if agent_root.exists() or evaluator_root.exists():
        raise FileExistsError("Choose fresh agent and evaluator roots")
    agent_root.mkdir(parents=True, mode=0o700)
    try:
        evaluator_root.mkdir(parents=True, mode=0o700)
    except OSError:
        agent_root.rmdir()
        raise
    index = {}
    mapper = []
    try:
        with tempfile.TemporaryDirectory(prefix="tyr-benchmark-generator-") as scratch:
            tmp = Path(scratch)
            for name in SCENARIOS:
                for replica in range(replicates):
                    tag = f"{name}:{replica}"
                    case_id = _derive(seed, tag + ":id")[:16].hex()
                    case_seed = int.from_bytes(_derive(seed, tag + ":seed")[:8], "big")
                    scenario = _scenario(name, case_seed)
                    observation = generate(scenario, tmp / "raw-observations", tmp / "truth", case_id)
                    task = _task(scenario, case_id, observation["sha256"])
                    packet = agent_root / case_id
                    packet.mkdir(mode=0o700)
                    data = packet / "records.sqlite"
                    shutil.copyfile(tmp / "raw-observations" / case_id / "records.sqlite", data)
                    data.chmod(0o444)
                    _write(packet / "task.json", task)
                    (packet / "task.json").chmod(0o444)
                    protocol.read_packet(packet)
                    private = evaluator_root / case_id
                    private.mkdir(mode=0o700)
                    shutil.copyfile(tmp / "truth" / case_id / "truth.json", private / "truth.json")
                    (private / "truth.json").chmod(0o600)
                    index[case_id] = {"task_sha256": protocol.digest(task), "expected": _expected(scenario)}
                    mapper.append({"case_id": case_id, "scenario": name, "replicate": replica})
        _write(evaluator_root / "index.json", {
            "version": BENCHMARK_VERSION, "master_seed": seed.hex(), "cases": index, "designs": mapper,
        })
    except BaseException:
        # These directories were created by this operation.
        shutil.rmtree(agent_root)
        shutil.rmtree(evaluator_root)
        raise
    return {"benchmark_version": BENCHMARK_VERSION, "cases": sorted(index), "case_count": len(index)}
