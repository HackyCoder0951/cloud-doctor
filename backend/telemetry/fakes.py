"""Fixture-based fakes for the telemetry protocols (no network). Driven by a scenario dict (JSON fixtures).

Scenario format (see tests/backend/fixtures/):
  start (RFC3339), step_seconds, duration_seconds,
  samples:  {service: {metric_key: [[offset_s, value], ...]}}   metric_key = a name from detector.yaml `metrics`
            ("dependency_up:<dep>" for dependency_up; build_version values are strings -> label `version`)
  outages:  [{from_s, to_s, mode: error|timeout, signal: prom|loki|all}]   telemetry collection failures
  logs:     [{t_s, service, level, line}]
  events:   [{t_s, kind, service, detail}]                                  change feed
  probes:   {service: [{from_s, to_s, ok}]}   (default ok=true inside the scenario)
`absent_*` metrics are derived: absent_X returns 1 iff the base metric has no sample inside the lookback.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from backend.detector.config import DetectorConfig
from backend.domain.catalog import Catalog
from backend.domain.clock import parse_ts

from .base import EMPTY, ERROR, OK, TIMEOUT, ChangeEvent, ChangeResult, LogLine, LogResult, ProbeResult, PromResult, Series


class Scenario:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.name = data["name"]
        self.start = parse_ts(data["start"])
        self.step = int(data.get("step_seconds", 5))
        self.duration = int(data["duration_seconds"])

    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        return cls(json.loads(Path(path).read_text()))

    def at(self, offset_s: float) -> datetime:
        return self.start + timedelta(seconds=offset_s)

    def offset(self, t: datetime) -> float:
        return (t - self.start).total_seconds()

    def outage(self, t: datetime, signal: str) -> str | None:
        off = self.offset(t)
        for o in self.data.get("outages", []):
            if o["from_s"] <= off < o["to_s"] and o.get("signal", "all") in (signal, "all"):
                return o["mode"]
        return None


def build_query_index(cfg: DetectorConfig, catalog: Catalog) -> dict[str, tuple[str, str]]:
    """Rendered PromQL -> (service, metric_key). The fake answers by exact query string."""
    idx: dict[str, tuple[str, str]] = {}
    for svc in catalog.names():
        for name in cfg.metrics:
            if name == "dependency_up":
                for dep in catalog.dependencies(svc):
                    idx[cfg.query(name, svc, dep)] = (svc, f"dependency_up:{dep}")
            else:
                idx[cfg.query(name, svc)] = (svc, name)
    return idx


class FixturePromClient:
    LOOKBACK_STEPS = 3

    def __init__(self, scenario: Scenario, index: dict[str, tuple[str, str]]) -> None:
        self.s, self.index = scenario, index
        self.calls = 0

    def _samples(self, service: str, key: str) -> list[list]:
        return self.s.data.get("samples", {}).get(service, {}).get(key, [])

    def _series(self, service: str, key: str, start: datetime, end: datetime, instant: bool) -> list[Series]:
        if key.startswith("absent_"):
            base = key[len("absent_"):]
            got = self._series(service, base, start, end, instant)
            return [] if got else [Series({}, [(end, 1.0)])]
        lo, hi = self.s.offset(start), self.s.offset(end)
        pts = [(o, v) for o, v in self._samples(service, key) if lo <= o <= hi]
        if not pts:
            return []
        if key == "build_version":
            version = pts[-1][1] if instant else None
            if instant:
                return [Series({"version": str(version)}, [(self.s.at(pts[-1][0]), 1.0)])]
            out: dict[str, list] = {}
            for o, v in pts:
                out.setdefault(str(v), []).append((self.s.at(o), 1.0))
            return [Series({"version": v}, p) for v, p in out.items()]
        if instant:
            o, v = pts[-1]
            return [Series({"service": service}, [(self.s.at(o), float(v))])]
        return [Series({"service": service}, [(self.s.at(o), float(v)) for o, v in pts])]

    def _answer(self, promql: str, start: datetime, end: datetime, instant: bool) -> PromResult:
        self.calls += 1
        mode = self.s.outage(end, "prom")
        if mode == "timeout":
            return PromResult(TIMEOUT, promql, error="timeout")
        if mode == "error":
            return PromResult(ERROR, promql, error="connection refused")
        target = self.index.get(promql)
        if target is None:
            return PromResult(EMPTY, promql)
        series = self._series(target[0], target[1], start, end, instant)
        return PromResult(OK if series else EMPTY, promql, series)

    def query(self, promql: str, at: datetime) -> PromResult:
        return self._answer(promql, at - timedelta(seconds=self.s.step * self.LOOKBACK_STEPS), at, True)

    def query_range(self, promql: str, start: datetime, end: datetime, step_s: int = 5) -> PromResult:
        return self._answer(promql, start, end, False)


_SEL = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


class FixtureLogClient:
    def __init__(self, scenario: Scenario) -> None:
        self.s = scenario

    def query_range(self, logql: str, start: datetime, end: datetime, limit: int = 200) -> LogResult:
        mode = self.s.outage(end, "loki")
        if mode:
            return LogResult(TIMEOUT if mode == "timeout" else ERROR, logql, error=mode)
        sel_text, _, rest = logql.partition("}")
        labels = dict(_SEL.findall(sel_text))
        filt = re.search(r'\|~\s*"([^"]*)"|\|=\s*"([^"]*)"', rest)
        pattern = (filt.group(1) or re.escape(filt.group(2))) if filt else None
        lo, hi = self.s.offset(start), self.s.offset(end)
        lines = []
        for e in self.s.data.get("logs", []):
            if not (lo <= e["t_s"] <= hi):
                continue
            if labels.get("service") and e["service"] != labels["service"]:
                continue
            if labels.get("level") and e["level"] != labels["level"]:
                continue
            if pattern and not re.search(pattern, e["line"]):
                continue
            lines.append(LogLine(self.s.at(e["t_s"]), e["level"], e["line"]))
        lines = lines[:limit]
        return LogResult(OK if lines else EMPTY, logql, lines)


class FixtureChangeFeed:
    def __init__(self, scenario: Scenario) -> None:
        self.s = scenario

    def events(self, start: datetime, end: datetime) -> ChangeResult:
        mode = self.s.outage(end, "events")
        if mode:
            return ChangeResult(TIMEOUT if mode == "timeout" else ERROR, error=mode)
        lo, hi = self.s.offset(start), self.s.offset(end)
        evs = [ChangeEvent(e["kind"], e["service"], self.s.at(e["t_s"]), dict(e.get("detail", {})))
               for e in self.s.data.get("events", []) if lo <= e["t_s"] <= hi]
        return ChangeResult(OK if evs else EMPTY, evs)


class FixtureProber:
    def __init__(self, scenario: Scenario) -> None:
        self.s = scenario

    def probe(self, service: str, at: datetime) -> ProbeResult:
        mode = self.s.outage(at, "probe")
        if mode:
            return ProbeResult(service, at, None, error=mode)  # cannot be established
        off = self.s.offset(at)
        for w in self.s.data.get("probes", {}).get(service, []):
            if w["from_s"] <= off < w["to_s"]:
                return ProbeResult(service, at, bool(w["ok"]), 200 if w["ok"] else 503, 0.05)
        return ProbeResult(service, at, True, 200, 0.05)
