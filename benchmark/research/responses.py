"""Provider-neutral outcome contract and the optional OpenAI Responses transport."""

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

import protocol
from observations import InvalidResult, TARGETS, TOOLS
from sleep_evidence import (
    PACKET_VERSION as REASSESSMENT_PACKET_VERSION, SLEEP_ONLY_PACKET_VERSION, STABILITY_PACKET_VERSION,
    TOOL_NAME, TOOL_TARGET, required_abstention, sleep_decision_basis, sleep_estimates,
)
from weight_evidence import required_weight_output

VERSION = "openai-responses-research-v2"
PROMPT_VERSION = "fixed-target-prompt-v3"
SELECTION_VERSION = "tyr_tool_selection_v1"
REASSESSMENT_PROMPT_VERSION = "fixed-target-prompt-v4"
STABILITY_PROMPT_VERSION = "fixed-target-prompt-v11"
REASSESSMENT_SELECTION_VERSION = "tyr_tool_selection_v2"
WEIGHT_SELECTION_VERSION = "tyr_tool_selection_v7"
MAX_REQUEST_BYTES = 48_000
MAX_OUTPUT_BYTES = 32_000
SAFE_PROVIDER_ID = re.compile(r"(?:resp|req)_[a-zA-Z0-9_-]{1,100}")
PROMPT = """Evaluate the four assigned observational targets. Use only the supplied case.
The relationship estimand is late minus earlier minutes on the following sleep wake date.
Late starts at nutrition clock minute 900. Compare positive timed doses, use a 15-minute
reduction threshold, and consider recorded training, weekend, dose, gaps and changing
relationships. Dates are civil labels, and window ends are exclusive. Treat missing values
as unknown. Weight uses kg and a 1 kg abrupt-change threshold. Avoid causal conclusions.
Return the four predictions in the supplied JSON schema. Report effects as signed numbers
or null if unavailable. For a decisive result, use that target's evidence ID from witnesses.
Each evidence ID binds existing rows to a target. It does not establish a result or prove an
effect size. Use inconclusive and null evidence when evidence is inadequate. Use a split date
only for a weight change and use null otherwise. Set a confounder flag to true only when
observations support it. If tools are available you may choose one target to investigate.
A tool result covers just its selected target. Use its effect precisely if reporting that
target's tool estimate. A null tool effect gives no estimate. Report a number in that case
only if you can estimate it independently from the observations. Treat it as exploratory."""

SELECTION_PROMPT = """Select at most one investigation for this case. The final task is to
assess later caffeine timing and following-night sleep in three windows and an abrupt
weight change in the assigned weight window. Call coverage or evaluate for one assigned
target if it would help. Otherwise return the skip action. This turn selects an action."""

REASSESSMENT_RULE = """Use sleep_summary to check the observed timing-group counts, coverage,
and signed contrasts in each assigned window. The summaries describe observations and
support limits. They do not assign verdicts. Assess each window, then compare the resulting
decisive windows in chronological order. A reassessment is a change in decision between
consecutive decisive windows. Skip an inconclusive middle window when comparing its two
decisive neighbors. Leave a mixed or undercovered window inconclusive when justified by
the evidence. Fixed thirds and leave-one-block-out ranges are diagnostic; a subset
contrast alone does not establish an endpoint decision."""
STABILITY_RULE = """For each window, start with endpoint_support. Its matched contrast and
leave-one-14-day-block-out range describe the whole window. Mark it inconclusive if the
coverage check fails or if stability_screen.result is mixed.
Availability in stability_screen refers only to
detecting within-window mixing from fixed thirds. An unavailable screen with a passing
coverage check is compatible with a decisive endpoint. Use notSupported for a well-covered
contrast clearly above -15 minutes, even if it is negative, and supported for one clearly
at or below -15. The block-deletion range is a sensitivity check. Consider inconclusive for
an ambiguous whole-window estimate, a threshold-sensitive range, or conflicting evidence.
Use sleep_decision_basis for the permitted estimate and method in each window. A sleep tool
result takes precedence only for a flagged window with adequate common support and a shared
estimate and sensitivity range that agree on the side of -15 minutes. In that window, use the
shared estimate for a decisive finding. If the attempted comparison does not resolve the
flagged window, report inconclusive. In other eligible windows use the whole-window default.
For a decisive sleep finding, copy the permitted estimate and method exactly. Raw differences
describe the sample. They do not support a threshold decision.
For inconclusive sleep, use null effect, evidence, and estimate_method.
Use inconclusive for windows listed in clustered_threshold_windows. Those are cases
with at least two eligible endpoints and all eligible estimates close to the cutoff.
Compare consecutive decisive endpoints chronologically, skipping inconclusive windows.
Use weight_summary for the independent calculation in kg. For a decisive weight result,
use its decision, effect, split, and evidence exactly. A grounded no_change has null
effect and split."""
B_WEIGHT_RULE = """If declining the weight calculation, use inconclusive with null effect,
split and evidence."""
REASSESSMENT_SELECTION_PROMPT = """Select at most one investigation for the assigned case.
Prioritize whether the caffeine–sleep relationship changes across the three assigned
windows. Use reassess_sleep for comparable evidence and within-window stability when
it would help. You may instead call coverage or evaluate for one assigned target,
including weight, or return the skip action. This turn selects an action only."""
WEIGHT_SELECTION_PROMPT = """Select at most one investigation across both domains.
Read tool_routing. Follow its recommendation by default. For sleep, call reassess_sleep:
the listed windows lose substantial matched support when restricted to shared strata.
Within-window stability does not resolve that comparability issue. For weight, call evaluate
with target weight: a borderline nominated step warrants the local verification.
If the recommendation is skip, use the shared evidence unless another investigation is
warranted. This turn selects an action only."""
C_WEIGHT_RULE = """Keep weight_summary's grounded weight decision unless evaluate for
weight returns a weight_verification challenge for its nominated split. A challenge
requires inconclusive with null effect, split and evidence for weight. Sleep tool
results, coverage alone and skipping leave the weight decision in force."""

@dataclass(frozen=True)
class Model:
    identifier: str
    effort: str
    input_limit: int
    output_limit: int
    input_rate: int
    output_rate: int
    price_date: str
    price_url: str

    def cost(self, input_tokens, output_tokens):
        return (input_tokens * self.input_rate + output_tokens * self.output_rate + 999_999) // 1_000_000


# Standard, global, un-discounted short-context pricing. Only this configuration is enabled.
PILOT = Model("gpt-5.4-mini-2026-03-17", "low", 400_000, 2_000, 750_000, 4_500_000,
              "2026-11-26", "https://developers.openai.com/api/docs/pricing")


def _object(**properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _enum(*values):
    return {"type": "string", "enum": list(values)}


def _number(**bounds):
    return {"type": "number", "minimum": -10_000, "maximum": 10_000, **bounds}


def _variants(options):
    return options[0] if len(options) == 1 else {"anyOf": options}


def _sleep_schema(packet, tool=None, *, arm=None):
    null = {"type": "null"}
    nullable_effect = {"anyOf": [_number(), null]}
    witnesses = packet["witnesses"]
    flags = _object(**{key: {"type": "boolean"} for key in sorted(protocol.CONFOUNDERS)})
    sleep = {}
    threshold = -protocol.MIN_SLEEP_REDUCTION_MINUTES
    for target in protocol.WINDOWS:
        if packet["version"] in (STABILITY_PACKET_VERSION, SLEEP_ONLY_PACKET_VERSION):
            variants = [_object(decision=_enum("inconclusive"), effect=null, evidence=null,
                                confounders=flags, estimate_method=null)]
            for method, effect in sleep_estimates(packet, target, tool, arm=arm).items():
                decision = "supported" if effect <= threshold else "notSupported"
                variants.append(_object(decision=_enum(decision), effect=_number(minimum=effect, maximum=effect),
                    evidence=_enum(witnesses[target]["id"]), confounders=flags, estimate_method=_enum(method)))
            sleep[target] = _variants(variants)
            continue
        variants = [_object(decision=_enum("inconclusive"), effect=nullable_effect,
                            evidence=null, confounders=flags)]
        if target in witnesses and not required_abstention(packet, target):
            selected = _enum(witnesses[target]["id"])
            variants.extend([
                _object(decision=_enum("supported"), effect=_number(maximum=threshold),
                        evidence=selected, confounders=flags),
                _object(decision=_enum("notSupported"), effect=_number(exclusiveMinimum=threshold),
                        evidence=selected, confounders=flags),
            ])
        sleep[target] = _variants(variants)

    return _object(**sleep)


def _prediction_schema(packet, tool=None, *, arm=None):
    null = {"type": "null"}
    nullable_effect = {"anyOf": [_number(), null]}
    witnesses = packet["witnesses"]
    required = required_weight_output(packet, tool, arm)
    grounded = required if required is not None else packet.get("weight_summary")
    change = []
    if required is None or required["decision"] == "inconclusive":
        change.append(_object(decision=_enum("inconclusive"), split=null,
                              effect=null if grounded is not None else nullable_effect, evidence=null))
    if grounded is not None:
        if grounded["decision"] != "inconclusive":
            effect, split = (grounded[key] for key in ("effect", "split"))
            change.append(_object(
                decision=_enum(grounded["decision"]),
                split=null if split is None else _enum(split),
                effect=null if effect is None else _number(minimum=effect, maximum=effect),
                evidence=_enum(grounded["evidence"]),
            ))
    elif "weight" in witnesses:
        witness = witnesses["weight"]
        first, last = (protocol.civil(witness[key]) for key in ("first_split", "last_split"))
        splits = [(first + timedelta(days=day)).isoformat() for day in range((last - first).days + 1)]
        minimum = protocol.MIN_WEIGHT_CHANGE_KG
        change.extend([
            _object(decision=_enum("no_change"), split=null, evidence=_enum(witness["id"]),
                    effect={"anyOf": [_number(exclusiveMinimum=-minimum, exclusiveMaximum=minimum), null]}),
            _object(decision=_enum("change"), split=_enum(*splits), evidence=_enum(witness["id"]),
                    effect={"anyOf": [_number(maximum=-minimum), _number(minimum=minimum)]}),
        ])
    return _object(relationship=_sleep_schema(packet, tool, arm=arm), change=_variants(change))


class Responses:
    name = VERSION

    def request(self, packet, *, offer_tool=False, require_tool=False, tool_result=None,
                output_limit=PILOT.output_limit, selection_only=False, arm=None):
        if require_tool and not offer_tool:
            raise ValueError("A required tool must be offered")
        if selection_only and (not offer_tool or require_tool or tool_result is not None):
            raise ValueError("Selection requires optional tools and no prior result")
        stability = packet.get("version") == STABILITY_PACKET_VERSION
        remediation = stability or packet.get("version") == REASSESSMENT_PACKET_VERSION
        context = {"observation_packet": packet}
        if tool_result is not None:
            context["executed_tool"] = dict(tool_result)
            if "finding" in tool_result:
                # The local receipt keeps the tool's source rows. Provider citations use witness IDs.
                context["executed_tool"]["finding"] = {
                    key: value for key, value in tool_result["finding"].items() if key != "references"}
        if selection_only:
            instructions = REASSESSMENT_SELECTION_PROMPT if remediation else SELECTION_PROMPT
            schema_name = REASSESSMENT_SELECTION_VERSION if remediation else SELECTION_VERSION
            if stability:
                instructions, schema_name = WEIGHT_SELECTION_PROMPT, WEIGHT_SELECTION_VERSION
            schema = _object(action=_enum("skip"))
        else:
            instructions = PROMPT + "\n" + REASSESSMENT_RULE if remediation else PROMPT
            if stability:
                instructions += "\n" + STABILITY_RULE
                instructions += "\n" + (C_WEIGHT_RULE if arm == "C" else B_WEIGHT_RULE)
                context["sleep_decision_basis"] = {
                    target: sleep_decision_basis(packet, target, tool_result, arm=arm)
                    for target in protocol.WINDOWS
                }
            schema_name, schema = "tyr_model_prediction_v2", _prediction_schema(packet, tool_result, arm=arm)
        payload = {
            "model": PILOT.identifier, "reasoning": {"effort": PILOT.effort},
            "instructions": instructions, "input": protocol.canonical(context),
            "max_output_tokens": output_limit, "store": False, "truncation": "disabled",
            "background": False, "stream": False, "service_tier": "default",
            "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        }
        if offer_tool:
            payload.update(tool_choice="required" if require_tool else "auto", parallel_tool_calls=False, tools=[
                {"type": "function", "name": name, "description": description, "strict": True,
                 "parameters": _object(target=_enum(*(("weight",) if stability and name == "evaluate" else TARGETS)))}
                for name, description in TOOLS.items()
            ])
            if selection_only and remediation:
                payload["tools"].append({
                    "type": "function", "name": TOOL_NAME, "strict": True,
                    "description": "Inspect comparable sleep contrasts and stability in all three assigned windows.",
                    "parameters": _object(target=_enum(TOOL_TARGET)),
                })
        if len(protocol.canonical(payload)) > MAX_REQUEST_BYTES:
            raise ValueError("Request exceeds the allowed serialized size")
        return payload

    def usage(self, response, *, output_limit=PILOT.output_limit):
        # Irrespective of payload validity, settle only trustworthy accounting.
        if (type(response) is not dict or response.get("model") != PILOT.identifier
                or response.get("service_tier") != "default"):
            raise ValueError("Missing or unexpected model or service tier")
        usage = response["usage"]
        incoming, outgoing = usage["input_tokens"], usage["output_tokens"]
        if (type(incoming) is not int or type(outgoing) is not int
                or not 0 < incoming <= PILOT.input_limit or not 0 <= outgoing <= output_limit
                or type(usage["total_tokens"]) is not int or usage["total_tokens"] != incoming + outgoing):
            raise ValueError("Usage falls outside this request's verified limits")
        reasoning = usage["output_tokens_details"]["reasoning_tokens"]
        cached = usage["input_tokens_details"]["cached_tokens"]
        if type(reasoning) is not int or not 0 <= reasoning <= outgoing or type(cached) is not int or not 0 <= cached <= incoming:
            raise ValueError("Inconsistent token usage details")
        provider_id = response.get("id")
        provider_id = provider_id if type(provider_id) is str and SAFE_PROVIDER_ID.fullmatch(provider_id) else None
        return {"input_tokens": incoming, "output_tokens": outgoing, "reasoning_tokens": reasoning,
                "cached_input_tokens": cached, "model": PILOT.identifier, "provider_response_id": provider_id}

    def output(self, response, *, offer_tool, selection_only=False, allow_reassessment=False,
               weight_only_evaluation=False):
        status = response.get("status")
        if status in ("incomplete", "failed"):
            raise InvalidResult("provider_" + status)
        if status != "completed":
            raise InvalidResult("unexpected_provider_status")
        if type(response["output"]) is not list or len(response["output"]) > 16:
            raise InvalidResult("malformed_provider_output")
        # Reasoning content stays opaque and is discarded. No provider items are replayed upstream.
        messages = [item for item in response["output"] if item["type"] != "reasoning"]
        if len(messages) != 1:
            raise InvalidResult("malformed_provider_output")
        item = messages[0]
        if item["type"] == "function_call":
            name = item["name"]
            if not offer_tool or type(name) is not str:
                raise InvalidResult("invalid_tool")
            targets = TARGETS if name in TOOLS else ()
            if weight_only_evaluation and name == "evaluate":
                targets = ("weight",)
            if allow_reassessment and selection_only and name == TOOL_NAME:
                targets = (TOOL_TARGET,)
            if not targets:
                raise InvalidResult("invalid_tool")
            args = _strict_json(item["arguments"])
            if type(args) is not dict or set(args) != {"target"} or args["target"] not in targets:
                raise InvalidResult("invalid_tool")
            return {"status": "tool", "operation": name, "target": args["target"]}
        if item["type"] != "message" or item["role"] != "assistant" or item.get("status") != "completed":
            raise InvalidResult("malformed_provider_output")
        if len(item["content"]) != 1:
            raise InvalidResult("malformed_provider_output")
        part = item["content"][0]
        if part["type"] == "refusal":
            raise InvalidResult("provider_refusal")
        if part["type"] != "output_text":
            raise InvalidResult("malformed_provider_output")
        value = _strict_json(part["text"])
        if selection_only:
            if value != {"action": "skip"}:
                raise InvalidResult("invalid_tool_selection")
            return {"status": "skip"}
        return {"status": "prediction", "prediction": value}


def _strict_json(text):
    if type(text) is not str or len(text) > MAX_OUTPUT_BYTES or len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise InvalidResult("malformed_provider_output")

    def unique(items):
        value = dict(items)
        if len(items) != len(value):
            raise InvalidResult("malformed_provider_output")
        return value

    def reject_constant(_):
        raise InvalidResult("malformed_provider_output")

    return json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)


class SDKTransport:
    """Map SDK responses to plain data. The broker's only transport action is send."""

    def __init__(self, client):
        self.client = client

    def send(self, payload):
        return self.client.responses.create(**payload).model_dump(mode="json")


def _only_responses(request):
    if request.method != "POST" or str(request.url) != "https://api.openai.com/v1/responses":
        raise ValueError("Unexpected provider destination")


@contextmanager
def open_sdk_transport(*, authorized=False):
    """Open the optional transport for a separately approved host launch."""
    if authorized is not True:
        raise PermissionError("Live provider transport requires separate authorization")
    if any(key.startswith("OPENAI_") and key != "OPENAI_API_KEY" for key in os.environ):
        raise ValueError("Use a clean provider environment with only the dedicated project key")
    # Optional dependencies and credentials are resolved only by an approved host launcher.
    from openai import OpenAI
    import httpx2

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("The trusted process needs a project API key")
    with httpx2.Client(trust_env=False, follow_redirects=False, timeout=45.0,
                      event_hooks={"request": [_only_responses]}) as http:
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1/", max_retries=0, http_client=http) as client:
            yield SDKTransport(client)
