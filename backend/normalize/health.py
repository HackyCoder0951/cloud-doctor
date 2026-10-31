"""Health-check payloads in their many shapes -> NormalizedHealth ({"status": "alive"}, {"ok": true}, "UP", components, ...)."""
from __future__ import annotations

import json
from typing import Any

from .naming import canonical_service, clean_text, snake_key
from .records import NormalizedHealth

_UP = {"alive", "ok", "okay", "healthy", "up", "pass", "passing", "ready", "running", "serving", "available", "green", "true", "1"}
_DOWN = {"down", "fail", "failing", "failed", "error", "unhealthy", "critical", "not_ready", "notready", "dead", "unavailable", "red", "false", "0",
         "out_of_service"}
_DEGRADED = {"degraded", "warn", "warning", "partial", "yellow", "limited"}
_KEYS = ("status", "state", "health", "healthy", "ok", "alive", "ready", "up", "result")
_SUB = ("components", "checks", "dependencies", "details", "services")


def _state(v: Any) -> str:
    if isinstance(v, bool):
        return "up" if v else "down"
    if isinstance(v, (int, float)):
        return "up" if v == 1 else "down" if v == 0 else "unknown"
    s = snake_key(v) if isinstance(v, str) else ""
    return "up" if s in _UP else "down" if s in _DOWN else "degraded" if s in _DEGRADED else "unknown"


def normalize_health(raw: Any, *, service_hint: str | None = None, http_status: int | None = None) -> NormalizedHealth:
    svc = canonical_service(service_hint)
    notes: list[str] = []
    obj = raw
    if isinstance(raw, (str, bytes)):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        try:
            obj = json.loads(text)
        except ValueError:
            obj = text.strip()
    top: str | None = None
    comps: dict[str, str] = {}
    detail: str | None = None
    if isinstance(obj, dict):
        flat = {snake_key(k): v for k, v in obj.items()}
        for k in _KEYS:
            if k in flat:
                top = _state(flat[k])
                break
        for k in _SUB:
            sub = flat.get(k)
            if isinstance(sub, dict):
                comps.update({snake_key(n): _state(v.get("status", v.get("state")) if isinstance(v, dict) else v) for n, v in sub.items()})
            elif isinstance(sub, list):
                for e in sub:
                    if isinstance(e, dict) and ("name" in e or "component" in e):
                        comps[snake_key(e.get("name", e.get("component")))] = _state(e.get("status", e.get("state")))
        d = flat.get("detail", flat.get("message", flat.get("error")))
        detail = clean_text(d, 300)[0] if d is not None else None
        svc = svc or canonical_service(flat.get("service", flat.get("name")))
    elif isinstance(obj, (str, bool, int, float)):
        top = _state(obj)
    if top is None and http_status is not None:
        top = "up" if 200 <= http_status < 300 else "down"
        notes.append("state taken from the HTTP status; the body had no status field")
    if top is None and comps:
        vals = set(comps.values())
        top = "up" if vals == {"up"} else "down" if vals == {"down"} else "degraded"
        notes.append("state derived from components")
    if top in (None, "unknown"):
        notes.append("status value not recognised")
    if top == "up" and "down" in comps.values():
        top = "degraded"
        notes.append("reports up but a component is down")
    return NormalizedHealth(svc, top or "unknown", comps, detail, http_status, "ok" if not notes else "partial", tuple(notes))
