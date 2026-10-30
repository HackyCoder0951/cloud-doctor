"""Injectable time. Everything time-dependent takes a Clock so tests and replays are deterministic."""
from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


def iso(dt: datetime) -> str:
    """RFC 3339 UTC with a Z suffix (fractional seconds only when non-zero)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC)
    if not _TS.match(value):
        raise ValueError(f"not an RFC 3339 timestamp: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """Virtual clock: sleep() advances time instantly."""

    def __init__(self, start: datetime | str = "2026-11-02T09:00:00Z") -> None:
        self._now = parse_ts(start)

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, when: datetime | str) -> None:
        self._now = parse_ts(when)
