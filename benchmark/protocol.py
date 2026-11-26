"""The observation-only task and fixed-target submission contracts."""

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path

VERSION = 1
ID = re.compile(r"[0-9a-f]{32}")
SHA = re.compile(r"[0-9a-f]{64}")
WINDOWS = ("window_1", "window_2", "window_3")
MIN_SLEEP_REDUCTION_MINUTES = 15
MIN_WEIGHT_CHANGE_KG = 1
LATE_DOSE_MINUTE = 900
DECISIONS = {"supported", "notSupported", "inconclusive"}
CLAIMS = {"descriptive", "association", "causal"}
CONFOUNDERS = {"training_day", "weekend", "dose_size", "logging_gaps", "baseline_change"}
REFERENCE_FIELDS = {
    "daily_snapshot": {"body_weight", "caffeine_last_dose_minute", "caffeine_mg", "workout_session_count"},
    "daily_sleep": {"total_minutes"},
}
MAX_SUBMISSION_SIZE = 96_000


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def read_json(path, max_bytes=MAX_SUBMISSION_SIZE):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Expected an ordinary JSON file")
    with path.open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("JSON is larger than the protocol allows")
    return json.loads(data)


def hash_file(path):
    with path.open("rb") as stream:
        digestor = hashlib.sha256()
        for item in iter(lambda: stream.read(1024 * 1024), b""):
            digestor.update(item)
        return digestor.hexdigest()


def fields(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError("Unexpected protocol fields")


def civil(value):
    if type(value) is not str:
        raise ValueError("Expected a civil date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Expected a YYYY-MM-DD civil date")
    return parsed


def validate_task(task):
    fields(task, "version case_id source_sha256 relationship change")
    if (type(task["version"]) is not int or task["version"] != VERSION
            or not isinstance(task["case_id"], str) or not ID.fullmatch(task["case_id"])
            or not isinstance(task["source_sha256"], str) or not SHA.fullmatch(task["source_sha256"])):
        raise ValueError("Unsupported task version or identity")
    if not isinstance(task["relationship"], list) or len(task["relationship"]) != len(WINDOWS):
        raise ValueError("Expected exactly three relationship windows")
    previous_end = None
    for key, window in zip(WINDOWS, task["relationship"], strict=True):
        fields(window, "id start end")
        start, end = civil(window["start"]), civil(window["end"])
        if window["id"] != key or (not start < end) or (previous_end and start < previous_end):
            raise ValueError("Unexpected relationship window")
        previous_end = end
    fields(task["change"], "start end")
    start, end = civil(task["change"]["start"]), civil(task["change"]["end"])
    if not 28 <= (end - start).days <= 365:
        raise ValueError("Unexpected baseline-change window")
    if civil(task["relationship"][0]["start"]) < start or previous_end > end:
        raise ValueError("Relationship windows must fit within the benchmark calendar")
    return task


def read_packet(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Expected a standalone agent packet")
    if {entry.name for entry in path.iterdir()} != {"records.sqlite", "task.json"}:
        raise ValueError("Agent packet must contain only records.sqlite and task.json")
    task = validate_task(read_json(path / "task.json"))
    database = path / "records.sqlite"
    if (task["case_id"] != path.name or database.is_symlink() or not database.is_file()
            or task["source_sha256"] != hash_file(database)):
        raise ValueError("Observation packet identity or fingerprint mismatch")
    return task, database


def _evidence(value):
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("Evidence must contain at most twelve references")
    seen = set()
    for ref in value:
        fields(ref, "table row_id column")
        table, row_id, column = ref["table"], ref["row_id"], ref["column"]
        if (type(table) is not str or type(column) is not str or column not in REFERENCE_FIELDS.get(table, ())
                or type(row_id) is not int or not 1 <= row_id < 2**63
                or (table, row_id, column) in seen):
            raise ValueError("Invalid or duplicate evidence reference")
        seen.add((table, row_id, column))


def _effect(value):
    if value is not None and (type(value) not in (int, float) or not -10_000 <= value <= 10_000
                              or not math.isfinite(value)):
        raise ValueError("Invalid effect")


def validate_predictions(value, task):
    fields(value, "version case_id relationship change")
    if type(value["version"]) is not int or value["version"] != VERSION or value["case_id"] != task["case_id"]:
        raise ValueError("Prediction must match the task")
    if type(value["relationship"]) is not dict or set(value["relationship"]) != set(WINDOWS):
        raise ValueError("Exactly one decision per fixed relationship window is required")
    for entry in value["relationship"].values():
        fields(entry, "decision claim_type effect references confounders")
        if (type(entry["decision"]) is not str or entry["decision"] not in DECISIONS
                or type(entry["claim_type"]) is not str or entry["claim_type"] not in CLAIMS):
            raise ValueError("Unexpected decision or claim type")
        _effect(entry["effect"])
        if entry["decision"] != "inconclusive" and entry["effect"] is None:
            raise ValueError("A decisive prediction must include an effect")
        _evidence(entry["references"])
        confounders = entry["confounders"]
        if (not isinstance(confounders, list) or any(type(item) is not str or item not in CONFOUNDERS for item in confounders)
                or len(confounders) != len(set(confounders))):
            raise ValueError("Unknown or repeated confounder")
    change = value["change"]
    fields(change, "decision split effect references claim_type")
    if (type(change["decision"]) is not str or change["decision"] not in {"change", "no_change", "inconclusive"}
            or type(change["claim_type"]) is not str or change["claim_type"] not in CLAIMS):
        raise ValueError("Invalid change decision")
    _effect(change["effect"])
    if change["decision"] == "change":
        split = civil(change["split"])
        if not civil(task["change"]["start"]) < split < civil(task["change"]["end"]) or change["effect"] is None:
            raise ValueError("A detected change needs a split and an effect within the task window")
    elif change["split"] is not None:
        raise ValueError("A split is only valid with a change decision")
    _evidence(change["references"])
    return value
