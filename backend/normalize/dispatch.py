"""Single entry point. `normalize(source, raw)` returns canonical records for any input and never raises: what it cannot
understand comes back as `Unclassified` (with a hash of the original), so nothing is silently lost."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .health import normalize_health
from .logs import normalize_log
from .metrics import normalize_exposition, normalize_prom_result
from .naming import clean_text
from .records import NormalizedHealth, NormalizedLog, NormalizedMetric, Unclassified

Record = NormalizedLog | NormalizedMetric | NormalizedHealth | Unclassified
SOURCES = ("log", "prom_result", "prom_exposition", "health", "auto")


def _unclassified(source: str, raw: Any, reason: str) -> Unclassified:
    text = raw if isinstance(raw, str) else json.dumps(raw, default=str) if isinstance(raw, (dict, list)) else repr(raw)
    return Unclassified(source, reason, clean_text(text, 300)[0], hashlib.sha256(text.encode("utf-8", "replace")).hexdigest())


def _detect(raw: Any) -> str:
    if isinstance(raw, dict):
        keys = {str(k).lower() for k in raw}
        if "metric" in keys and ("value" in keys or "values" in keys) or "data" in keys and isinstance(raw.get("data"), dict) and "result" in raw["data"]:
            return "prom_result"
        if keys & {"msg", "message", "level", "lvl", "severity"}:
            return "log"
        if keys & {"status", "healthy", "alive", "ok", "ready", "state", "health"}:
            return "health"
    if isinstance(raw, str) and raw.lstrip().startswith(("# HELP", "# TYPE")):
        return "prom_exposition"
    return "log"


def normalize(source: str, raw: Any, **hints: Any) -> list[Record]:
    try:
        if source == "auto":
            source = _detect(raw)
        if source == "log":
            return [normalize_log(raw, **hints)]
        if source == "health":
            return [normalize_health(raw, **hints)]
        if source == "prom_result":
            recs = normalize_prom_result(raw)
            return recs or [_unclassified(source, raw, "no samples in the result")]
        if source == "prom_exposition":
            recs = normalize_exposition(raw if isinstance(raw, str) else str(raw))
            return recs or [_unclassified(source, raw, "no samples in the text")]
        return [_unclassified(source, raw, f"unknown source {source!r}")]
    except Exception as exc:  # noqa: BLE001 - the contract of this function is that it does not raise
        return [_unclassified(source, raw, f"normaliser failed: {type(exc).__name__}")]
