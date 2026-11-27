"""Mock-only sleep contract with host-validated within-period estimates."""

from collections import defaultdict
from copy import copy
from statistics import fmean

import protocol
from observations import InvalidResult
from providers import MockTransport
from responses import MAX_REQUEST_BYTES, _enum, _number, _object, _variants
from sleep_evidence import ACROSS_WINDOW_METHOD, sleep_decision_basis
from sleep_only import SleepOnly
from tyr_brain_lab import analysis
from tyr_brain_lab.source import open_source

PACKET_VERSION = "sleep-only-observation-v2"
REQUEST_VERSION = "sleep-only-request-v2"
ESTIMATE_METHOD = "within-period-dose-matched-v1"
PERIOD_DAYS = 28
MIN_PAIRS_PER_PERIOD = 4
MIN_SUPPORTED_PERIODS = 2
CUTOFF = -protocol.MIN_SLEEP_REDUCTION_MINUTES


def within_period_support(pairs, start, shared_strata):
    """Compute a weighted contrast from matching dose and context within each period."""
    cells = defaultdict(lambda: ([], []))
    for pair in pairs:
        stratum = pair["stratum"]
        if shared_strata is None or stratum in shared_strata:
            period = (protocol.civil(pair["day"]) - start).days // PERIOD_DAYS
            cells[period, stratum, pair["dose_mg"]][pair["late"]].append(pair)
    by_period = defaultdict(list)
    for (period, _, _), (earlier, later) in sorted(cells.items()):
        count = min(len(earlier), len(later))
        if count:
            diff = fmean(row["value"] for row in later) - fmean(row["value"] for row in earlier)
            by_period[period].append((count, diff, earlier[0], later[0]))
    periods, supported = [], []
    for period in sorted(by_period):
        matches = by_period[period]
        n = sum(row[0] for row in matches)
        effect = sum(count * diff for count, diff, _, _ in matches) / n
        periods.append({"period": period, "matched_pairs_per_arm": n, "effect_minutes": round(effect, 6)})
        if n >= MIN_PAIRS_PER_PERIOD:
            supported.append((n, effect, matches[0][2:]))
    if len(supported) < MIN_SUPPORTED_PERIODS:
        return periods, None, [], "insufficient_period_support"
    if len({effect <= CUTOFF for _, effect, _ in supported}) != 1:
        return periods, None, [], "period_estimates_disagree"
    effect = round(sum(n * e for n, e, _ in supported) / sum(n for n, _, _ in supported), 6)
    # Retain a matched example from the first and last supported periods.
    references = [
        {"table": ref["table"], "row_id": ref["row_id"], "column": col}
        for _, _, example in (supported[0], supported[-1])
        for pair in example
        for ref, col in zip(pair["references"], ("caffeine_last_dose_minute", "total_minutes"), strict=True)
    ]
    return periods, effect, references, "period_support_resolved"


def local_schema(basis, witnesses):
    null = {"type": "null"}
    flags = _object(**{key: {"type": "boolean"} for key in sorted(protocol.CONFOUNDERS)})
    windows = {}
    for target, selected in basis.items():
        variants = [_object(decision=_enum("inconclusive"), effect=null, estimate_method=null,
                            evidence=null, confounders=flags)]
        effect = selected["effect"]
        if effect is not None:
            variants.append(_object(
                decision=_enum("supported" if effect <= CUTOFF else "notSupported"),
                effect=_number(minimum=effect, maximum=effect),
                estimate_method=_enum(ESTIMATE_METHOD), evidence=_enum(witnesses[target]["id"]), confounders=flags,
            ))
        windows[target] = _variants(variants)
    return _object(relationship=_object(**windows))


class WithinPeriodSleep(SleepOnly):
    """Freeze one local evidence basis for C, independent of model output."""

    def __init__(self, directory):
        super().__init__(directory)
        self.basis, self.support, self.local_witnesses = {}, {}, {}
        common = self.packet["sleep_summary"]["cross_window_comparability"]["shared_strata"]
        with open_source(self.database) as source:
            if source.manifest["sha256"] != self.task["source_sha256"]:
                raise ValueError("Synthetic source changed before within-period analysis")
            for window in self.task["relationship"]:
                target = window["id"]
                inherited = sleep_decision_basis(self.packet, target, self.receipt, arm="C")
                effect, periods, refs = None, [], []
                reason = inherited["reason"]
                if inherited["method"] is not None:
                    start, end = (protocol.civil(window[key]) for key in ("start", "end"))
                    pairs, _ = analysis._paired_sleep(source, start, end, protocol.LATE_DOSE_MINUTE)
                    strata = set(common) if inherited["method"] == ACROSS_WINDOW_METHOD else None
                    periods, effect, refs, reason = within_period_support(pairs, start, strata)
                self.support[target] = {"periods": periods, "inherited_basis": inherited, "result": reason}
                self.basis[target] = {"method": ESTIMATE_METHOD if effect is not None else None,
                                      "effect": effect, "reason": reason}
                if effect is not None:
                    self.local_witnesses[target] = {"id": f"{target}-within-period-{self.task['case_id']}",
                                                    "references": refs}

    def request(self, arm):
        request = super().request(arm)
        request["version"] = REQUEST_VERSION
        context = request["input"]
        packet = {**context["observation_packet"], "version": PACKET_VERSION}
        context["observation_packet"] = packet
        if arm == "C":
            packet["witnesses"] = self.local_witnesses
            context.update(sleep_decision_basis=self.basis, within_period_support=self.support)
            request["response_schema"] = local_schema(self.basis, self.local_witnesses)
            request["instructions"] += (
                "\nC's permitted estimate is a dose-matched contrast within fixed 28-day periods. "
                "Assess the recorded context and coverage before treating it as interpretable for the window. "
                "Report inconclusive if support is inadequate. Copy the permitted method, number and evidence ID "
                "for any decisive result."
            )
        if len(protocol.canonical(request).encode("ascii")) > MAX_REQUEST_BYTES:
            raise ValueError("Within-period request exceeds its approved envelope")
        return request

    def request_mock(self, arm, transport):
        if arm == "B":
            return super().request_mock(arm, transport)
        if type(transport) is not MockTransport:
            raise PermissionError("Within-period preparation accepts the in-memory mock transport only")
        value = transport.send(self.request(arm))
        try:
            protocol.fields(value, "relationship")
            protocol.fields(value["relationship"], " ".join(protocol.WINDOWS))
            relationships, provenance = {}, {}
            for target, row in value["relationship"].items():
                protocol.fields(row, "decision effect estimate_method evidence confounders")
                expected = self.basis[target]
                if row["decision"] == "inconclusive":
                    if row["effect"] is not None or row["estimate_method"] is not None:
                        raise InvalidResult("ungrounded_sleep")
                    provenance[target] = "unavailable"
                else:
                    if expected["method"] is None:
                        raise InvalidResult("required_window_abstention")
                    if row["effect"] != expected["effect"] or row["estimate_method"] != expected["method"]:
                        raise InvalidResult("ungrounded_sleep")
                    provenance[target] = ESTIMATE_METHOD
                relationships[target] = {key: item for key, item in row.items() if key != "estimate_method"}
        except InvalidResult:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidResult("malformed_prediction") from error
        validator = copy(self.source)
        validator.packet = {**validator.packet, "witnesses": self.local_witnesses}
        result = validator.validate_model({
            "relationship": relationships,
            "change": {"decision": "inconclusive", "effect": None, "evidence": None, "split": None},
        })
        result["numerical_provenance"] = provenance
        return result
