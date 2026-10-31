"""Naming and value canonicalisation shared by every normaliser. Rules are written down in docs/dev/conventions.md."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

MAX_TEXT = 8192  # characters kept from any untrusted text; the original is identified by its hash

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NONWORD = re.compile(r"[^0-9a-zA-Z]+")


def snake_key(key: Any) -> str:
    """`requestId`, `Request-ID`, `request id`, `@timestamp` -> `request_id`, `request_id`, `request_id`, `timestamp`."""
    s = _CAMEL.sub("_", str(key).strip())
    s = _NONWORD.sub("_", s).strip("_").lower()
    return s or "field"


def clean_text(value: Any, limit: int = MAX_TEXT) -> tuple[str, bool]:
    """Untrusted text -> (safe text, truncated). NUL and control characters removed; never evaluated or rendered as markup."""
    s = value if isinstance(value, str) else str(value)
    s = _CTRL.sub("", s)
    return (s[:limit], True) if len(s) > limit else (s, False)


_LEVELS = {
    "trace": "debug", "debug": "debug", "dbg": "debug", "verbose": "debug", "10": "debug", "20": "debug", "5": "debug",
    "info": "info", "information": "info", "informational": "info", "notice": "info", "log": "info", "30": "info",
    "warn": "warn", "warning": "warn", "wrn": "warn", "40": "warn",
    "error": "error", "err": "error", "fatal": "error", "critical": "error", "crit": "error", "severe": "error",
    "panic": "error", "alert": "error", "emerg": "error", "emergency": "error", "50": "error", "60": "error",
}


# Numeric levels follow pino/bunyan (10 trace, 20 debug, 30 info, 40 warn, 50 error, 60 fatal), the common JSON-logger scheme.
def canonical_level(value: Any) -> str:
    """Any spelling of a severity -> debug | info | warn | error | unknown."""
    return _LEVELS.get(str(value).strip().lower(), "unknown") if value is not None else "unknown"


_SERVICE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def canonical_service(value: Any) -> str | None:
    """`cd-api`, `API`, `api_1` -> catalog-style names; returns None when the value cannot be a service name."""
    if value is None:
        return None
    s = _NONWORD.sub("-", str(value).strip().lower()).strip("-")
    if s.startswith("cd-"):
        s = s[3:]
    return s if _SERVICE.match(s) else None


_RFC = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def parse_time(value: Any) -> tuple[datetime | None, bool]:
    """Timestamp in any common shape -> (aware UTC datetime or None, assumed_utc).
    Accepts RFC 3339, `YYYY-MM-DD HH:MM:SS`, and epoch numbers in seconds, milliseconds, microseconds or nanoseconds."""
    if value is None or isinstance(value, bool):
        return None, False
    if isinstance(value, datetime):
        return (value.astimezone(UTC), False) if value.tzinfo else (value.replace(tzinfo=UTC), True)
    if isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            value = float(s)
        elif _RFC.match(s):
            s2 = s.replace(" ", "T", 1)
            s2 = s2[:-1] + "+00:00" if s2.endswith("Z") else s2
            if re.search(r"[+-]\d{4}$", s2):
                s2 = s2[:-2] + ":" + s2[-2:]
            try:
                d = datetime.fromisoformat(s2)
            except ValueError:
                return None, False
            return (d.astimezone(UTC), False) if d.tzinfo else (d.replace(tzinfo=UTC), True)
        else:
            return None, False
    if isinstance(value, (int, float)):
        v = float(value)
        if v != v or v <= 0:
            return None, False
        for limit, div in ((1e11, 1), (1e14, 1e3), (1e17, 1e6)):
            if v < limit:
                return datetime.fromtimestamp(v / div, UTC), False
        return datetime.fromtimestamp(v / 1e9, UTC), False
    return None, False


_UNITS = {"ns": 1e-9, "us": 1e-6, "µs": 1e-6, "ms": 1e-3, "s": 1.0, "sec": 1.0, "m": 60.0, "min": 60.0, "h": 3600.0,
          "b": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9, "kib": 1024.0, "mib": 1024.0**2, "gib": 1024.0**3}


def to_base_unit(value: float, unit: str) -> float:
    """Durations to seconds and sizes to bytes (SI and binary prefixes kept distinct). Unknown unit -> ValueError."""
    return value * _UNITS[unit.strip().lower()]
