"""HTTP implementations of the telemetry protocols (Prometheus, Loki, synthetic probe).

All network errors are converted into results with status error/timeout: no exception escapes, and a
failure is never presented as an empty result.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx


from ..normalize import normalize_log
from .base import EMPTY, ERROR, OK, TIMEOUT, LogLine, LogResult, PromResult, ProbeResult, Series


def _ts(v: float) -> datetime:
    return datetime.fromtimestamp(float(v), UTC)


class PromHttpClient:
    def __init__(self, base_url: str | None = None, timeout_s: float = 3.0, client: httpx.Client | None = None) -> None:
        self.base = (base_url or os.environ.get("CD_PROMETHEUS_URL") or "http://127.0.0.1:9090").rstrip("/")
        self._c = client or httpx.Client(timeout=timeout_s)

    def _get(self, path: str, params: dict, promql: str) -> PromResult:
        try:
            r = self._c.get(f"{self.base}{path}", params=params)
        except httpx.TimeoutException:
            return PromResult(TIMEOUT, promql, error="timeout")
        except httpx.HTTPError as exc:
            return PromResult(ERROR, promql, error=type(exc).__name__)
        if r.status_code != 200:
            return PromResult(ERROR, promql, error=f"http {r.status_code}")
        try:
            body = r.json()
            if body.get("status") != "success":
                return PromResult(ERROR, promql, error="prometheus status error")
            data = body["data"]
            series: list[Series] = []
            if data["resultType"] == "vector":
                for item in data["result"]:
                    t, v = item["value"]
                    series.append(Series(item["metric"], [(_ts(t), float(v))]))
            elif data["resultType"] == "matrix":
                for item in data["result"]:
                    series.append(Series(item["metric"], [(_ts(t), float(v)) for t, v in item["values"]]))
            else:
                return PromResult(ERROR, promql, error="unsupported result type")
        except (ValueError, KeyError, TypeError):
            return PromResult(ERROR, promql, error="malformed response")
        return PromResult(OK if series else EMPTY, promql, series)

    def query(self, promql: str, at: datetime) -> PromResult:
        return self._get("/api/v1/query", {"query": promql, "time": at.timestamp()}, promql)

    def query_range(self, promql: str, start: datetime, end: datetime, step_s: int = 5) -> PromResult:
        return self._get("/api/v1/query_range", {"query": promql, "start": start.timestamp(), "end": end.timestamp(), "step": step_s}, promql)


class LokiHttpClient:
    def __init__(self, base_url: str | None = None, timeout_s: float = 3.0, client: httpx.Client | None = None) -> None:
        self.base = (base_url or os.environ.get("CD_LOKI_URL") or "http://127.0.0.1:3100").rstrip("/")
        self._c = client or httpx.Client(timeout=timeout_s)

    def query_range(self, logql: str, start: datetime, end: datetime, limit: int = 200) -> LogResult:
        params = {"query": logql, "start": int(start.timestamp() * 1e9), "end": int(end.timestamp() * 1e9), "limit": limit, "direction": "forward"}
        try:
            r = self._c.get(f"{self.base}/loki/api/v1/query_range", params=params)
        except httpx.TimeoutException:
            return LogResult(TIMEOUT, logql, error="timeout")
        except httpx.HTTPError as exc:
            return LogResult(ERROR, logql, error=type(exc).__name__)
        if r.status_code != 200:
            return LogResult(ERROR, logql, error=f"http {r.status_code}")
        try:
            lines: list[LogLine] = []
            for stream in r.json()["data"]["result"]:
                lvl = stream.get("stream", {}).get("level", "")
                for ns, text in stream["values"]:
                    # the line's own level, else the stream label; any spelling (WARNING, 40, err) -> debug|info|warn|error
                    n = normalize_log(text, level_hint=lvl)
                    lines.append(LogLine(_ts(int(ns) / 1e9), "" if n.level == "unknown" else n.level, text))
            lines.sort(key=lambda l: l.t)
        except (ValueError, KeyError, TypeError):
            return LogResult(ERROR, logql, error="malformed response")
        return LogResult(OK if lines else EMPTY, logql, lines)


class HttpProber:
    """Independent synthetic probe against the catalog's published_probe_url (not via service telemetry)."""

    def __init__(self, urls: dict[str, str], timeout_s: float = 2.0, client: httpx.Client | None = None) -> None:
        self._urls = urls
        self._c = client or httpx.Client(timeout=timeout_s)

    def probe(self, service: str, at: datetime) -> ProbeResult:
        url = self._urls.get(service)
        if not url:
            return ProbeResult(service, at, None, error="no published probe url")
        started = datetime.now(UTC)
        try:
            r = self._c.get(url)
        except httpx.TimeoutException:
            return ProbeResult(service, at, False, error="timeout")
        except httpx.HTTPError as exc:
            return ProbeResult(service, at, False, error=type(exc).__name__)
        return ProbeResult(service, at, 200 <= r.status_code < 300, r.status_code, (datetime.now(UTC) - started).total_seconds())
