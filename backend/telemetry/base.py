"""Telemetry client protocols and result types.

Hard rule: a failed/timed-out query is NEVER reported as "no data". Every client returns a result whose
``status`` is ok | empty | error | timeout; error/timeout map to missing_signal_state ``collection_failed``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

OK, EMPTY, ERROR, TIMEOUT = "ok", "empty", "error", "timeout"


@dataclass
class Series:
    labels: dict[str, str]
    points: list[tuple[datetime, float]]


@dataclass
class PromResult:
    status: str
    query: str
    series: list[Series] = field(default_factory=list)
    error: str | None = None  # short, non-sensitive reason

    @property
    def failed(self) -> bool:
        return self.status in (ERROR, TIMEOUT)

    def last_value(self) -> float | None:
        for s in self.series:
            if s.points:
                return s.points[-1][1]
        return None

    def first_series(self) -> Series | None:
        return self.series[0] if self.series else None


@dataclass
class LogLine:
    t: datetime
    level: str
    line: str  # UNTRUSTED text: never executed, never rendered as HTML


@dataclass
class LogResult:
    status: str
    query: str
    lines: list[LogLine] = field(default_factory=list)
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.status in (ERROR, TIMEOUT)


@dataclass
class ChangeEvent:
    kind: str  # deploy | container_stop | container_start | oom_kill
    service: str
    event_time: datetime
    detail: dict = field(default_factory=dict)


@dataclass
class ChangeResult:
    status: str
    events: list[ChangeEvent] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProbeResult:
    service: str
    at: datetime
    ok: bool | None  # None = could not be established (fail closed)
    status_code: int | None = None
    latency_s: float | None = None
    error: str | None = None


class PromClient(Protocol):
    def query(self, promql: str, at: datetime) -> PromResult: ...
    def query_range(self, promql: str, start: datetime, end: datetime, step_s: int = 5) -> PromResult: ...


class LogClient(Protocol):
    def query_range(self, logql: str, start: datetime, end: datetime, limit: int = 200) -> LogResult: ...


class ChangeFeed(Protocol):
    def events(self, start: datetime, end: datetime) -> ChangeResult: ...


class Prober(Protocol):
    def probe(self, service: str, at: datetime) -> ProbeResult: ...


def missing_signal_for(status: str, expected_absent: bool) -> str:
    """Map a query status to the contract's missing_signal_state."""
    if status in (ERROR, TIMEOUT):
        return "collection_failed"
    if status == EMPTY:
        return "no_data_expected" if expected_absent else "no_data_unexpected"
    return "none"
