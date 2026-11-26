"""Canonical Brain v1 encoding for the portable subset written by this Lab."""

import hashlib
import hmac
import json


def _frozen(value):
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int and -(2**63) <= value < 2**63:
        return value
    if type(value) is list:
        return [_frozen(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _frozen(value[key]) for key in sorted(value, key=lambda item: item.encode("utf-16-be"))}
    raise ValueError("Lab Brain JSON uses signed 64-bit integers and excludes floating-point JSON numbers")


def envelope(payload):
    if type(payload) is not dict:
        raise ValueError("Brain envelope requires an object")
    encoded = json.dumps({"payload": _frozen(payload), "version": 1}, separators=(",", ":"), ensure_ascii=False)
    encoded.encode("utf-8")
    return encoded


def sha256(encoded):
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _check_spec(payload):
    if type(payload) is not dict:
        raise ValueError("Missing frozen specification")
    hypothesis = payload.get("hypothesis")
    fields = ("uuid", "title", "statement", "domain", "hypothesisType", "claimType", "originType", "registrationMode")
    if (type(hypothesis) is not dict or not all(type(hypothesis.get(key)) is str and hypothesis[key] for key in fields)
            or "originRef" not in hypothesis or (hypothesis["originRef"] is not None and type(hypothesis["originRef"]) is not str)
            or type(hypothesis.get("registeredAt")) is not int or type(hypothesis.get("definitionVersion")) is not int
            or hypothesis["definitionVersion"] < 1):
        raise ValueError("Incomplete frozen hypothesis")
    for key, accepted in {
        "hypothesisType": ("intervention", "association", "descriptive"),
        "claimType": ("descriptive", "association", "causal"),
        "originType": ("user", "observation", "imported", "unknown"),
        "registrationMode": ("prospective", "retrospective", "mixed", "unknown"),
    }.items():
        if hypothesis[key] not in accepted:
            raise ValueError("Unsupported frozen hypothesis value")
    for key in ("metricBindings", "interventionBindings", "interventionOutcomes"):
        if type(payload.get(key)) is not list or any(type(item) is not dict for item in payload[key]):
            raise ValueError("Frozen bindings or outcomes must be a list of objects")
    for binding in payload["interventionBindings"]:
        period = binding.get("interventionPeriodUuid")
        if period is not None and (type(period) is not str or not period.strip()):
            raise ValueError("Invalid frozen period reference")
    if type(payload.get("analysisParameters")) is not dict:
        raise ValueError("Missing frozen analysis parameters")


def specification(payload):
    _check_spec(payload)
    encoded = envelope(payload)
    return encoded, sha256(encoded)


def validate_specification(encoded, checksum):
    if type(encoded) is not str or type(checksum) is not str:
        return 0
    try:
        decoded = json.loads(encoded)
        if (type(decoded) is not dict or set(decoded) != {"payload", "version"}
                or type(decoded["version"]) is not int or decoded["version"] != 1):
            return 0
        canonical, digest = specification(decoded["payload"])
        return int(canonical == encoded and hmac.compare_digest(digest, checksum))
    except (ValueError, TypeError, RecursionError):
        return 0
