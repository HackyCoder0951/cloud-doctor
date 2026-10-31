"""Prometheus data -> NormalizedMetric. Handles the HTTP API result shapes and the text exposition format."""
from __future__ import annotations

import math
import re
from typing import Any

from .naming import canonical_service, parse_time, snake_key
from .records import NormalizedMetric

_UNIT_SUFFIX = (("_seconds_total", "seconds"), ("_seconds", "seconds"), ("_bytes_total", "bytes"), ("_bytes", "bytes"),
                ("_ratio", "ratio"), ("_total", "count"), ("_count", "count"), ("_connections", "count"), ("_length", "count"), ("_depth", "count"))


def describe(name: str) -> tuple[str, str]:
    """(metric_type, unit) inferred from the metric name alone (Prometheus naming conventions)."""
    if name.endswith("_info"):
        mtype = "info"
    elif name.endswith(("_bucket", "_sum")) or name.endswith("_count") and "_duration" in name:
        mtype = "histogram_part"
    elif name.endswith(("_total", "_created")):
        mtype = "counter"
    else:
        mtype = "gauge" if name else "unknown"
    base = name[:-7] if name.endswith("_bucket") else name
    unit = next((u for suf, u in _UNIT_SUFFIX if base.endswith(suf)), "none")
    return mtype, unit


def _value(v: Any) -> tuple[float | None, str | None]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None, "value is not a number"
    return (None, "NaN (stale or undefined)") if math.isnan(f) else (f, None)


def _build(name: str, labels: dict[str, Any], value: Any, t: Any) -> NormalizedMetric:
    notes: list[str] = []
    lab = {snake_key(k): str(v) for k, v in labels.items() if k != "__name__"}
    val, why = _value(value)
    if why:
        notes.append(why)
    when, _ = parse_time(t)
    mtype, unit = describe(name)
    if name != name.lower():
        notes.append("metric name is not lower-case snake_case")
    return NormalizedMetric(name, lab, val, when, canonical_service(lab.get("service")), mtype, unit, "ok" if not notes else "partial", tuple(notes))


def normalize_prom_result(result: Any) -> list[NormalizedMetric]:
    """`data.result` of /api/v1/query (vector) or /query_range (matrix); a full response body is accepted too."""
    if isinstance(result, dict) and "data" in result:
        result = result["data"].get("result", []) if isinstance(result["data"], dict) else []
    elif isinstance(result, dict):
        result = [result]  # a single vector element
    out: list[NormalizedMetric] = []
    for item in result or []:
        m = item.get("metric", {})
        name = m.get("__name__", "")
        if "values" in item:
            out += [_build(name, m, v, t) for t, v in item["values"]]
        elif "value" in item:
            t, v = item["value"]
            out.append(_build(name, m, v, t))
    return out


_LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)(?:\s+(\d+))?$')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def normalize_exposition(text: str) -> list[NormalizedMetric]:
    out: list[NormalizedMetric] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, lab, val, ts = m.groups()
        labels = {k: v.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\") for k, v in _LABEL.findall(lab or "")}
        out.append(_build(name, labels, val, int(ts) / 1000 if ts else None))
    return out
