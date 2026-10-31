"""Raw log line -> NormalizedLog. Accepts the contract format (one JSON object per line) and every other shape we meet:
other key spellings, nested objects, plain text, truncated JSON. Never raises."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .naming import canonical_level, canonical_service, clean_text, parse_time, snake_key
from .records import NormalizedLog

_ALIASES = {
    "t": ("ts", "time", "timestamp", "datetime", "date", "t", "at"),
    "level": ("level", "lvl", "severity", "loglevel", "log_level", "levelname", "priority"),
    "message": ("msg", "message", "text", "log", "event", "body"),
    "service": ("service", "service_name", "svc", "app", "application", "component", "container_name"),
    "request_id": ("request_id", "req_id", "requestid", "correlation_id", "x_request_id"),
    "error": ("error", "err", "exception", "exc", "exc_info", "stack", "stacktrace"),
}
_SIGS = (  # order matters: the most specific first
    ("conn_limit", re.compile(r"(?i)too many (clients|connections)|connection limit|max_connections|remaining connection slots")),
    ("no_space", re.compile(r"(?i)no space left|disk full|enospc")),
    ("oom", re.compile(r"(?i)out of memory|oom[- ]?kill|cannot allocate memory|memoryerror")),
    ("conn_fail", re.compile(r"(?i)connection (failed|refused|reset)|connect: connection refused|dial tcp|operationalerror|name or service not known")),
    ("timeout", re.compile(r"(?i)timed? ?out|deadline exceeded")),
)
_MAX_FIELDS, _MAX_DEPTH = 40, 3


def classify(text: str) -> str:
    for kind, rx in _SIGS:
        if rx.search(text):
            return kind
    return "other"


def _scalarise(v: Any, depth: int = 0) -> Any:
    """Keep fields flat and bounded: scalars as they are, small containers as JSON text, the rest as their type name."""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return clean_text(v, 512)[0]
    if depth < _MAX_DEPTH and isinstance(v, (dict, list)):
        try:
            return clean_text(json.dumps(v, sort_keys=True, default=str), 512)[0]
        except (TypeError, ValueError):
            pass
    return f"<{type(v).__name__}>"


def _pick(flat: dict[str, Any], names: tuple[str, ...]) -> tuple[Any, str | None]:
    for n in names:
        if n in flat and flat[n] not in (None, ""):
            return flat[n], n
    return None, None


def normalize_log(raw: Any, *, service_hint: str | None = None, level_hint: str | None = None, time_hint: Any = None) -> NormalizedLog:
    """`*_hint` are values known from outside the line (Loki stream labels and timestamp); the line's own fields win."""
    text = raw if isinstance(raw, str) else (json.dumps(raw, default=str) if isinstance(raw, (dict, list)) else str(raw))
    sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    notes: list[str] = []
    obj: Any = raw if isinstance(raw, dict) else None
    if obj is None and isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            obj = json.loads(raw)
        except ValueError:
            notes.append("looks like JSON but does not parse (cut off?)")
    if not isinstance(obj, dict):
        msg, trunc = clean_text(text)
        return NormalizedLog(parse_time(time_hint)[0], canonical_level(level_hint), canonical_service(service_hint), msg, None, None,
                             classify(msg), {}, "text", trunc, False, sha, True, tuple(notes))
    flat = {snake_key(k): v for k, v in obj.items()}
    used: set[str] = set()
    got: dict[str, Any] = {}
    for target, names in _ALIASES.items():
        v, key = _pick(flat, names)
        got[target] = v
        if key:
            used.add(key)
    t, assumed = parse_time(got["t"] if got["t"] is not None else time_hint)
    if t is None:
        notes.append("no readable timestamp")
    level = canonical_level(got["level"] if got["level"] is not None else level_hint)
    if level == "unknown":
        notes.append("no readable level")
    svc = canonical_service(got["service"]) or canonical_service(service_hint)
    msg, trunc1 = clean_text(got["message"] if got["message"] is not None else "")
    err, trunc2 = clean_text(got["error"]) if got["error"] is not None else (None, False)
    if not msg:
        notes.append("no message")
    rid = None if got["request_id"] is None else clean_text(got["request_id"], 128)[0]
    extra = {k: _scalarise(v) for k, v in flat.items() if k not in used}
    if len(extra) > _MAX_FIELDS:
        notes.append(f"{len(extra) - _MAX_FIELDS} fields dropped (limit {_MAX_FIELDS})")
        extra = dict(list(extra.items())[:_MAX_FIELDS])
    status = "ok" if t is not None and level != "unknown" and msg else "partial"
    return NormalizedLog(t, level, svc, msg, rid, err, classify(f"{msg} {err or ''}"), extra, status, trunc1 or trunc2, assumed, sha, True, tuple(notes))
