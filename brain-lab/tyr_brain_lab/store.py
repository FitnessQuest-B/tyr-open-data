"""Typed, source-bound persistence with the versioned portable Brain tables."""

import json
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path

from read_export import check_export_file
from schema_support import ROOT, digest, load_contract, quote, schema_objects, stable_json
from . import analysis, codec
from .source import CONTRACT_VERSION

LAB_ROOT = Path(__file__).resolve().parents[1]
POLICY = "offline-sensitivity-v1"
INSERTS = {
    "brain_hypothesis", "brain_hypothesis_metric", "brain_evaluation", "brain_evaluation_evidence",
    "brain_assessment", "brain_memory_node", "brain_memory_link", "lab_run",
}


class StaleSource(ValueError):
    pass


@lru_cache(maxsize=1)
def _schema():
    folder, contract = load_contract(CONTRACT_VERSION)
    artifact = contract["artifacts"]["brain-lab"]
    ddl = (folder / artifact["sql"]).read_text()
    metadata = (LAB_ROOT / "lab_metadata.sql").read_text()
    with closing(sqlite3.connect(":memory:")) as fresh:
        fresh.executescript(ddl)
        if schema_objects(fresh) != artifact["objects"]:
            raise ValueError("The committed Brain schema differs from the versioned manifest")
        fresh.executescript(metadata)
        return artifact, ddl, metadata, schema_objects(fresh)


def _verify_schema(db):
    artifact, _, _, expected = _schema()
    if (db.execute("PRAGMA application_id").fetchone()[0] != artifact["application_id"]
            or db.execute("PRAGMA user_version").fetchone()[0] != artifact["file_schema_version"]
            or schema_objects(db) != expected):
        raise ValueError("Expected an intact Brain Lab database made by the Lab initializer")


def _verify_integrity(db):
    if [row[0] for row in db.execute("PRAGMA integrity_check")] != ["ok"]:
        raise ValueError("Brain Lab integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Brain Lab has inconsistent foreign keys")


def _path(path, source):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Use an ordinary file as the Lab database")
    path = path.resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Keep Lab data outside the candidate checkout")
    if path == source.path or (path.exists() and path.samefile(source.path)):
        raise ValueError("The Lab database must be a separate file from the source")
    return path


def initialize(path, source):
    path = _path(path, source)
    if source.owner is None:
        raise ValueError("Choose a source containing one local owner record")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        raise FileExistsError("A database already exists at the requested Lab path")
    _, ddl, metadata, _ = _schema()
    interventions, periods = source.intervention_identities()
    with tempfile.TemporaryDirectory(dir=path.parent) as job:
        pending = Path(job) / "lab.sqlite"
        with closing(sqlite3.connect(pending)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(ddl)
            db.executescript(metadata)
            with db:
                db.execute("INSERT INTO lab_source VALUES (1, ?, 1, ?, ?)", (
                    uuid.uuid4().hex, stable_json(source.manifest), int(time.time()),
                ))
                db.executemany("INSERT INTO interventions (id,uuid) VALUES (?,?)", interventions)
                db.executemany("INSERT INTO intervention_periods (id,intervention_id,uuid) VALUES (?,?,?)", periods)
            _verify_schema(db)
            _verify_integrity(db)
        source.assert_unchanged()
        pending.chmod(0o600)
        os.link(pending, path)
    return {"status": "initialized", "source": source.manifest,
            "mirrored_interventions": len(interventions), "mirrored_periods": len(periods)}


def _authorize(action, relation, column, database, trigger):
    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if database == "main" or (database is None and column == ""):
            return sqlite3.SQLITE_OK
    if database != "main":
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_INSERT and relation in INSERTS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_DELETE and relation == "brain_assessment" and trigger:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _binding(db, source):
    bound = db.execute("SELECT lab_id, source_manifest_json FROM lab_source WHERE singleton=1").fetchone()
    if bound is None:
        raise ValueError("Brain Lab is missing its source binding")
    if json.loads(bound["source_manifest_json"]) != source.manifest:
        raise StaleSource("Source fingerprint differs; existing Lab findings are stale for this file")
    return bound["lab_id"]


@contextmanager
def open_lab(path, source, *, write=False, check_binding=True):
    path = _path(path, source)
    if write and not check_binding:
        raise ValueError("All Lab writes require a matching source binding")
    if write and not path.is_file():
        raise ValueError("Initialize the separate Lab database first")
    if write:
        if path.stat().st_nlink != 1:
            raise ValueError("Use a Lab database file with a single filesystem link")
    # Prove the target is a known local Lab before a writable connection is made.
    if write:
        with open_lab(path, source):
            pass

    if not write:
        check_export_file(path)
    mode = "rw" if write else "ro"
    db = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, cached_statements=0)
    try:
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = sqlite3.Row
        if write:
            db.execute("BEGIN IMMEDIATE")
        else:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
        _verify_schema(db)
        binding = _binding(db, source) if check_binding else None
        if write:
            # Python UDFs are not marked innocuous. Turn schema trust on only
            # after checking the exact DDL inside this writer transaction.
            db.create_function("tyr_brain_specification_valid", 2, codec.validate_specification, deterministic=True)
            db.execute("PRAGMA trusted_schema=ON")
            db.set_authorizer(_authorize)
        yield db, binding
        if write:
            source.assert_unchanged()
            db.commit()
    finally:
        db.close()


def status(path, source):
    try:
        with open_lab(path, source) as (db, _):
            runs = db.execute("SELECT count(*) FROM lab_run").fetchone()[0]
    except StaleSource:
        return {"status": "stale", "message": "The inspected source no longer matches this Lab binding"}
    return {"status": "current", "source": source.manifest, "runs": runs}


def _insert(db, table, **values):
    names = ", ".join(map(quote, values))
    placeholders = ", ".join("?" for _ in values)
    return db.execute(f"INSERT INTO {quote(table)} ({names}) VALUES ({placeholders})", tuple(values.values())).lastrowid


def _question(plan):
    return digest({field: plan[field] for field in ("method", "metric", "minimum_change_milli", "late_clock_minute")})


def _new_hypothesis(db, plan, hypothesis_uuid, now, claim):
    if plan["method"] == "late-caffeine-sleep":
        title = "Caffeine timing and following sleep duration"
        statement = "Is the recorded later caffeine dose associated with meaningfully shorter following sleep?"
    else:
        title = f"Change in recorded {plan['metric']}"
        statement = "Is the difference across the declared split large enough to meet the planned threshold?"
    pk = _insert(db, "brain_hypothesis", uuid=hypothesis_uuid, title=title, statement=statement,
                 domain="personal_observations", hypothesis_type=claim, claim_type=claim, origin_type="observation",
                 origin_ref=_question(plan), registration_mode="retrospective",
                 registered_at=now, created_at=now, updated_at=now)
    _insert(db, "brain_hypothesis_metric", uuid=str(uuid.uuid4()), hypothesis_id=pk,
            metric_key=plan["metric"], role="outcome", created_at=now)
    return db.execute("SELECT * FROM brain_hypothesis WHERE id=?", (pk,)).fetchone()


def _specification(hypothesis, plan, source, evidence_hash):
    definition = {
        "uuid": hypothesis["uuid"], "title": hypothesis["title"], "statement": hypothesis["statement"],
        "domain": hypothesis["domain"], "hypothesisType": hypothesis["hypothesis_type"],
        "claimType": hypothesis["claim_type"], "originType": hypothesis["origin_type"],
        "originRef": hypothesis["origin_ref"], "registrationMode": hypothesis["registration_mode"],
        "registeredAt": hypothesis["registered_at"], "definitionVersion": hypothesis["definition_version"],
    }
    return codec.specification({
        "hypothesis": definition, "metricBindings": [{"metricKey": plan["metric"], "role": "outcome"}],
        "interventionBindings": [], "interventionOutcomes": [],
        "analysisParameters": {
            "plan": plan, "sourceSha256": source.manifest["sha256"], "inputSha256": evidence_hash,
            "sensitivityBlockDays": analysis.BLOCK_DAYS, "calendarEncoding": "civil_labels_as_utc_midnight",
        },
    })


def _persist_evaluation(db, hypothesis, result, source, previous, now):
    plan = result["plan"]
    encoded, spec_hash = _specification(hypothesis, plan, source, result["input_sha256"])
    sequence = db.execute(
        "SELECT max(coalesce((SELECT seq FROM sqlite_sequence WHERE name='brain_evaluation'),0), "
        "coalesce((SELECT max(id) FROM brain_evaluation),0)) + 1"
    ).fetchone()[0]
    evaluation_uuid = str(uuid.uuid4())
    for evidence in result["evidence"]:
        stats = evidence["statistics"]
        expected = evidence["expected_days"]
        _insert(
            db, "brain_evaluation_evidence", uuid=str(uuid.uuid4()), evaluation_id=sequence,
            metric_key=plan["metric"], metric_role="outcome", cohort_role=evidence["role"], source_type="aggregate",
            window_start=analysis.seconds(analysis.day(evidence["window_start"])),
            window_end=analysis.seconds(analysis.day(evidence["window_end_exclusive"])),
            sample_count=stats["n"], expected_count=expected, mean=stats["mean"],
            standard_deviation=stats["population_sd"], minimum=stats["min"], maximum=stats["max"],
            coverage_ratio=stats["n"] / expected if expected else None, canonical_unit=result["unit"],
            source_fingerprint=evidence["input_sha256"], extra_codec_version=1,
            extra_json=codec.envelope({"references": evidence["reference_rows"], "sourceSha256": source.manifest["sha256"]}),
        )
    sensitivity = result["sensitivity_range"]
    _insert(
        db, "brain_evaluation", id=sequence, uuid=evaluation_uuid, hypothesis_id=hypothesis["id"],
        algorithm_id=plan["method"], algorithm_version=analysis.VERSION, evaluation_mode="exploratory",
        spec_registered_at=now, test_window_start=analysis.seconds(analysis.day(plan["start"])),
        test_window_end=analysis.seconds(analysis.day(result["analysis_window_end_exclusive"])),
        executed_at=now, spec_hash=spec_hash, specification_codec_version=1, specification_json=encoded,
        input_manifest_hash=result["input_sha256"], reproducibility_level="fingerprinted",
        supersedes_evaluation_uuid=previous["evaluation_uuid"] if previous else None, primary_metric_key=plan["metric"],
        effect_estimate=result["effect"], effect_unit=result["unit"] if result["effect"] is not None else None,
        interval_lower=sensitivity[0] if sensitivity else None, interval_upper=sensitivity[1] if sensitivity else None,
        interval_method=result["sensitivity_method"] if sensitivity else None,
        sample_count=result["eligible_days"], coverage_ratio=result["coverage_ratio"],
        evidence_decision=result["evidence_decision"], result_claim_type=result["claim_type"],
        failure_class="insufficientData" if result["evidence_decision"] == "inconclusive" and not sensitivity else None,
        limitations_code="observational_sensitivity_only",
        diagnostics_codec_version=1, diagnostics_json=codec.envelope({
            "limitations": result["limitations"], "observedDays": result["eligible_days"],
            "expectedDays": result["expected_days"], "competingExplanations": result["confounders"],
        }),
    )
    return evaluation_uuid


def _assessment(db, hypothesis, evaluation_uuid, result, previous, now):
    decision = result["evidence_decision"]
    earlier = json.loads(previous["assessment_json"])["decision"] if previous else None
    lost_support = earlier == "supported" and decision != "supported"
    assessment = {
        "decision": decision, "claim_strength": result["claim_type"],
        "applicability": "recheckRequired" if lost_support or decision == "inconclusive" else "current",
        "reason": "earlier_support_not_repeated" if lost_support else "offline_exploratory_comparison",
        "evidence_strength": "none" if decision == "inconclusive" else "weak",
        "policy_version": POLICY, "execution_time": now,
    }
    _insert(
        db, "brain_assessment", hypothesis_id=hypothesis["id"], evidence_decision=decision,
        claim_strength=assessment["claim_strength"], applicability=assessment["applicability"],
        latest_evaluation_uuid=evaluation_uuid, evidence_strength=assessment["evidence_strength"],
        policy_version=POLICY, assessed_at=now, review_reason_code=assessment["reason"],
        failure_disposition="insufficientEvidence" if decision == "inconclusive" else None,
    )
    return assessment


def _knowledge(db, hypothesis, evaluation, previous, decision, now):
    row = db.execute(
        "SELECT id FROM brain_memory_node WHERE source_entity_type='hypothesis' AND source_entity_uuid=?",
        (hypothesis["uuid"],),
    ).fetchone()
    hypothesis_node = row[0] if row else _insert(
        db, "brain_memory_node", uuid=str(uuid.uuid4()), node_type="source", source_entity_type="hypothesis",
        source_entity_uuid=hypothesis["uuid"], title=hypothesis["title"], retrieval_tier="primary",
        review_state="unreviewed", created_at=now, updated_at=now,
    )
    evaluation_node = _insert(
        db, "brain_memory_node", uuid=str(uuid.uuid4()), node_type="source", source_entity_type="evaluation",
        source_entity_uuid=evaluation, title="Offline exploratory evaluation", retrieval_tier="secondary",
        review_state="unreviewed", created_at=now, updated_at=now,
    )
    _insert(db, "brain_memory_link", uuid=str(uuid.uuid4()), from_node_id=evaluation_node,
            to_node_id=hypothesis_node, relation_type="supports" if decision == "supported" else "relevantTo",
            source_evaluation_uuid=evaluation, created_at=now)
    if previous:
        row = db.execute("SELECT id FROM brain_memory_node WHERE source_entity_type='evaluation' AND source_entity_uuid=?",
                         (previous["evaluation_uuid"],)).fetchone()
        if row:
            _insert(db, "brain_memory_link", uuid=str(uuid.uuid4()), from_node_id=evaluation_node,
                    to_node_id=row[0], relation_type="supersedes", source_evaluation_uuid=evaluation, created_at=now)


def record(path, source, plan, hypothesis_uuid=None):
    result = analysis.analyze(source, plan)
    now = int(time.time())
    if analysis.seconds(analysis.day(result["analysis_window_end_exclusive"])) > now:
        raise ValueError("The recorded analysis window must have ended")
    result_hash = digest(result)
    with open_lab(path, source, write=True) as (db, lab_id):
        namespace = uuid.UUID(hex=lab_id)
        if hypothesis_uuid is None:
            hypothesis_uuid = str(uuid.uuid5(namespace, digest(plan)))
        run_key = digest({"source": source.manifest["sha256"], "plan": plan,
                          "hypothesis": hypothesis_uuid, "algorithm_version": analysis.VERSION})
        existing = db.execute("SELECT * FROM lab_run WHERE run_key=?", (run_key,)).fetchone()
        if existing:
            if existing["result_sha256"] != result_hash:
                raise ValueError("A saved run no longer reproduces")
            return _receipt(existing, "already_recorded")
        hypothesis = db.execute("SELECT * FROM brain_hypothesis WHERE uuid=?", (hypothesis_uuid,)).fetchone()
        previous = None
        if hypothesis is not None:
            if hypothesis["archived_at"] is not None or hypothesis["origin_ref"] != _question(plan):
                raise ValueError("Reassessment must keep the active hypothesis, metric and comparison parameters")
            previous = db.execute(
                "SELECT lab_run.* FROM lab_run JOIN brain_evaluation ON uuid = evaluation_uuid "
                "WHERE hypothesis_uuid=? ORDER BY executed_at DESC, brain_evaluation.id DESC LIMIT 1",
                (hypothesis_uuid,),
            ).fetchone()
            if previous and plan["start"] < json.loads(previous["plan_json"])["end_exclusive"]:
                raise ValueError("Reassessment needs a later non-overlapping analysis window")
        else:
            if hypothesis_uuid != str(uuid.uuid5(namespace, digest(plan))):
                raise ValueError("The reassessment hypothesis was not found in this Lab")
            hypothesis = _new_hypothesis(db, plan, hypothesis_uuid, now, result["claim_type"])
        evaluation = _persist_evaluation(db, hypothesis, result, source, previous, now)
        assessment = _assessment(db, hypothesis, evaluation, result, previous, now)
        _knowledge(db, hypothesis, evaluation, previous, assessment["decision"], now)
        _insert(db, "lab_run", run_key=run_key, hypothesis_uuid=hypothesis_uuid, evaluation_uuid=evaluation,
                plan_json=stable_json(plan), result_sha256=result_hash, result_json=stable_json(result),
                assessment_json=stable_json(assessment), recorded_at=now)
        return _receipt(db.execute("SELECT * FROM lab_run WHERE run_key=?", (run_key,)).fetchone(), "recorded")


def _receipt(row, status):
    return {
        "status": status, "run_key": row["run_key"], "hypothesis_uuid": row["hypothesis_uuid"],
        "evaluation_uuid": row["evaluation_uuid"], "result_sha256": row["result_sha256"],
        "assessment": json.loads(row["assessment_json"]),
    }


def inspect(path, source, run_key=None):
    with open_lab(path, source) as (db, _):
        if run_key is not None:
            row = db.execute("SELECT * FROM lab_run WHERE run_key=?", (run_key,)).fetchone()
            if row is None:
                raise ValueError("Unknown Lab run")
            result = json.loads(row["result_json"])
            if digest(result) != row["result_sha256"]:
                raise ValueError("Saved result integrity check failed")
            return {**_receipt(row, "recorded"), "result": result}
        rows = db.execute(
            "SELECT lab_run.*, brain_hypothesis.title, brain_evaluation.effect_estimate, "
            "brain_evaluation.effect_unit, brain_evaluation.supersedes_evaluation_uuid, "
            "brain_assessment.latest_evaluation_uuid FROM lab_run "
            "JOIN brain_hypothesis ON brain_hypothesis.uuid=hypothesis_uuid "
            "JOIN brain_evaluation ON brain_evaluation.uuid=evaluation_uuid "
            "LEFT JOIN brain_assessment ON brain_assessment.hypothesis_id=brain_hypothesis.id "
            "ORDER BY brain_hypothesis.id, brain_evaluation.executed_at, brain_evaluation.id"
        )
        return [
            {
                **_receipt(row, "recorded"), "title": row["title"], "plan": json.loads(row["plan_json"]),
                "effect": row["effect_estimate"], "unit": row["effect_unit"],
                "supersedes": row["supersedes_evaluation_uuid"],
                "current": row["latest_evaluation_uuid"] == row["evaluation_uuid"],
            }
            for row in rows
        ]


def replay(path, source, run_key):
    saved = inspect(path, source, run_key)
    expected = saved["result"]
    actual = analysis.analyze(source, expected["plan"])
    if digest(actual) != saved["result_sha256"]:
        raise ValueError("Saved result does not reproduce with this source and algorithm")
    return {"status": "reproduced", "run_key": run_key, "result_sha256": saved["result_sha256"]}
