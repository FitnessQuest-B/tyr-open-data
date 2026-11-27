"""Read-only verification and export of selected native Brain receipts."""

import hashlib
import json
import math
import re

ALGORITHMS = {
    ("tyr.intervention.matched_daily_means", "1"),
    ("tyr.intervention.matched_daily_means", "2"),
    ("tyr.sleep.fixed_window_duration", "1"),
    ("tyr.exercise_recorded_calories", "1"),
}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def envelope(raw):
    def distinct(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate Brain JSON key")
            result[key] = value
        return result

    def rejected(_):
        raise ValueError("Non-finite Brain JSON value")

    if not isinstance(raw, str) or len(raw) > 2_000_000:
        raise ValueError("Invalid Brain JSON size or storage type")
    try:
        value = json.loads(raw, object_pairs_hook=distinct, parse_constant=rejected)
    except RecursionError as error:
        raise ValueError("Brain JSON is nested too deeply") from error
    if (not isinstance(value, dict) or set(value) != {"payload", "version"}
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["payload"], dict)):
        raise ValueError("Unsupported Brain JSON envelope")
    return value


def match_scope(spec, evidence, receipt):
    params = spec.get("analysisParameters")
    if not isinstance(params, dict):
        raise ValueError("Missing exercise specification")
    lag = params.get("lagDays")
    zone = params.get("explicitReferenceCalendar")
    if (type(lag) is not int or lag not in (0, 1)
            or not isinstance(zone, str) or not zone
            or params.get("temporalPolicy") != "tyr.temporal.v1"
            or params.get("cutoffHour") != 3
            or params.get("meaningfulKcal") != 100
            or params.get("minimumCoverage") != .60
            or params.get("minimumPairs") != 6
            or params.get("minimumWeekdays") != 3
            or params.get("maxPairDistanceDays") != 14
            or not isinstance(spec.get("metricBindings"), list)):
        raise ValueError("Unsupported exercise specification")
    if not all(isinstance(item, dict) for item in spec["metricBindings"]):
        raise ValueError("Unsupported metric bindings")
    bindings = {(item.get("role"), item.get("metricKey"), item.get("lagDays"))
                for item in spec["metricBindings"]
                if isinstance(item.get("role"), str) and isinstance(item.get("metricKey"), str)
                and (item.get("lagDays") is None or type(item["lagDays"]) is int)}
    if len(spec["metricBindings"]) != 2 or bindings != {
        ("exposure", "workout_session_count", lag), ("outcome", "calories", None)
    }:
        raise ValueError("Unsupported exercise metric bindings")
    if (len(evidence) != 2 or {row["cohort_role"] for row in evidence} != {"exposure", "comparator"}
            or receipt["effect_unit"] != "kcal" or receipt["primary_metric_key"] != "calories"
            or not DIGEST.fullmatch(receipt["input_manifest_hash"] or "")):
        raise ValueError("Missing exercise cohorts")
    for row in evidence:
        meta = row["technical_receipt"]["payload"]
        if (meta.get("profile") != "tyr.exercise_recorded_calories.evidence.v1"
                or meta.get("calendar") != zone or meta.get("lagDays") != lag
                or meta.get("sensitivityIsConfidenceInterval") is not False
                or row["metric_key"] != "calories" or row["canonical_unit"] != "kcal"
                or row["source_fingerprint"] != receipt["input_manifest_hash"]
                or not isinstance(meta.get("pairsByOutcomeDate"), list)
                or not isinstance(meta.get("alternatePairsByOutcomeDate"), list)
                or not isinstance(meta.get("excludedExposureDates"), dict)):
            raise ValueError("Exercise cohort is inconsistent with its evaluation")


SELECT_EVALUATION = """SELECT e.id, e.uuid, h.uuid, e.algorithm_id, e.algorithm_version,
    e.evidence_decision, e.result_claim_type, e.executed_at, e.test_window_start, e.test_window_end,
    e.primary_metric_key, e.effect_estimate, e.effect_unit, e.interval_lower, e.interval_upper,
    e.interval_method, e.specification_json, e.spec_hash, e.input_manifest_hash, e.reproducibility_level,
    e.supersedes_evaluation_uuid
    FROM main.brain_evaluation e JOIN main.brain_hypothesis h ON h.id=e.hypothesis_id
    WHERE e.uuid=? LIMIT 2"""
EVALUATION_KEYS = (
    "local_id", "evaluation_uuid", "hypothesis_uuid", "algorithm_id", "algorithm_version",
    "decision", "claim_type", "executed_at", "window_start", "window_end", "primary_metric_key",
    "effect_estimate", "effect_unit", "interval_lower", "interval_upper", "interval_method",
    "raw_specification", "spec_hash", "input_manifest_hash", "reproducibility", "supersedes_evaluation_uuid",
)
EVIDENCE_KEYS = (
    "uuid", "metric_key", "metric_role", "cohort_role", "source_type", "window_start",
    "window_end", "sample_count", "expected_count", "mean", "coverage_ratio",
    "canonical_unit", "source_fingerprint", "extra_json",
)
TABLES = ("brain_evaluation", "brain_hypothesis", "brain_evaluation_evidence")
UNITS = {
    "total_sleep_minutes": "minutes", "sleep_debt_minutes_7_day": "minutes",
    "bedtime_minute": "minute_of_day", "wake_minute": "minute_of_day",
    "sleep_midpoint_minute": "minute_of_day", "workout_session_count": "count",
    "workout_minutes": "minutes", "cardio_minutes": "minutes", "strength_volume_load": "kg_reps",
    "strength_working_sets": "sets", "strength_failure_sets": "sets", "calories": "kcal",
    "protein_grams": "grams", "carbs_grams": "grams", "fat_grams": "grams",
    "total_steps": "steps", "body_weight": "kg", "resting_hr": "bpm",
    "average_hr": "bpm", "hrv_morning": "ms",
}


def read_receipt(db, uuid, native_version):
    """Copy technical evidence for a named evaluation, with no SQL writes."""
    names = {name for schema, name, kind, *_ in db.execute("PRAGMA table_list")
             if schema == "main" and kind == "table"}
    if not set(TABLES) <= names:
        raise ValueError("Missing native Brain tables")
    rows = db.execute(SELECT_EVALUATION, (uuid,)).fetchall()
    if len(rows) != 1:
        raise ValueError("Expected one native evaluation UUID")
    item = dict(zip(EVALUATION_KEYS, rows[0], strict=True))
    native_id = item.pop("local_id")
    raw = item["raw_specification"]
    spec = envelope(raw)
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != item["spec_hash"]:
        raise ValueError("Native Brain specification digest mismatch")
    if (item["algorithm_id"], item["algorithm_version"]) not in ALGORITHMS:
        raise ValueError("Unsupported native evaluation algorithm")
    frozen = spec["payload"].get("hypothesis")
    if not isinstance(frozen, dict) or frozen.get("uuid") != item["hypothesis_uuid"]:
        raise ValueError("Frozen hypothesis does not match its native evaluation")
    units = dict(UNITS)
    if native_version == 93:
        units["caffeine_mg"] = "mg"
    if item["primary_metric_key"] not in units:
        raise ValueError("Unsupported canonical metric")
    for field in ("effect_estimate", "interval_lower", "interval_upper"):
        value = item[field]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("Invalid estimate")
    projected = ", ".join(EVIDENCE_KEYS)
    rows = db.execute(f"""SELECT {projected} FROM main.brain_evaluation_evidence
        WHERE evaluation_id=? ORDER BY id LIMIT 101""", (native_id,)).fetchall()
    if len(rows) > 100:
        raise ValueError("Native evaluation exceeds the portable evidence limit")
    evidence = []
    for values in rows:
        row = dict(zip(EVIDENCE_KEYS, values, strict=True))
        if row["metric_key"] not in units or row["canonical_unit"] != units[row["metric_key"]]:
            raise ValueError("Invalid canonical evidence unit")
        raw_evidence = row.pop("extra_json")
        row["technical_receipt"] = envelope(raw_evidence) if raw_evidence is not None else None
        evidence.append(row)
    if item["algorithm_id"] == "tyr.exercise_recorded_calories":
        if any(not r["technical_receipt"] for r in evidence):
            raise ValueError("Missing exercise technical receipt")
        match_scope(spec["payload"], evidence, item)
    return {**item, "specification": spec, "evidence": evidence}
