"""Optional model protocol adapters and mock-only bounded request accounting."""

import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import protocol

LEDGER_APPLICATION_ID = 0x54595250
LEDGER = """
CREATE TABLE experiment (id INTEGER PRIMARY KEY CHECK(id=1), policy TEXT NOT NULL);
CREATE TABLE request (
  request_id TEXT PRIMARY KEY, adapter TEXT NOT NULL, model TEXT NOT NULL,
  status TEXT NOT NULL, response TEXT, input_tokens INTEGER, output_tokens INTEGER,
  cost_microusd INTEGER
);
CREATE TABLE attempt (
  request_id TEXT NOT NULL REFERENCES request(request_id), ordinal INTEGER NOT NULL,
  status TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost_microusd INTEGER NOT NULL,
  PRIMARY KEY (request_id, ordinal)
);
"""


class BudgetExceeded(ValueError):
    pass


class UnsentRetryable(ValueError):
    """The mock transport guarantees that the attempt was never submitted."""


class AmbiguousRequest(ValueError):
    """A reservation may have been consumed and needs explicit reconciliation."""


@dataclass(frozen=True)
class Policy:
    max_attempts: int = 4
    max_retries: int = 1
    max_total_tokens: int = 32_000
    max_cost_microusd: int = 0
    max_output_tokens: int = 1600
    input_microusd_per_million: int = 0
    output_microusd_per_million: int = 0
    allow_paid: bool = False
    allow_personal: bool = False

    def __post_init__(self):
        for key, bounds in {
            "max_attempts": (1, 1000), "max_retries": (0, 3), "max_total_tokens": (1, 10**8),
            "max_cost_microusd": (0, 10**9), "max_output_tokens": (1, 16384),
            "input_microusd_per_million": (0, 10**9), "output_microusd_per_million": (0, 10**9),
        }.items():
            value = getattr(self, key)
            if type(value) is not int or not bounds[0] <= value <= bounds[1]:
                raise ValueError(f"Invalid provider policy field {key}")
        if type(self.allow_paid) is not bool or type(self.allow_personal) is not bool:
            raise ValueError("Provider authorization flags must be explicit booleans")

    def cost(self, input_tokens, output_tokens):
        numerator = input_tokens * self.input_microusd_per_million + output_tokens * self.output_microusd_per_million
        return (numerator + 999_999) // 1_000_000


class ResponsesAdapter:
    """Convert text-only observation requests to the OpenAI Responses shape."""

    name = "openai-responses"

    def request(self, model, prompt, output_limit):
        return {"model": model, "input": prompt, "max_output_tokens": output_limit, "store": False}

    def response(self, payload):
        if payload.get("status") != "completed":
            raise ValueError("Expected a completed mock Responses payload")
        texts = [
            part["text"] for item in payload["output"]
            if item.get("type") == "message" and item.get("role") == "assistant"
            for part in item["content"] if part.get("type") == "output_text" and type(part.get("text")) is str
        ]
        if len(texts) != 1:
            raise ValueError("Expected exactly one assistant output-text item")
        usage = payload["usage"]
        return texts[0], payload["model"], usage["input_tokens"], usage["output_tokens"]


class LocalAdapter:
    """A small JSON contract for an optional local model driver."""

    name = "local-json"

    def request(self, model, prompt, output_limit):
        return {"model": model, "prompt": prompt, "max_new_tokens": output_limit}

    def response(self, payload):
        return payload["text"], payload["model"], payload["prompt_tokens"], payload["generated_tokens"]


class MockTransport:
    """Provide in-memory responses or prescribed failure outcomes. No IO transport."""

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        payload = next(self.outcomes)
        if isinstance(payload, Exception):
            raise payload
        return payload


class Client:
    def __init__(self, path, policy, adapter, transport):
        if type(transport) is not MockTransport:
            raise ValueError("This candidate supports the in-memory mock transport only")
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("Use a separate regular provider-ledger file")
        self.path = self.path.resolve()
        self.policy = policy
        self.adapter = adapter
        self.transport = transport

    @contextmanager
    def _transaction(self):
        created = False
        try:
            handle = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not self.path.is_file() or self.path.is_symlink() or self.path.stat().st_nlink != 1:
                raise ValueError("Expected a separate regular provider ledger")
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as probe:
                if probe.execute("PRAGMA application_id").fetchone()[0] != LEDGER_APPLICATION_ID:
                    raise ValueError("The existing file is outside the provider-ledger contract")
        else:
            os.close(handle)
            created = True
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                if created:
                    for statement in LEDGER.strip().split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute(f"PRAGMA application_id={LEDGER_APPLICATION_ID}")
                    db.execute("INSERT INTO experiment VALUES (1, ?)", (protocol.canonical(asdict(self.policy)),))
                    # Publish an empty usable ledger even if the first reservation is refused.
                    db.commit()
                    db.execute("BEGIN IMMEDIATE")
                schema = sorted(" ".join(row[0].split()) for row in db.execute(
                    "SELECT sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
                ))
                expected = sorted(" ".join(command.split()) for command in LEDGER.split(";") if command.strip())
                if (db.execute("PRAGMA application_id").fetchone()[0] != LEDGER_APPLICATION_ID or schema != expected):
                    raise ValueError("The provider ledger schema does not match")
                policy = db.execute("SELECT policy FROM experiment WHERE id=1").fetchone()
                if policy is None or policy[0] != protocol.canonical(asdict(self.policy)):
                    raise ValueError("The resumed experiment must use its original budget and authorizations")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _reserve(self, request_id, model, max_tokens, max_cost):
        with self._transaction() as db:
            request = db.execute("SELECT * FROM request WHERE request_id=?", (request_id,)).fetchone()
            if request is not None and request["status"] == "complete":
                return self._receipt(request, cached=True)
            if request is not None and request["status"] == "pending":
                raise AmbiguousRequest("Earlier attempt is unresolved; automatic retry is blocked")
            attempt = db.execute("SELECT count(*) FROM attempt WHERE request_id=?", (request_id,)).fetchone()[0]
            if attempt >= self.policy.max_retries + 1:
                raise BudgetExceeded("Per-request retry limit reached")
            totals = self._totals(db)
            if (totals["attempts"] >= self.policy.max_attempts
                    or totals["accounted_tokens"] + max_tokens > self.policy.max_total_tokens
                    or totals["accounted_cost_microusd"] + max_cost > self.policy.max_cost_microusd):
                raise BudgetExceeded("Experiment request, token or monetary budget would be exceeded")
            if request is None:
                db.execute("INSERT INTO request (request_id,adapter,model,status) VALUES (?, ?, ?, 'pending')",
                           (request_id, self.adapter.name, model))
            else:
                db.execute("UPDATE request SET status='pending' WHERE request_id=?", (request_id,))
            db.execute("INSERT INTO attempt VALUES (?, ?, 'pending', ?, ?)",
                       (request_id, attempt + 1, max_tokens, max_cost))
            return None

    @staticmethod
    def _totals(db):
        attempts, pending_tokens, pending_cost = db.execute("""
            SELECT count(*), coalesce(sum(CASE WHEN status='pending' THEN reserved_tokens END), 0),
                   coalesce(sum(CASE WHEN status='pending' THEN reserved_cost_microusd END), 0)
            FROM attempt
        """).fetchone()
        count, tokens, cost = db.execute("""
            SELECT count(*), coalesce(sum(input_tokens + output_tokens), 0), coalesce(sum(cost_microusd),0)
            FROM request WHERE status='complete'
        """).fetchone()
        return {"attempts": attempts, "completed": count, "simulated_tokens": tokens,
                "simulated_cost_microusd": cost, "accounted_tokens": tokens + pending_tokens,
                "accounted_cost_microusd": cost + pending_cost, "actual_api_calls": 0, "actual_cost_microusd": 0}

    def accounting(self):
        with self._transaction() as db:
            return self._totals(db)

    @staticmethod
    def _receipt(row, cached):
        return {
            "request_id": row["request_id"], "adapter": row["adapter"], "model": row["model"],
            "text": row["response"], "cached": cached, "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"], "simulated_cost_microusd": row["cost_microusd"],
            "actual_api_calls": 0, "actual_cost_microusd": 0,
        }

    def call(self, model, observations, *, data_class="synthetic", billable=False, dry_run=False):
        if type(model) is not str or not 1 <= len(model) <= 120:
            raise ValueError("Choose a bounded model identifier")
        if data_class not in {"synthetic", "personal"} or (data_class == "personal" and not self.policy.allow_personal):
            raise ValueError("Personal-data transfer requires separate authorization")
        if type(billable) is not bool or (billable and not self.policy.allow_paid):
            raise ValueError("Billable inference requires explicit experiment authorization")
        if billable and not (self.policy.input_microusd_per_million or self.policy.output_microusd_per_million):
            raise ValueError("Configure the simulated rates for a billable dry-run or mock")
        prompt = protocol.canonical(observations)
        if len(prompt) > 64_000:
            raise ValueError("Provider context exceeds the approved offline envelope")
        payload = self.adapter.request(model, prompt, self.policy.max_output_tokens)
        # This mock bound includes serialized bytes and a fixed framing allowance.
        # A future live driver must replace it with a model-specific verified bound.
        input_bound = len(protocol.canonical(payload).encode("utf-8")) + 128
        budget_tokens = input_bound + self.policy.max_output_tokens
        budget_cost = self.policy.cost(input_bound, self.policy.max_output_tokens)
        request_id = protocol.digest({"adapter": self.adapter.name, "payload": payload, "data_class": data_class,
                                      "billable": billable})
        if dry_run:
            return {"request_id": request_id, "model": model, "status": "dry_run",
                    "reserved_tokens": budget_tokens, "reserved_cost_microusd": budget_cost,
                    "fits_per_experiment_limit": budget_tokens <= self.policy.max_total_tokens
                    and budget_cost <= self.policy.max_cost_microusd, "actual_api_calls": 0}
        for _ in range(self.policy.max_retries + 1):
            cached = self._reserve(request_id, model, budget_tokens, budget_cost)
            if cached:
                return cached
            try:
                raw = self.transport.send(payload)
            except UnsentRetryable:
                with self._transaction() as db:
                    db.execute("UPDATE attempt SET status='unsent' WHERE request_id=? AND status='pending'", (request_id,))
                    db.execute("UPDATE request SET status='unsent' WHERE request_id=?", (request_id,))
                continue
            except Exception as error:
                raise AmbiguousRequest("Mock response status is unresolved; the reservation remains") from error
            try:
                output, returned_model, used_input, used_output = self.adapter.response(raw)
                if (type(output) is not str or not output or len(output) > protocol.MAX_SUBMISSION_SIZE
                        or type(returned_model) is not str or not 1 <= len(returned_model) <= 120
                        or type(used_input) is not int or not 0 <= used_input <= input_bound
                        or type(used_output) is not int or not 0 <= used_output <= self.policy.max_output_tokens):
                    raise ValueError("Invalid usage or model response")
            except (TypeError, ValueError, KeyError, AttributeError) as error:
                raise AmbiguousRequest("Invalid response; the reservation remains") from error
            with self._transaction() as db:
                db.execute("UPDATE attempt SET status='complete' WHERE request_id=? AND status='pending'", (request_id,))
                db.execute("""UPDATE request SET status='complete',model=?,response=?,input_tokens=?,output_tokens=?,
                              cost_microusd=? WHERE request_id=?""", (
                    returned_model, output, used_input, used_output, self.policy.cost(used_input, used_output), request_id,
                ))
                row = db.execute("SELECT * FROM request WHERE request_id=?", (request_id,)).fetchone()
                return self._receipt(row, cached=False)
        raise BudgetExceeded("Per-request retry limit reached")
