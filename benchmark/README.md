# Offline TYR benchmark

The benchmark compares submissions on fixed targets using only synthetic observations. The bundled implementations are the Brain Lab deterministic analysis and two abstaining mock adapters. The mock outputs test exchange formats, budgeting and scoring. They provide no model capability or live cost evidence.

## Run the benchmark

From the repository root, use Python 3.10 or later linked to SQLite 3.41.0 or later with JSON support.

```sh
job=$(mktemp -d)
python3 -B benchmark/bench.py demo --workspace "$job/run"
```

The demo generates two held-out replicates per starter design, runs each implementation twice and writes private evaluator scores. It uses a fresh secret seed by default. A maintainer can reuse the evaluator’s seed with `--seed` and new directories to reproduce the same cases. Keep the seed and private results in the evaluator workspace. The initial dates, day count and task windows are identical across the four designs.

For independent implementations, run `prepare` with separate fresh `--agent-root` and `--evaluator-root` directories. Pass only one opaque packet and the [generic task contract](task.md) into an isolated environment. Submit one result JSON per case named `CASE_ID.json`. Any implementation that can read SQLite and produce the documented JSON can participate. Use a second independent submission directory to measure repeatability.

```sh
python3 -B benchmark/bench.py run-offline --agent-root "$job/run/agent" \
  --worker deterministic --out "$job/another-pass"
python3 -B benchmark/bench.py score --agent-root "$job/run/agent" \
  --evaluator-root "$job/run/evaluator" --submissions "$job/another-pass" \
  --replay "$job/run/deterministic-first"
```

## Isolation

Each packet contains `records.sqlite` and `task.json`. The evaluator root contains the case mapping, seed, ground truth and expected outcomes. Score commands verify the task and record fingerprints against the evaluator binding and keep inputs read-only.

The bundled runner copies only the worker, its allowed code and the records manifest into a detached runtime. Its subprocess gets one packet, a restricted environment and a bounded execution time. An input guard rejects extra file opens, source SQLite writes, network sockets and subprocesses. It is an accidental-access control for the bundled code. Run arbitrary third-party agents in a separate OS sandbox with only the selected packet and generic task contract mounted read-only, a separate output location, and no evaluator files or authoring checkout. The benchmark does not launch arbitrary agent binaries or send payloads to a hosted model.

## Scoring

The evaluator scores three relationship windows and one weight-change search per case. The directional target is a decrease of at least 15 minutes for a later caffeine dose. Cases with insufficient paired evidence are scored separately. The evaluator requires at least 30 opportunities with paired observations, at least ten observations per timing arm and at least 50% paired coverage for a decisive ground-truth label. The bundled worker has its own common-support and block-sensitivity requirements.

Scoring version 2 requires a decisive estimate to agree with the decision and satisfy the evidence rules in the [task contract](task.md). A weight breakpoint must land within 14 days of the simulated shift and match its direction. Recovery, false positives, false alarms and reassessment use qualifying decisions. Separate submitted false-positive and false-alarm counts capture claims made on null targets even when those claims fail qualification. Abstaining on an insufficient relationship window earns credit. Scores also report named confounders, traceable references, unsupported causal claims and matching normalized predictions on replay.

Any causal declaration loses correctness credit because the task supplies observational evidence. Extra hypotheses outside the fixed task are rejected. Runtime and usage are reported for the first submission set. Replay compares predictions independently of timings. Mock counts and costs are separately labeled. Scores describe this synthetic benchmark and should be interpreted with the small number of cases and shared underlying design in mind.

See [provider adapters and accounting](providers.md).
