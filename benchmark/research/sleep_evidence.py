"""Observed-data sleep summaries and a bounded three-window reassessment tool."""

from contextlib import contextmanager
from copy import copy
from datetime import timedelta
from statistics import fmean

import evidence_method
import protocol
from observations import InvalidResult
from tyr_brain_lab import analysis
from tyr_brain_lab.source import open_source
from weight_evidence import VERIFY_MARGIN_KG, required_weight_output, verify_weight_step, weight_evidence

PACKET_VERSION = "observation-packet-v3"
SUMMARY_VERSION = "paired-sleep-summary-v1"
STABILITY_PACKET_VERSION = "observation-packet-v13"
SLEEP_ONLY_PACKET_VERSION = "sleep-only-observation-v1"
STABILITY_SUMMARY_VERSION = "paired-sleep-summary-v6"
STABILITY_METHOD = "matched-thirds-v2"
ENDPOINT_METHOD = "whole-window-matched-v1"
THRESHOLD_METHOD = "clustered-threshold-v1"
TOOL_VERSION = "sleep-reassessment-tool-v1"
GROUNDED_TOOL_VERSION = "sleep-reassessment-tool-v2"
ACROSS_WINDOW_METHOD = "across-window-matched-v1"
COMPARABILITY_METHOD = "cross-window-support-v1"
ROUTING_METHOD = "mixed-tool-routing-v3"
PRECEDENCE_METHOD = "shared-strata-precedence-v1"
TOOL_NAME = "reassess_sleep"
TOOL_TARGET = "sleep_reassessment"
MAX_TOOL_BYTES = 4096
MIN_RAW_PER_ARM = 10
MIN_MATCHED_PER_ARM = 6
MIN_SPREAD_MINUTES = 12
THRESHOLD_MARGIN_MINUTES = 3


def _number(value):
    return None if value is None else round(value, 6)


def _sample(pairs):
    earlier, later = ([p["value"] for p in pairs if p["late"] == arm] for arm in (0, 1))
    early_mean = fmean(earlier) if earlier else None
    late_mean = fmean(later) if later else None
    return {
        "earlier_count": len(earlier), "later_count": len(later),
        "earlier_mean_minutes": _number(early_mean), "later_mean_minutes": _number(late_mean),
        "late_minus_earlier_minutes": _number(late_mean - early_mean) if earlier and later else None,
    }


def _matched(groups, weights, minimum):
    earlier, later = (sum(len(groups[key][arm]) for key in weights) for arm in (0, 1))
    return {"earlier_count": earlier, "later_count": later,
            "late_minus_earlier_minutes": _number(evidence_method.effect(groups, weights))
            if min(earlier, later) >= minimum else None}


def _shared_weights(groups, minimum):
    # Apply identical weights where every period has both timing arms.
    shared = set.intersection(*(set(period) for period in groups))
    overlaps = {key: min(len(arm) for period in groups for arm in period[key]) for key in sorted(shared)}
    return {key: count for key, count in overlaps.items() if count >= minimum}


def _windows(source, task):
    for window in task["relationship"]:
        start, end = (protocol.civil(window[key]) for key in ("start", "end"))
        pairs, _ = analysis._paired_sleep(source, start, end, protocol.LATE_DOSE_MINUTE)
        yield window["id"], start, end, pairs


def summaries(source, task, *, stability=False):
    windows = {}
    groups = {}
    for target, start, end, pairs in _windows(source, task):
        days = (end - start).days
        sample = _sample(pairs)
        strata = analysis._strata(pairs)
        weights = evidence_method.mix(strata)
        matched = _matched(strata, weights, minimum=10)
        limits = []
        if len(pairs) < 30 or len(pairs) * 2 < days or min(sample["earlier_count"], sample["later_count"]) < 10:
            limits.append("paired_coverage")
        if matched["late_minus_earlier_minutes"] is None or (matched["earlier_count"] + matched["later_count"]) * 2 < len(pairs):
            limits.append("common_support")
        window = {
            "start": start.isoformat(), "end_exclusive": end.isoformat(), "expected_days": days,
            "paired_days": len(pairs), "date_coverage": _number(len(pairs) / days),
            **sample,
        }
        if stability:
            groups[target] = strata
            window["endpoint_support"] = {
                "coverage_check": "fail" if limits else "pass",
                "limits": limits,
                "matched": matched,
                "leave_one_14_day_block_range_minutes": None if limits else _block_range(pairs, start, weights),
            }
            window["stability_screen"] = _stability(limits, start, end, pairs)
        else:
            window.update(matched=matched, support_limits=limits)
        windows[target] = window
    summary = {"version": STABILITY_SUMMARY_VERSION if stability else SUMMARY_VERSION, "windows": windows}
    if stability:
        summary.update(endpoint_method=ENDPOINT_METHOD, stability_method=STABILITY_METHOD,
                       threshold_method=THRESHOLD_METHOD, threshold_margin_minutes=THRESHOLD_MARGIN_MINUTES,
                       clustered_threshold_windows=_threshold_cluster(windows),
                       cross_window_comparability=_comparability(windows, groups))
    return summary


def _block_range(pairs, start, weights):
    if not weights:
        return None
    retained = [pair for pair in pairs if pair["stratum"] in weights]

    def estimate(rows):
        groups = analysis._strata(rows)
        available = {key: weight for key, weight in weights.items() if key in groups and all(groups[key])}
        if sum(available.values()) * 4 < sum(weights.values()) * 3:
            return None
        return evidence_method.effect(groups, available)

    return analysis._sensitivity(retained, start, estimate)


def _thirds(start, end, pairs):
    days = (end - start).days
    cuts = [(start + timedelta(days=(days * i) // 3)).isoformat() for i in range(4)]
    edges = list(zip(cuts[:-1], cuts[1:], strict=True))
    periods = [[pair for pair in pairs if left <= pair["day"] < right] for left, right in edges]
    strata = [analysis._strata(period) for period in periods]
    weights = _shared_weights(strata, minimum=2)
    bands = []
    for (left, right), period, groups in zip(edges, periods, strata, strict=True):
        sample = _sample(period)
        bands.append({"start": left, "end_exclusive": right,
                      "earlier_count": sample["earlier_count"], "later_count": sample["later_count"],
                      "late_minus_earlier_minutes": sample["late_minus_earlier_minutes"],
                      "matched": _matched(groups, weights, minimum=MIN_MATCHED_PER_ARM)})
    return bands


def _stability(limits, start, end, pairs):
    if limits:
        return {"availability": "unavailable", "reason": "whole_window_coverage", "result": None}
    bands = _thirds(start, end, pairs)
    raw = [band["late_minus_earlier_minutes"] for band in bands]
    matched = [band["matched"]["late_minus_earlier_minutes"] for band in bands]
    if any(min(band["earlier_count"], band["later_count"]) < MIN_RAW_PER_ARM for band in bands):
        return {"availability": "unavailable", "reason": "third_pair_count", "result": None}
    if any(value is None for value in raw + matched):
        return {"availability": "unavailable", "reason": "third_matched_overlap", "result": None}
    threshold = -protocol.MIN_SLEEP_REDUCTION_MINUTES
    mixed = all(min(effects) <= threshold - THRESHOLD_MARGIN_MINUTES
                and max(effects) >= threshold + THRESHOLD_MARGIN_MINUTES
                and max(effects) - min(effects) >= MIN_SPREAD_MINUTES
                for effects in (raw, matched))
    return {"availability": "available", "result": "mixed" if mixed else "no_mixing_detected",
            "raw_thirds_minutes": raw, "matched_thirds_minutes": matched}


def _threshold_cluster(windows):
    eligible = {target: window["endpoint_support"]["matched"]["late_minus_earlier_minutes"]
                for target, window in windows.items()
                if window["endpoint_support"]["coverage_check"] == "pass"
                and window["stability_screen"]["result"] != "mixed"}
    threshold = -protocol.MIN_SLEEP_REDUCTION_MINUTES
    return (sorted(eligible) if len(eligible) >= 2
            and all(abs(effect - threshold) <= THRESHOLD_MARGIN_MINUTES for effect in eligible.values()) else [])


def _comparability(windows, groups):
    common = _shared_weights(list(groups.values()), minimum=3)
    result = {}
    for target, window in windows.items():
        strata = groups[target]
        matched = window["endpoint_support"]["matched"]
        local_count = matched["earlier_count"] + matched["later_count"]
        counts = [sum(len(strata[key][arm]) for key in common) for arm in (0, 1)]
        shared_count = sum(counts)
        removed = local_count - shared_count
        enough = min(counts) >= 10 and 2 * shared_count >= window["paired_days"]
        result[target] = {
            "local_matched_pairs": local_count,
            "shared_earlier_pairs": counts[0],
            "shared_later_pairs": counts[1],
            "removed_local_strata": sorted(key for key in evidence_method.mix(strata) if key not in common),
            "shared_pair_support": enough,
            "material_support_change": enough and 5 * removed >= local_count,
        }
    return {"method": COMPARABILITY_METHOD, "shared_strata": sorted(common), "windows": result}


def required_abstention(packet, target):
    if packet["version"] not in (STABILITY_PACKET_VERSION, SLEEP_ONLY_PACKET_VERSION):
        return False
    summary = packet["sleep_summary"]
    window = summary["windows"][target]
    return (window["endpoint_support"]["coverage_check"] == "fail"
            or window["stability_screen"]["result"] == "mixed"
            or target in summary["clustered_threshold_windows"])


def sleep_review_windows(packet):
    windows = packet["sleep_summary"]["cross_window_comparability"]["windows"]
    eligible = [key for key in windows if not required_abstention(packet, key) and key in packet["witnesses"]]
    return sorted(key for key in eligible if windows[key]["material_support_change"]) if len(eligible) >= 2 else []


def routing_guidance(packet):
    sleep_review = sleep_review_windows(packet)
    weight = packet["weight_summary"]
    weight_review = weight["decision"] == "change" and abs(weight["effect"]) < (
        protocol.MIN_WEIGHT_CHANGE_KG + VERIFY_MARGIN_KG)
    # The mixed pilot prioritizes exact sleep reassessment when both cues apply.
    recommended = "sleep" if sleep_review else "weight" if weight_review else "skip"
    return {"method": ROUTING_METHOD, "sleep_review_windows": sleep_review,
            "borderline_weight_step": weight_review, "recommended": recommended}


def recommended_tool(packet):
    choice = packet["tool_routing"]["recommended"]
    return {"weight": ("evaluate", "weight"), "sleep": (TOOL_NAME, TOOL_TARGET), "skip": None}[choice]


def requires_sleep_route(packet):
    if packet["version"] != STABILITY_PACKET_VERSION:
        return False
    routing = packet["tool_routing"]
    return bool(routing["sleep_review_windows"] and routing["borderline_weight_step"])


def sleep_decision_basis(packet, target, tool=None, *, arm=None):
    """Determine which observed estimate, if any, can support a decision."""
    if required_abstention(packet, target):
        return {"method": None, "effect": None, "reason": "window_abstention_gate"}
    if target not in packet["witnesses"]:
        return {"method": None, "effect": None, "reason": "missing_witness"}
    window = packet["sleep_summary"]["windows"][target]
    if not (arm == "C" and target in packet["tool_routing"]["sleep_review_windows"] and tool
            and (tool["operation"], tool["target"], tool["version"])
            == (TOOL_NAME, TOOL_TARGET, GROUNDED_TOOL_VERSION)):
        return {"method": ENDPOINT_METHOD,
                "effect": window["endpoint_support"]["matched"]["late_minus_earlier_minutes"],
                "reason": "whole_window_default"}
    calculation = tool["windows"][target]
    comparable = calculation["matched_across_windows"]
    earlier, later = comparable["earlier_count"], comparable["later_count"]
    effect = comparable["late_minus_earlier_minutes"]
    sensitivity = calculation["leave_one_14_day_block_range_minutes"]
    if effect is None or min(earlier, later) < MIN_RAW_PER_ARM or (earlier + later) * 2 < window["paired_days"]:
        return {"method": None, "effect": None, "reason": "inadequate_common_support"}
    if sensitivity is None:
        return {"method": None, "effect": None, "reason": "missing_common_sensitivity"}
    low, high = sensitivity
    cutoff = -protocol.MIN_SLEEP_REDUCTION_MINUTES
    if not (max(effect, high) <= cutoff or min(effect, low) > cutoff):
        return {"method": None, "effect": None, "reason": "common_estimate_threshold_sensitive"}
    return {"method": ACROSS_WINDOW_METHOD, "effect": effect, "reason": "common_support_resolved"}


def sleep_estimates(packet, target, tool=None, *, arm=None):
    basis = sleep_decision_basis(packet, target, tool, arm=arm)
    return {basis["method"]: basis["effect"]} if basis["method"] is not None else {}


def ground_sleep(packet, relationship, tool, arm):
    try:
        protocol.fields(relationship, " ".join(protocol.WINDOWS))
        normalized, provenance = {}, {}
        for target, entry in relationship.items():
            protocol.fields(entry, "decision effect evidence confounders estimate_method")
            method = entry["estimate_method"]
            if entry["decision"] == "inconclusive":
                if method is not None or entry["effect"] is not None:
                    raise InvalidResult("ungrounded_sleep")
                provenance[target] = "unavailable"
            else:
                estimates = sleep_estimates(packet, target, tool, arm=arm)
                if not estimates:
                    raise InvalidResult("required_window_abstention")
                if method not in estimates or entry["effect"] != estimates[method]:
                    raise InvalidResult("ungrounded_sleep")
                provenance[target] = method
            normalized[target] = {key: val for key, val in entry.items() if key != "estimate_method"}
    except InvalidResult:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidResult("malformed_prediction") from error
    return normalized, provenance


def reassess(source, task, *, grounded=False):
    windows = list(_windows(source, task))
    groups = [analysis._strata(pairs) for _, _, _, pairs in windows]
    weights = _shared_weights(groups, minimum=3)
    diagnostics = {}
    for (target, start, end, pairs), strata in zip(windows, groups, strict=True):
        matched = _matched(strata, weights, minimum=10)
        diagnostics[target] = {
            "matched_across_windows": matched,
            "leave_one_14_day_block_range_minutes": _block_range(pairs, start, weights)
            if matched["late_minus_earlier_minutes"] is not None else None,
            "fixed_thirds": _thirds(start, end, pairs),
        }
    output = {"operation": TOOL_NAME, "target": TOOL_TARGET,
              "version": GROUNDED_TOOL_VERSION if grounded else TOOL_VERSION,
              "windows": diagnostics}
    if grounded:
        output["estimate_method"] = ACROSS_WINDOW_METHOD
    if len(protocol.canonical(output).encode("utf-8")) > MAX_TOOL_BYTES:
        raise ValueError("Sleep reassessment result exceeds its approved envelope")
    return output


class ReassessmentObservations:
    """Enrich an already admitted case without reinterpreting its original digest."""

    def __init__(self, accepted, *, stability=False):
        self.accepted = accepted
        self.task, self.database = accepted.task, accepted.database
        with self._source() as source:
            summary = summaries(source, self.task, stability=stability)
            if stability:
                weight, references = weight_evidence(source, self.task)
        version = STABILITY_PACKET_VERSION if stability else PACKET_VERSION
        self.packet = {**accepted.packet, "version": version, "sleep_summary": summary}
        if stability:
            self.packet["weight_summary"] = weight
            witnesses = {key: entry for key, entry in self.packet["witnesses"].items() if key != "weight"}
            if references:
                witnesses["weight"] = {"id": weight["evidence"], "references": references}
            self.packet["witnesses"] = witnesses
            self.packet["tool_routing"] = routing_guidance(self.packet)
            self.accepted = copy(accepted)
            self.accepted.packet = self.packet

    @contextmanager
    def _source(self):
        with open_source(self.database) as source:
            if source.manifest["sha256"] != self.task["source_sha256"]:
                raise ValueError("Public fixture changed before sleep analysis")
            yield source

    def tool(self, name, target):
        grounded = self.packet["version"] == STABILITY_PACKET_VERSION
        if name != TOOL_NAME:
            weight = self.packet.get("weight_summary")
            if name == "evaluate" and target == "weight" and weight is not None:
                coverage = self.accepted.tool("coverage", target)
                refs = self.packet["witnesses"].get("weight", {}).get("references", [])
                finding = {key: weight[key] for key in ("decision", "effect", "split")}
                with self._source() as source:
                    verification = verify_weight_step(source, weight)
                return {**coverage, "operation": name, "method": weight["method"],
                        "weight_verification": verification,
                        "finding": {**finding, "claim_type": "descriptive", "references": refs}}
            if grounded and name == "evaluate":
                raise InvalidResult("invalid_tool")
            return self.accepted.tool(name, target)
        if target != TOOL_TARGET:
            raise InvalidResult("invalid_tool")
        with self._source() as source:
            return reassess(source, self.task, grounded=grounded)

    def validate_model(self, value, tool=None, *, arm=None):
        provenance = {}
        if self.packet["version"] == STABILITY_PACKET_VERSION:
            try:
                protocol.fields(value, "relationship change")
            except ValueError as error:
                raise InvalidResult("malformed_prediction") from error
            relationship, provenance = ground_sleep(self.packet, value["relationship"], tool, arm)
            value = {**value, "relationship": relationship}
        weight = self.packet.get("weight_summary")
        if weight is not None:
            finding = value.get("change") if isinstance(value, dict) else None
            if isinstance(finding, dict):
                required = required_weight_output(self.packet, tool, arm)
                if required is not None and finding != required:
                    raise InvalidResult("weight_verification_conflict")
                keys = ("decision", "effect", "split", "evidence")
                abstention = {"decision": "inconclusive", "effect": None, "split": None, "evidence": None}
                if finding != abstention and finding != {key: weight[key] for key in keys}:
                    raise InvalidResult("ungrounded_weight")
        result = self.accepted.validate_model(value, tool)
        if weight is not None and result["numerical_provenance"]["weight"] == "model_estimate":
            result["numerical_provenance"]["weight"] = "matches_calculation"
        result["numerical_provenance"].update(provenance)
        return result
