"""Transactional budget reservation and scheduled-run accounting."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import protocol
from responses import PILOT

APPLICATION_ID = 0x54595252
RERUN_OUTPUT_LIMITS = {("B", 0): 3_900, ("C", 0): 512, ("C", 1): 3_900}
SMOKE_STAGES = (("C", 0), ("C", 1))
BATCH_CASES = 8
BATCH_MODES = ("mock-pilot", "live-pilot", "live-pilot-remediated")
MOCK_MODES = ("mock", "mock-pilot")
SCHEMA = """
CREATE TABLE experiment (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL, stop_reason TEXT);
CREATE TABLE run (
    case_id TEXT NOT NULL, arm TEXT NOT NULL, result TEXT,
    PRIMARY KEY(case_id, arm)
);
CREATE TABLE attempt (
    case_id TEXT NOT NULL, arm TEXT NOT NULL, stage INTEGER NOT NULL,
    request_sha256 TEXT NOT NULL, status TEXT NOT NULL, reserved_tokens INTEGER NOT NULL,
    reserved_cost_microusd INTEGER NOT NULL, usage TEXT, result TEXT,
    accounted_tokens INTEGER NOT NULL, accounted_cost_microusd INTEGER NOT NULL,
    created_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, settled_utc TEXT,
    PRIMARY KEY(case_id, arm, stage), FOREIGN KEY(case_id, arm) REFERENCES run(case_id, arm)
);
"""


class BudgetBlocked(ValueError):
    def __init__(self, classification):
        super().__init__(classification)
        self.classification = classification


@dataclass(frozen=True)
class Limits:
    attempts: int = 24
    case_attempts: int = 3
    tokens: int = 24 * (PILOT.input_limit + PILOT.output_limit)
    case_microusd: int = 700_000
    experiment_microusd: int = 5_000_000

    def __post_init__(self):
        ceilings = (24, 3, 24 * (PILOT.input_limit + max(RERUN_OUTPUT_LIMITS.values())), 700_000, 5_000_000)
        if any(type(value) is not int or not 1 <= value <= cap
               for value, cap in zip(asdict(self).values(), ceilings, strict=True)):
            raise ValueError("Budget exceeds the research envelope")


def reservation(output_limit=PILOT.output_limit):
    # Reserve the entire published context window as input, plus all output.
    # Reapproval of the model, tier and tariff is required for any live dispatch.
    return {"tokens": PILOT.input_limit + output_limit,
            "cost_microusd": PILOT.cost(PILOT.input_limit, output_limit)}


SMOKE_LIMITS = Limits(attempts=len(SMOKE_STAGES), case_attempts=len(SMOKE_STAGES),
                      tokens=sum(reservation()["tokens"] for _ in SMOKE_STAGES),
                      case_microusd=650_000, experiment_microusd=650_000)
RERUN_LIMITS = Limits(attempts=len(SMOKE_STAGES), case_attempts=len(SMOKE_STAGES),
                      tokens=sum(reservation(RERUN_OUTPUT_LIMITS[stage])["tokens"] for stage in SMOKE_STAGES),
                      case_microusd=650_000, experiment_microusd=650_000)
BATCH_LIMITS = Limits(attempts=24, tokens=BATCH_CASES * sum(
    reservation(cap)["tokens"] for cap in RERUN_OUTPUT_LIMITS.values()),
                      case_microusd=650_000, experiment_microusd=5_000_000)


def verify_live_schedule(limits, stage_caps, cases):
    cost = sum(reservation(cap)["cost_microusd"] for cap in stage_caps)
    tokens = sum(reservation(cap)["tokens"] for cap in stage_caps)
    if (cost > limits.case_microusd or cost * cases > limits.experiment_microusd
            or len(stage_caps) > limits.case_attempts or len(stage_caps) * cases > limits.attempts
            or tokens * cases > limits.tokens):
        raise ValueError("The live schedule exceeds its full-context reservation limits")


class Ledger:
    def __init__(self, path, limits, schedule, provenance, *, mode="mock", host_sleep_cases=()):
        if mode not in ("mock", "live-smoke", "live-smoke-rerun", *BATCH_MODES):
            raise ValueError("Unknown research transport mode")
        fixed_limits = RERUN_LIMITS if mode == "live-smoke-rerun" else SMOKE_LIMITS
        if mode in ("live-smoke", "live-smoke-rerun") and (
            limits != fixed_limits or len(schedule) != 2
            or len({case for case, _ in schedule}) != 1 or {arm for _, arm in schedule} != {"A", "C"}
        ):
            raise ValueError("Live smoke requires exactly one approved case and its fixed limits")
        if mode in BATCH_MODES:
            cases = tuple(dict.fromkeys(case for case, _ in schedule))
            if (limits != BATCH_LIMITS or len(cases) != BATCH_CASES
                    or list(schedule) != [(case, arm) for case in cases for arm in ("A", "B", "C")]):
                raise ValueError("The pilot requires eight paired cases and its fixed limits")
            if mode != "mock-pilot":
                verify_live_schedule(limits, tuple(RERUN_OUTPUT_LIMITS.values()), BATCH_CASES)
        self.path = Path(path)
        self.limits = limits
        self.mode = mode
        self.host_sleep_cases = frozenset(host_sleep_cases)
        if self.host_sleep_cases and (mode != "mock-pilot"
                                      or not self.host_sleep_cases <= {case for case, arm in schedule if arm == "C"}):
            raise ValueError("Host-selected sleep requires scheduled mock pilot cases")
        binding = {"policy": asdict(limits), "model": asdict(PILOT), "schedule": schedule,
                   "provenance": provenance, "transport": mode, "max_retries": 0}
        if self.host_sleep_cases:
            binding["host_sleep_cases"] = sorted(self.host_sleep_cases)
        if mode in ("live-smoke-rerun", *BATCH_MODES):
            stages = SMOKE_STAGES if mode == "live-smoke-rerun" else RERUN_OUTPUT_LIMITS
            binding["stage_output_limits"] = {f"{arm}-{stage}": RERUN_OUTPUT_LIMITS[arm, stage]
                                              for arm, stage in stages}
        self.binding = protocol.canonical(binding)
        folder = self.path.parent
        if folder.is_symlink() or folder.stat().st_mode & 0o077 or folder.stat().st_uid != os.getuid():
            raise ValueError("Choose an owner-only research workspace")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            with self.transaction():
                pass
        else:
            os.close(fd)
            with closing(self._connect()) as db:
                db.executescript("BEGIN IMMEDIATE; " + SCHEMA)
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("INSERT INTO experiment(id,binding) VALUES (1,?)", (self.binding,))
                db.executemany("INSERT INTO run(case_id,arm) VALUES (?,?)", schedule)
                db.commit()

    def _connect(self):
        stat = self.path.lstat()
        if (self.path.is_symlink() or not self.path.is_file() or stat.st_nlink != 1
                or stat.st_mode & 0o077 or stat.st_uid != os.getuid()):
            raise ValueError("Expected a private regular research ledger")
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def transaction(self):
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("Unexpected research ledger")
            schema = sorted(" ".join(row[0].split()) for row in db.execute(
                "SELECT sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"))
            expected = sorted(" ".join(statement.split()) for statement in SCHEMA.split(";") if statement.strip())
            if schema != expected or db.execute("SELECT binding FROM experiment WHERE id=1").fetchone()[0] != self.binding:
                raise ValueError("Research ledger does not match the frozen schedule and policy")
            yield db
            db.commit()

    def output_limit(self, arm, stage):
        if self.mode in ("live-smoke-rerun", *BATCH_MODES):
            return RERUN_OUTPUT_LIMITS[arm, stage]
        return PILOT.output_limit

    def reserve(self, case, arm, stage, request_hash):
        key = (case, arm, stage)
        with self.transaction() as db:
            run = db.execute("SELECT result FROM run WHERE case_id=? AND arm=?", key[:2]).fetchone()
            if run is None or run["result"] is not None or not (arm == "B" and stage == 0 or arm == "C" and stage in (0, 1)):
                raise BudgetBlocked("unscheduled_stage")
            host_sleep = arm == "C" and case in self.host_sleep_cases
            if host_sleep and stage != 1:
                raise BudgetBlocked("unscheduled_stage")
            existing = db.execute(
                "SELECT * FROM attempt WHERE case_id=? AND arm=? AND stage=?", key).fetchone()
            if existing and existing["request_sha256"] != request_hash:
                raise BudgetBlocked("changed_request")
            if existing and existing["status"] == "settled":
                return json_result(existing["result"])
            stop = db.execute("SELECT stop_reason FROM experiment WHERE id=1").fetchone()[0]
            if stop:
                return {"status": "not_run_" + stop}
            if db.execute("SELECT 1 FROM attempt WHERE status='pending' LIMIT 1").fetchone():
                raise BudgetBlocked("pending_request")
            if stage == 1 and not host_sleep:
                first = db.execute(
                    "SELECT status, result FROM attempt WHERE case_id=? AND arm=? AND stage=0", key[:2]).fetchone()
                allowed = {"tool", "skip"} if self.mode in BATCH_MODES else {"tool"}
                if (first is None or first["status"] != "settled"
                        or json_result(first["result"])["status"] not in allowed):
                    raise BudgetBlocked("unscheduled_stage")
            attempts, tokens, cost, case_attempts, case_cost = db.execute("""
                SELECT count(*), COALESCE(sum(accounted_tokens),0), COALESCE(sum(accounted_cost_microusd),0),
                       count(CASE WHEN case_id=? THEN 1 END),
                       COALESCE(sum(CASE WHEN case_id=? THEN accounted_cost_microusd END),0) FROM attempt
                """, (case, case)).fetchone()
            cap = reservation(self.output_limit(arm, stage))
            if (attempts >= self.limits.attempts or case_attempts >= self.limits.case_attempts
                    or tokens + cap["tokens"] > self.limits.tokens
                    or cost + cap["cost_microusd"] > self.limits.experiment_microusd
                    or case_cost + cap["cost_microusd"] > self.limits.case_microusd):
                db.execute("UPDATE experiment SET stop_reason='budget_exhausted' WHERE id=1")
                return {"status": "budget_exhausted"}
            db.execute("""
                INSERT INTO attempt(case_id,arm,stage,request_sha256,status,reserved_tokens,reserved_cost_microusd,
                                    accounted_tokens,accounted_cost_microusd)
                VALUES (?,?,?,?,'pending',?,?,?,?)
                """, (*key, request_hash, cap["tokens"], cap["cost_microusd"], cap["tokens"], cap["cost_microusd"]))
        return None

    def settle(self, case, arm, stage, usage=None, result=None):
        with self.transaction() as db:
            key = (case, arm, stage)
            if usage is None:
                db.execute("UPDATE experiment SET stop_reason='uncertain_provider_request' WHERE id=1")
                update = db.execute("""
                    UPDATE attempt SET status='uncertain',settled_utc=CURRENT_TIMESTAMP
                    WHERE case_id=? AND arm=? AND stage=? AND status='pending'
                    """, key)
            else:
                incoming, outgoing = usage["input_tokens"], usage["output_tokens"]
                if not 0 < incoming <= PILOT.input_limit or not 0 <= outgoing <= self.output_limit(arm, stage):
                    raise ValueError("Usage exceeds the reserved input or output limit")
                tokens, cost = incoming + outgoing, PILOT.cost(incoming, outgoing)
                update = db.execute("""
                    UPDATE attempt SET status='settled',usage=?,result=?,accounted_tokens=?,
                        accounted_cost_microusd=?,settled_utc=CURRENT_TIMESTAMP
                    WHERE case_id=? AND arm=? AND stage=? AND status='pending'
                      AND reserved_tokens>=? AND reserved_cost_microusd>=?
                    """, (protocol.canonical(usage), protocol.canonical(result), tokens, cost, *key, tokens, cost))
            if update.rowcount != 1:
                raise ValueError("Attempt is missing or already settled")

    def finish(self, case, arm, result):
        value = protocol.canonical(result)
        with self.transaction() as db:
            update = db.execute("UPDATE run SET result=? WHERE case_id=? AND arm=? AND result IS NULL",
                                (value, case, arm))
            if update.rowcount != 1 and self._result(db, case, arm) != result:
                raise ValueError("Scheduled result is immutable")

    @staticmethod
    def _result(db, case, arm):
        row = db.execute("SELECT result FROM run WHERE case_id=? AND arm=?", (case, arm)).fetchone()
        return json_result(row["result"])

    def result(self, case, arm):
        with self.transaction() as db:
            return self._result(db, case, arm)

    def report(self):
        with self.transaction() as db:
            runs = [{"case_id": row["case_id"], "arm": row["arm"], "result": json_result(row["result"])}
                    for row in db.execute("SELECT * FROM run ORDER BY case_id,arm")]
            attempts = [dict(row) for row in db.execute(
                "SELECT * FROM attempt ORDER BY case_id,arm,stage")]
        charges = {"actual_api_calls": 0, "actual_cost_microusd": 0} if self.mode in MOCK_MODES else {}
        return {"mode": self.mode, **charges, "scheduled_runs": len(runs),
                "recorded_runs": sum(row["result"] is not None for row in runs),
                "accounted_cost_microusd": sum(row["accounted_cost_microusd"] for row in attempts),
                "accounted_tokens": sum(row["accounted_tokens"] for row in attempts),
                "runs": runs, "attempts": attempts}


def json_result(text):
    # Ledger JSON was written canonically by the broker.
    return None if text is None else json.loads(text)
