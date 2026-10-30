"""Builds the MINIMISED OPA input. Free text, logs and evidence never cross this boundary."""
from __future__ import annotations

import re
from datetime import datetime, timezone

ACTIONS = {"restart_service", "rollback_service", "scale_service", "clear_cache", "isolate_dependency", "escalate"}
_SERVICE = re.compile(r"[a-z][a-z0-9-]{1,40}")
_VERSION = re.compile(r"[A-Za-z0-9._-]{1,64}")
_TENANT = re.compile(r"[A-Za-z0-9._-]{1,40}")
_CHANNEL = re.compile(r"C[0-4]")
_COUNTERS = ("attempts_used", "failed_attempts", "actions_in_window")


class InputError(ValueError):
    pass


def build_opa_input(plan: dict, *, target_kind: str | None, confidence: float, counters: dict,
                    tenant: str, channel: str, now: datetime) -> dict:
    """Whitelist construction: only these keys, only these types. `reason`, `rationale`,
    `evidence_refs` and every other free-text field are deliberately left out."""
    if not isinstance(plan, dict):
        raise InputError("plan must be an object")
    action = plan.get("action_id")
    if action not in ACTIONS:
        raise InputError("unknown action")
    params, out_params = plan.get("params") or {}, {}
    for key in ("service", "dependency"):
        if key in params:
            if not (isinstance(params[key], str) and _SERVICE.fullmatch(params[key])):
                raise InputError(f"bad {key}")
            out_params[key] = params[key]
    if "version" in params:
        if not (isinstance(params["version"], str) and _VERSION.fullmatch(params["version"])):
            raise InputError("bad version")
        out_params["version"] = params["version"]
    if "replicas" in params:
        if type(params["replicas"]) is not int or not 1 <= params["replicas"] <= 5:
            raise InputError("bad replicas")
        out_params["replicas"] = params["replicas"]
    if plan.get("risk_class") not in ("low", "medium", "high"):
        raise InputError("bad risk_class")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        raise InputError("confidence must be within 0..1")
    if not (isinstance(tenant, str) and _TENANT.fullmatch(tenant)) or not (isinstance(channel, str) and _CHANNEL.fullmatch(channel)):
        raise InputError("bad tenant or channel")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise InputError("now must be timezone-aware")
    clean_counters = {}
    for key in _COUNTERS:
        if key in counters:
            if type(counters[key]) is not int or counters[key] < 0:
                raise InputError(f"bad counter {key}")
            clean_counters[key] = counters[key]
    target = {"service": out_params.get("service")}
    if target["service"] is None:
        del target["service"]
    if target_kind is not None:
        if target_kind not in ("app", "cache", "queue_worker", "database", "load_generator"):
            raise InputError("bad target kind")
        target["kind"] = target_kind
    return {
        "action": action, "params": out_params, "target": target, "risk_class": plan["risk_class"],
        "confidence": float(confidence), "counters": clean_counters, "tenant": tenant, "channel": channel,
        "time": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
