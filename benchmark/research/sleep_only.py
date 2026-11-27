"""Frozen sleep-only research contract and in-memory qualification."""

from datetime import timedelta

import protocol
from observations import InvalidResult, Observations
from providers import MockTransport
from responses import MAX_REQUEST_BYTES, _object, _sleep_schema
from sleep_evidence import (
    SLEEP_ONLY_PACKET_VERSION, ground_sleep, reassess, sleep_decision_basis, sleep_review_windows, summaries,
)
from tyr_brain_lab.source import open_source

ROUTING_VERSION = "sleep-only-comparability-route-v1"
REQUEST_VERSION = "sleep-only-request-v1"
COMPARATOR_VERSION = "sleep-threshold-comparator-v1"
PROMPT = """Assess the three assigned windows. Each exposure day is paired to sleep
recorded on the following wake date. Compare positive timed caffeine observations.
Late timing starts at clock minute 900. Report later-minus-earlier sleep minutes.
The effect criterion is a reduction of at least 15 minutes. Use the permitted
estimate and evidence ID exactly for a decisive decision. Use inconclusive, with null
effect, evidence and estimate method, under an abstention gate or inadequate evidence.
Consider observed training, weekend, caffeine dose, coverage and temporal changes.
When earlier and later doses occupy disjoint ranges among the paired observations,
the observations cannot distinguish timing from dose. Assess that window as
inconclusive and flag dose_size. Preserve well-supported decisions in other windows.
Use associative interpretations. Compare consecutive decisive windows chronologically
when considering reassessment. The evaluator derives transitions from the three
window decisions and skips inconclusive windows. Return only the three decisions."""


class SleepOnly:
    """Compile a bounded sleep task and run its one optional host calculation."""

    def __init__(self, directory):
        self.source = Observations(directory, sleep_only=True)
        self.task, self.database = self.source.task, self.source.database
        windows = self.task["relationship"]
        bounds = [(protocol.civil(window["start"]), protocol.civil(window["end"])) for window in windows]
        packet = self.source.packet
        next_day = timedelta(days=1)
        with open_source(self.database) as source:
            if source.manifest["sha256"] != self.task["source_sha256"]:
                raise ValueError("Synthetic source changed before sleep-only compilation")
            summary = summaries(source, self.task, stability=True)
            self.packet = {
                "version": SLEEP_ONLY_PACKET_VERSION,
                "task": {"case_id": self.task["case_id"], "relationship": windows},
                "snapshot_columns": packet["snapshot_columns"],
                "snapshot": [r for r in packet["snapshot"]
                             if any(lo <= protocol.civil(r[1]) < hi for lo, hi in bounds)],
                "sleep_columns": packet["sleep_columns"],
                "sleep": [r for r in packet["sleep"]
                          if any(lo <= protocol.civil(r[1]) - next_day < hi for lo, hi in bounds)],
                "witnesses": packet["witnesses"], "sleep_summary": summary,
            }
            targets = sleep_review_windows(self.packet)
            self.packet["tool_routing"] = {
                "method": ROUTING_VERSION, "sleep_review_windows": targets, "action": "reassess_sleep" if targets else "skip",
            }
            self.receipt = reassess(source, self.task, grounded=True) if targets else None

    def request(self, arm):
        if arm not in ("B", "C"):
            raise ValueError("Expected a sleep research arm")
        receipt = self.receipt if arm == "C" else None
        context = {
            "observation_packet": self.packet,
            "sleep_decision_basis": {
                target: sleep_decision_basis(self.packet, target, receipt, arm=arm) for target in protocol.WINDOWS
            },
        }
        if receipt is not None:
            context["executed_tool"] = receipt
        request = {"version": REQUEST_VERSION, "instructions": PROMPT, "input": context,
                   "response_schema": _object(relationship=_sleep_schema(self.packet, receipt, arm=arm))}
        if len(protocol.canonical(request).encode("ascii")) > MAX_REQUEST_BYTES:
            raise ValueError("Sleep-only request exceeds its approved envelope")
        return request

    def request_mock(self, arm, transport):
        if type(transport) is not MockTransport:
            raise PermissionError("Sleep-only preparation accepts the in-memory mock transport only")
        request = self.request(arm)
        value = transport.send(request)
        try:
            protocol.fields(value, "relationship")
        except ValueError as error:
            raise InvalidResult("malformed_prediction") from error
        receipt = self.receipt if arm == "C" else None
        relationship, provenance = ground_sleep(self.packet, value["relationship"], receipt, arm)
        # The local v0.3 scorer still expects its inactive change field.
        result = self.source.validate_model({
            "relationship": relationship,
            "change": {"decision": "inconclusive", "effect": None, "evidence": None, "split": None},
        })
        result["numerical_provenance"] = provenance
        return result


def deterministic_prediction(request):
    """Apply the v0.3 threshold to the exact eligible basis in the arm's envelope."""
    context = request["input"]
    witnesses = context["observation_packet"]["witnesses"]
    relationship = {}
    for target, basis in context["sleep_decision_basis"].items():
        method, effect = basis["method"], basis["effect"]
        decision = "inconclusive" if method is None else (
            "supported" if effect <= -protocol.MIN_SLEEP_REDUCTION_MINUTES else "notSupported")
        relationship[target] = {
            "decision": decision, "effect": effect, "estimate_method": method,
            "evidence": witnesses[target]["id"] if method is not None else None,
            "confounders": dict.fromkeys(sorted(protocol.CONFOUNDERS), False),
        }
    return {"relationship": relationship}
