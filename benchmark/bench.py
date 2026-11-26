"""Prepare, run and score an offline TYR benchmark, with evaluator data kept separate."""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "tools")]

import protocol
import scoring
from generate_synthetic import separated_roots
from prepare import BENCHMARK_VERSION, prepare

WORKERS = ("deterministic", "mock-openai", "mock-local")
WORKER_FILES = (
    "benchmark/worker.py", "benchmark/protocol.py", "benchmark/providers.py",
    "brain-lab/tyr_brain_lab/analysis.py", "brain-lab/tyr_brain_lab/source.py",
    "tools/read_export.py", "tools/schema_support.py", "schema/versions/0.1.0/manifest.json",
)


def detached_worker_files(destination):
    for rel in WORKER_FILES:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)


def _case_ids(agent):
    ids = sorted(entry.name for entry in agent.iterdir())
    if not ids or any(not protocol.ID.fullmatch(item) for item in ids):
        raise ValueError("Agent root must contain only opaque case packets")
    return ids


def run_offline(agent_root, output, worker):
    if worker not in WORKERS:
        raise ValueError("Only bundled offline workers can run in this command")
    agent, output = separated_roots(Path(agent_root), Path(output))
    ids = _case_ids(agent)
    output.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="tyr-benchmark-worker-") as temp:
            scratch = Path(temp)
            runtime = scratch / "runtime"
            detached_worker_files(runtime)
            # Bundled workers get neutral process settings, no seed, credentials,
            # evaluator path, or repository PYTHONPATH.
            env = {"PATH": os.defpath, "TZ": "UTC", "LC_ALL": "C", "TMPDIR": str(scratch),
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
            ledger = scratch / "requests.sqlite"
            for case_id in ids:
                packet = agent / case_id
                task, _ = protocol.read_packet(packet)
                command = [
                    sys.executable, "-B", "-s", str(runtime / "benchmark/worker.py"), str(packet),
                    "--worker", worker, "--confined-inputs",
                ]
                if worker != "deterministic":
                    command.extend(("--ledger", str(ledger)))
                result = subprocess.run(command, cwd=packet, env=env, check=True, timeout=30, capture_output=True)
                if len(result.stdout) > protocol.MAX_SUBMISSION_SIZE:
                    raise ValueError("Bundled worker output exceeds protocol limits")
                value = scoring.submission(json.loads(result.stdout), task)
                (output / f"{case_id}.json").write_text(protocol.canonical(value) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(output)
        raise
    return {"worker": worker, "completed_cases": len(ids), "actual_api_calls": 0}


def _check_submission_dir(path, case_ids):
    if {item.name for item in path.iterdir()} != {f"{case}.json" for case in case_ids}:
        raise ValueError("Expected one submission per opaque case and no extra files")


def score(agent_root, evaluator_root, submissions, *, replay=None):
    agent, evaluator = separated_roots(Path(agent_root), Path(evaluator_root))
    _, submissions = separated_roots(agent, Path(submissions))
    separated_roots(evaluator, submissions)
    index = protocol.read_json(evaluator / "index.json", max_bytes=512_000)
    if index["version"] != BENCHMARK_VERSION:
        raise ValueError("Unsupported evaluator index")
    cases = _case_ids(agent)
    if set(cases) != set(index["cases"]):
        raise ValueError("The evaluator index does not match this packet set")
    _check_submission_dir(submissions, cases)
    if replay is not None:
        _, replay = separated_roots(agent, Path(replay))
        separated_roots(evaluator, replay)
        separated_roots(submissions, replay)
        _check_submission_dir(replay, cases)
    per_case, reports, checks = {}, [], []
    for case_id in cases:
        task, database = protocol.read_packet(agent / case_id)
        case = index["cases"][case_id]
        truth = protocol.read_json(evaluator / case_id / "truth.json", max_bytes=128_000)
        binding = truth["observation_package"]
        if (protocol.digest(task) != case["task_sha256"] or binding["id"] != case_id
                or binding["sha256"] != task["source_sha256"]):
            raise ValueError("Task does not match its private evaluator binding")
        filename = f"{case_id}.json"
        result = scoring.submission(protocol.read_json(submissions / filename), task)
        reports.append(result)
        if replay is not None:
            second = scoring.submission(protocol.read_json(replay / filename), task)
            checks.append(result["worker"] == second["worker"] and
                          protocol.digest(result["predictions"]) == protocol.digest(second["predictions"]))
        per_case[case_id] = scoring.score_case(database, task, case["expected"], result)
        if protocol.hash_file(database) != task["source_sha256"]:
            raise ValueError("Observation bytes changed during scoring")
    if len({row["worker"] for row in reports}) != 1:
        raise ValueError("Use a separate submission directory for each implementation")
    return {"benchmark_version": BENCHMARK_VERSION, "scoring_version": scoring.SCORING_VERSION, "worker": reports[0]["worker"],
            "summary": scoring.aggregate(list(per_case.values()), checks, reports), "cases": per_case}


def demo(workspace, replicates, seed):
    workspace = Path(workspace).resolve()
    if workspace.is_relative_to(ROOT) or ROOT.is_relative_to(workspace):
        raise ValueError("Keep the benchmark workspace separate from the source checkout")
    workspace.mkdir(mode=0o700)
    agent, evaluator = workspace / "agent", workspace / "evaluator"
    prepared = prepare(agent, evaluator, replicates, master_seed=seed)
    summary = {}
    for worker in WORKERS:
        first, second = workspace / f"{worker}-first", workspace / f"{worker}-repeat"
        run_offline(agent, first, worker)
        run_offline(agent, second, worker)
        report = score(agent, evaluator, first, replay=second)
        (evaluator / f"score-{worker}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary[worker] = report["summary"]
    result = {**prepared, "scoring_version": scoring.SCORING_VERSION, "methods": summary}
    (evaluator / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--agent-root", required=True, type=Path)
    prep.add_argument("--evaluator-root", required=True, type=Path)
    smoke = commands.add_parser("demo")
    smoke.add_argument("--workspace", required=True, type=Path)
    for command in (prep, smoke):
        command.add_argument("--replicates", type=int, default=2)
        command.add_argument("--seed", help="Private evaluator seed for exact case replay")
    run = commands.add_parser("run-offline")
    run.add_argument("--agent-root", required=True, type=Path)
    run.add_argument("--worker", choices=WORKERS, default="deterministic")
    run.add_argument("--out", required=True, type=Path)
    scoring_parser = commands.add_parser("score")
    scoring_parser.add_argument("--agent-root", required=True, type=Path)
    scoring_parser.add_argument("--evaluator-root", required=True, type=Path)
    scoring_parser.add_argument("--submissions", required=True, type=Path)
    scoring_parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.agent_root, args.evaluator_root, args.replicates, master_seed=args.seed)
        elif args.command == "run-offline":
            result = run_offline(args.agent_root, args.out, args.worker)
        elif args.command == "score":
            result = score(args.agent_root, args.evaluator_root, args.submissions, replay=args.replay)
        else:
            result = demo(args.workspace, args.replicates, args.seed)
    except subprocess.CalledProcessError as error:
        parser.exit(1, f"Bundled worker failed: {error.stderr.decode('utf-8', 'replace').strip()}\n")
    except (subprocess.TimeoutExpired, OSError, ValueError, sqlite3.Error, TypeError, KeyError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
