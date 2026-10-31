"""Canonical record shapes. Every normaliser returns these; nothing downstream reads raw service JSON.
Field names are snake_case; times are aware UTC datetimes; durations are seconds; sizes are bytes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# parse_status: ok = every expected field understood | partial = usable but something was missing or guessed
#               text = not structured, kept as a message | unparsed = could not be read at all (raw hash kept)


@dataclass(frozen=True)
class NormalizedLog:
    t: datetime | None
    level: str                       # debug | info | warn | error | unknown
    service: str | None              # catalog-style name
    message: str                     # UNTRUSTED
    request_id: str | None
    error: str | None                # UNTRUSTED
    kind: str                        # signature: conn_fail | conn_limit | timeout | no_space | oom | other
    fields: dict[str, Any] = field(default_factory=dict)  # remaining keys, snake_case, scalars only, UNTRUSTED
    parse_status: str = "ok"
    truncated: bool = False
    assumed_utc: bool = False
    raw_sha256: str = ""
    untrusted: bool = True
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedMetric:
    name: str                        # exactly as exported (names are part of contracts/telemetry.md)
    labels: dict[str, str]           # keys snake_case
    value: float | None              # None for NaN or an unreadable value
    t: datetime | None
    service: str | None
    metric_type: str                 # counter | gauge | histogram_part | info | unknown (inferred from the name)
    unit: str                        # seconds | bytes | ratio | count | none
    parse_status: str = "ok"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedHealth:
    service: str | None
    state: str                       # up | degraded | down | unknown
    components: dict[str, str] = field(default_factory=dict)  # name -> up | degraded | down | unknown
    detail: str | None = None        # UNTRUSTED
    http_status: int | None = None
    parse_status: str = "ok"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Unclassified:
    """Anything no normaliser understood. Kept, never dropped, never guessed at."""
    source: str
    reason: str
    preview: str                     # UNTRUSTED, truncated
    raw_sha256: str
    parse_status: str = "unparsed"
    untrusted: bool = True
