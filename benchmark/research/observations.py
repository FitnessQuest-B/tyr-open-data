"""Canonical public synthetic inputs, case-scoped tools and evidence validation."""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager

import protocol
import prepare
import evidence_method
from tyr_brain_lab import analysis
from tyr_brain_lab.source import open_source

VERSION = "observation-packet-v2"
TOOL_VERSION = "research-tools-v1"
PUBLIC_SEED = "040a" * 16
SNAPSHOT = ("id", "day", "caffeine_last_dose_minute", "caffeine_mg", "workout_session_count", "body_weight")
SLEEP = ("id", "day", "total_minutes", "sleep_start_minute", "sleep_end_minute")
TARGETS = (*protocol.WINDOWS, "weight")
TOOLS = {
    "coverage": "Count eligible paired sleep days or weight days for one assigned target.",
    "evaluate": "Run the v0.3.0 evidence-aware method for one assigned target.",
}


class InvalidResult(ValueError):
    def __init__(self, classification):
        super().__init__(classification)
        self.classification = classification


@contextmanager
def public_panel():
    # Both roots are fresh. Only the observation paths leave this staging function.
    with TemporaryDirectory(prefix="tyr-research-public-") as scratch:
        root = Path(scratch)
        agent = root / "observations"
        index = prepare.prepare(agent, root / "evaluator", master_seed=PUBLIC_SEED)
        yield tuple(agent / identity for identity in index["cases"])


def _table(source, table, columns, start, end):
    output = []
    for day, row in sorted(analysis._indexed(source, table).items()):
        if not start <= day < end or row.get("deleted_at") is not None:
            continue
        if table == "daily_sleep" and row["source"] in {"fake", "devSeed"}:
            continue
        output.append([row["id"], day.isoformat(), *(row[key] for key in columns[2:])])
    return output


def _witnesses(source, task, start, end, *, include_weight=True):
    witnesses = {}
    for window in task["relationship"]:
        left, right = (protocol.civil(window[key]) for key in ("start", "end"))
        pairs, _ = analysis._paired_sleep(source, left, right, protocol.LATE_DOSE_MINUTE)
        earlier, later = (next((p for p in pairs if p["late"] == arm), None) for arm in (0, 1))
        if earlier is not None and later is not None:
            target = window["id"]
            witnesses[target] = {
                "id": f"{target}-{task['case_id']}",
                "references": [
                    {"table": ref["table"], "row_id": ref["row_id"], "column": column}
                    for pair in (earlier, later)
                    for ref, column in zip(pair["references"], ("caffeine_last_dose_minute", "total_minutes"),
                                           strict=True)
                ],
            }
    points = analysis._points(source, "body_weight", start, end) if include_weight else []
    if len(points) >= 2:
        first, last = points[0], points[-1]
        witnesses["weight"] = {
            "id": f"weight-{task['case_id']}",
            "references": [{key: point["references"][0][key] for key in ("table", "row_id", "column")}
                           for point in (first, last)],
            "first_split": (protocol.civil(first["day"]) + timedelta(days=1)).isoformat(),
            "last_split": last["day"],
        }
    return witnesses


class Observations:
    """Constructed exclusively by the trusted controller from the regenerated panel."""

    def __init__(self, packet, *, sleep_only=False):
        self.task, self.database = protocol.read_packet(packet)
        start, end = (protocol.civil(self.task["change"][key]) for key in ("start", "end"))
        snapshot_columns = SNAPSHOT[:-1] if sleep_only else SNAPSHOT
        with open_source(self.database) as source:
            if (source.manifest["profile"] != "open_data_projection" or source.owner != 1
                    or source.manifest["sha256"] != self.task["source_sha256"]
                    or source.manifest["foreign_key_violations"] != 0):
                raise ValueError("Public fixture projection failed validation")
            snapshots = _table(source, "daily_snapshot", snapshot_columns, start, end)
            next_day = timedelta(days=1)
            sleep = _table(source, "daily_sleep", SLEEP, start + next_day, end + next_day)
            witnesses = _witnesses(source, self.task, start, end, include_weight=not sleep_only)
        # Use explicit positional fields to keep full daily data within the request cap.
        self.packet = {
            "version": VERSION,
            "task": {key: self.task[key] for key in ("version", "case_id", "relationship", "change")},
            "snapshot_columns": snapshot_columns, "snapshot": snapshots,
            "sleep_columns": SLEEP, "sleep": sleep,
            "witnesses": witnesses,
        }
        self.rows = {
            "daily_snapshot": {row[0]: dict(zip(snapshot_columns, row, strict=True)) for row in snapshots},
            "daily_sleep": {row[0]: dict(zip(SLEEP, row, strict=True)) for row in sleep},
        }

    def window(self, target):
        if target == "weight":
            return self.task["change"]
        return next(window for window in self.task["relationship"] if window["id"] == target)

    def tool(self, name, target):
        if name not in TOOLS or target not in TARGETS:
            raise InvalidResult("invalid_tool")
        window = self.window(target)
        start, end = (protocol.civil(window[key]) for key in ("start", "end"))
        weight = target == "weight"
        with open_source(self.database) as source:
            if source.manifest["sha256"] != self.task["source_sha256"]:
                raise ValueError("Public fixture changed before tool execution")
            if weight:
                points = analysis._points(source, "body_weight", start, end)
                counts = {"observed_days": len(points)}
            else:
                pairs, excluded = analysis._paired_sleep(source, start, end, protocol.LATE_DOSE_MINUTE)
                counts = {"paired_days": len(pairs), "late_days": sum(p["late"] for p in pairs),
                          "excluded": dict(excluded)}
            result = {
                "operation": name, "target": target, "version": TOOL_VERSION,
                "method": ("v0.3.0-evidence-aware" if name == "evaluate" else "v0.3.0-eligible-days"),
                "measurements": (["body_weight"] if weight else [
                    "caffeine_mg", "caffeine_last_dose_minute", "workout_session_count", "total_sleep_minutes"]),
                "start": window["start"], "end_exclusive": window["end"],
                "expected_days": (end - start).days, "unit": "kg" if weight else "min", **counts,
            }
            if name == "evaluate":
                all_findings = evidence_method.predict(self.task, source)
                finding = all_findings["change"] if weight else all_findings["relationship"][target]
                protocol.validate_predictions(all_findings, self.task)
                self._references(finding, target)
                result["finding"] = finding
        if len(protocol.canonical(result)) > 4096:
            raise ValueError("Tool result exceeds its approved envelope")
        return result

    def _references(self, finding, target):
        weight = target == "weight"
        window = self.window(target)
        start, end = (protocol.civil(window[key]) for key in ("start", "end"))
        doses, sleep, weights = {}, set(), set()
        for ref in finding["references"]:
            table, column = ref["table"], ref["column"]
            row = self.rows[table].get(ref["row_id"])
            if row is None or row[column] is None:
                raise InvalidResult("invalid_evidence")
            day = protocol.civil(row["day"])
            if table == "daily_sleep":
                day -= timedelta(days=1)  # Compare wake minus one day to the exposure window.
            if not start <= day < end or weight != (column == "body_weight"):
                raise InvalidResult("invalid_evidence")
            if weight:
                if row[column] <= 0:
                    raise InvalidResult("invalid_evidence")
                weights.add(day)
            elif table == "daily_sleep":
                if row[column] < 0:
                    raise InvalidResult("invalid_evidence")
                sleep.add(day)
            elif column == "caffeine_last_dose_minute":
                if not 180 <= row[column] <= 1439 or not (row["caffeine_mg"] or 0) > 0:
                    raise InvalidResult("invalid_evidence")
                doses[day] = row[column] >= protocol.LATE_DOSE_MINUTE
        if finding["decision"] == "inconclusive":
            return
        if not weight:
            valid = {doses[day] for day in sleep & doses.keys()} == {False, True}
        elif finding["split"]:
            cut = protocol.civil(finding["split"])
            valid = {day < cut for day in weights} == {False, True}
        else:
            valid = len(weights) >= 2
        if not valid:
            raise InvalidResult("invalid_evidence")

    def validate(self, prediction, tool=None):
        try:
            protocol.validate_predictions(prediction, self.task)
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidResult("malformed_prediction") from error
        findings = {**prediction["relationship"], "weight": prediction["change"]}
        numerical = {}
        for target, finding in findings.items():
            if finding["claim_type"] == "causal":
                raise InvalidResult("unsupported_causal")
            self._references(finding, target)
            effect = finding["effect"]
            decision = finding["decision"]
            weight = target == "weight"
            if decision != "inconclusive":
                if weight:
                    agrees = ((effect is not None and abs(effect) >= protocol.MIN_WEIGHT_CHANGE_KG)
                              == (decision == "change"))
                else:
                    agrees = ((effect <= -protocol.MIN_SLEEP_REDUCTION_MINUTES) == (decision == "supported"))
                if not agrees:
                    raise InvalidResult("invalid_effect")
            numerical[target] = "unavailable" if effect is None else "model_estimate"
            if tool and tool["target"] == target and "finding" in tool and effect is not None:
                verified = tool["finding"]
                if verified["effect"] is None:
                    continue
                if (abs(verified["effect"] - effect) > 0.01
                        or (weight and finding["split"] != verified["split"])):
                    raise InvalidResult("tool_number_mismatch")
                numerical[target] = "matches_tool"
        return {"status": "completed", "prediction": prediction, "numerical_provenance": numerical}

    def validate_model(self, value, tool=None):
        """Bind provider output to the current case before the benchmark checks."""
        try:
            protocol.fields(value, "relationship change")
            protocol.fields(value["relationship"], " ".join(protocol.WINDOWS))
            predictions = {"version": protocol.VERSION, "case_id": self.task["case_id"], "relationship": {}}
            for target in protocol.WINDOWS:
                entry = value["relationship"][target]
                protocol.fields(entry, "decision effect evidence confounders")
                confounders = entry["confounders"]
                protocol.fields(confounders, " ".join(sorted(protocol.CONFOUNDERS)))
                if any(type(flag) is not bool for flag in confounders.values()):
                    raise ValueError("Confounder flags must be boolean")
                predictions["relationship"][target] = {
                    "decision": entry["decision"], "effect": entry["effect"], "claim_type": "association",
                    "references": self._bind_witness(entry, target),
                    "confounders": sorted(key for key, flag in confounders.items() if flag),
                }
            entry = value["change"]
            protocol.fields(entry, "decision effect evidence split")
            predictions["change"] = {
                "decision": entry["decision"], "effect": entry["effect"], "split": entry["split"],
                "claim_type": "descriptive", "references": self._bind_witness(entry, "weight"),
            }
        except InvalidResult:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidResult("malformed_prediction") from error
        return self.validate(predictions, tool)

    def _bind_witness(self, entry, target):
        if entry["decision"] == "inconclusive":
            if entry["evidence"] is not None:
                raise InvalidResult("invalid_evidence")
            return []
        witness = self.packet["witnesses"].get(target)
        if witness is None or entry["evidence"] != witness["id"]:
            raise InvalidResult("invalid_evidence")
        return witness["references"]
