"""Deterministic synthetic telemetry scenarios (JSON fixtures are generated from this module).

HONESTY NOTE: these are hand-modelled from contracts/telemetry.md and docs/11-experiments/*.md, NOT recordings
of a real sandbox run. Values are illustrative; shapes (onset order, absent series, restarts) follow the docs.
Run `python tests/backend/fixtures/scenarios.py` to (re)write the JSON files next to this module.
"""
from __future__ import annotations

import json
from pathlib import Path

START = "2026-11-02T09:00:00Z"
BASE_EPOCH = 1793610000  # epoch of START: process_start_time_seconds values are START + offset


def _noise(i: int, amp: float) -> float:
    return amp * (((i * 7919) % 13) / 13 - 0.5)


class Builder:
    def __init__(self, name: str, description: str, duration: int = 300, step: int = 5) -> None:
        self.d = {"name": name, "description": description, "start": START, "step_seconds": step, "duration_seconds": duration,
                  "samples": {}, "outages": [], "logs": [], "events": [], "probes": {}}
        self.step, self.duration = step, duration
        self._steady()

    # -- sampling helpers
    def times(self, lo: float = 0, hi: float | None = None):
        hi = self.duration + 1 if hi is None else hi  # inclusive of the final step
        t = lo
        while t < hi:
            yield t
            t += self.step

    def put(self, svc: str, metric: str, fn, lo: float = 0, hi: float | None = None) -> None:
        """Replace samples of svc/metric in [lo, hi) with fn(t) (a constant or callable; None = leave a gap)."""
        cur = [s for s in self.d["samples"].setdefault(svc, {}).get(metric, []) if not (lo <= s[0] < (self.duration + 1 if hi is None else hi))]
        for i, t in enumerate(self.times(lo, hi)):
            v = fn(t) if callable(fn) else fn
            if v is not None:
                cur.append([t, v])
        self.d["samples"][svc][metric] = sorted(cur, key=lambda s: s[0])

    def gap(self, svc: str, metric: str, lo: float, hi: float | None = None) -> None:
        self.put(svc, metric, lambda t: None, lo, hi)

    def _steady(self) -> None:
        for svc in ("api", "worker", "redis", "app-db", "loadgen"):
            self.put(svc, "up", 1)
        for svc in ("redis", "app-db"):
            self.put(svc, "cd_service_up", 1)
        for svc in ("api", "worker", "loadgen"):
            self.put(svc, "start_time", BASE_EPOCH - 3600)
        self.put("api", "request_rate", lambda t: 10 + _noise(int(t), 0.6))
        self.put("api", "error_ratio", lambda t: max(0.0, 0.004 + _noise(int(t), 0.004)))
        self.put("api", "latency_p95", lambda t: 0.08 + _noise(int(t), 0.01))
        self.put("api", "build_version", "v1")
        self.put("api", "memory_bytes", lambda t: 120e6 + _noise(int(t), 2e6))
        self.put("api", "cpu_cores", lambda t: 0.2 + _noise(int(t), 0.04))
        self.put("app-db", "db_probe_seconds", lambda t: 0.001 + abs(_noise(int(t), 0.0005)))
        for svc in ("api", "worker"):
            self.put(svc, "db_call_p95", lambda t: 0.03 + abs(_noise(int(t), 0.005)))
        self.put("api", "fs_used_ratio", lambda t: 0.55 + abs(_noise(int(t), 0.002)))
        self.put("app-db", "db_connections", lambda t: 3 + abs(_noise(int(t), 1)))
        self.put("app-db", "db_max_connections", 100)
        self.put("app-db", "db_connections_by_client", {"api": 2, "worker": 1})
        self.put("worker", "queue_depth", lambda t: 3 + _noise(int(t), 3))
        self.put("worker", "memory_bytes", lambda t: 80e6 + _noise(int(t), 2e6))
        for svc in ("api", "worker"):
            for dep in ("redis", "app-db"):
                self.put(svc, f"dependency_up:{dep}", 1)
        self.put("loadgen", "dependency_up:api", 1)

    def log(self, t: float, svc: str, level: str, msg: str, **extra) -> None:
        rec = {"ts": f"t+{int(t)}s", "level": level, "service": svc, "msg": msg, **extra}
        self.d["logs"].append({"t_s": t, "service": svc, "level": level, "line": json.dumps(rec, sort_keys=True)})

    def event(self, t: float, kind: str, svc: str, **detail) -> None:
        self.d["events"].append({"t_s": t, "kind": kind, "service": svc, "detail": detail})

    def outage(self, lo: float, hi: float, mode: str, signal: str = "all") -> None:
        self.d["outages"].append({"from_s": lo, "to_s": hi, "mode": mode, "signal": signal})

    def probe_down(self, svc: str, lo: float, hi: float) -> None:
        self.d["probes"].setdefault(svc, []).append({"from_s": lo, "to_s": hi, "ok": False})

    def build(self) -> dict:
        self.d["logs"].sort(key=lambda e: (e["t_s"], e["service"]))
        self.d["events"].sort(key=lambda e: (e["t_s"], e["service"]))
        return self.d


def ramp(t0: float, t1: float, v0: float, v1: float):
    return lambda t: v0 if t <= t0 else v1 if t >= t1 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def control() -> dict:
    return Builder("control", "Steady state, no fault (control run: expect zero incidents)").build()


def redis_outage(recover_at: float | None = None, persistent: bool = False) -> dict:
    """EXP-01. Per contracts/telemetry.md: up{redis} stays 1 (probe sidecar); cd_service_up falls ~6s after the stop,
    dependency_up ~9s, queue_depth vanishes ~12s, api 5xx ratio ~1.0 ~15s."""
    b = Builder("redis_outage" + ("_recovered" if recover_at else ""), "Redis stopped at t=60s", duration=400)
    T, end = 60, recover_at
    b.event(T, "container_stop", "redis", container="cd-redis")
    b.put("redis", "cd_service_up", 0, T + 5, end)
    for svc in ("api", "worker"):
        b.put(svc, f"dependency_up:redis", 0, T + 10, end)
    b.gap("worker", "queue_depth", T + 10, end)
    b.put("api", "error_ratio", ramp(T + 5, T + 15, 0.004, 0.97), T + 5, end)
    b.put("api", "latency_p95", ramp(T + 5, T + 15, 0.08, 0.2), T + 5, end)
    for t in range(T + 8, (end or b.duration), 4):
        b.log(t, "api", "error", "redis connection failed", error="dial tcp: connect: connection refused")
        if t % 8 == 0:
            b.log(t + 1, "worker", "error", "redis connection failed", error="dial tcp: connect: connection refused")
    if end:
        b.event(end, "container_start", "redis", container="cd-redis")
        b.put("api", "error_ratio", ramp(end, end + 15, 0.97, 0.004), end, end + 20)
        b.put("api", "latency_p95", 0.08, end, None)
        b.put("worker", "queue_depth", ramp(end, end + 40, 400, 5), end + 5, end + 45)
    return b.build()


def worker_crash(recover_at: float | None = None) -> dict:
    """EXP-02: worker exits; api healthy. The worker exports queue_depth, so the series is ABSENT while it is dead (observed on the
    sandbox, docs/dev/infra/STATUS.md) and reappears with the accumulated backlog after the restart. With recover_at the worker is back from that time."""
    b = Builder("worker_crash" + ("_recovered" if recover_at else ""), "Worker process killed at t=60s; api healthy; queue_depth series absent while the worker is down")
    T, end = 60, recover_at
    b.log(T - 2, "worker", "error", "job failed: unexpected exception", error="worker panic")
    b.event(T + 3, "container_stop", "worker", container="cd-worker")
    b.put("worker", "up", 0, T + 5, end)
    b.gap("worker", "start_time", T + 5, end)
    b.gap("worker", "dependency_up:redis", T + 5, end)
    b.gap("worker", "dependency_up:app-db", T + 5, end)
    b.gap("worker", "memory_bytes", T + 5, end)
    b.put("worker", "queue_depth", lambda t: 3 + (t - T) * 6, T, T + 5)  # last scrapes before the exporter dies
    b.gap("worker", "queue_depth", T + 5, end)
    if end:
        b.event(end, "container_start", "worker", container="cd-worker")
        b.put("worker", "start_time", BASE_EPOCH + end, end)
        b.put("worker", "queue_depth", ramp(end, end + 40, 3 + (end - T) * 6, 4), end)
    return b.build()


def memory_exhaustion() -> dict:
    """EXP-04: api memory leaks; OOM kills at t=110 and t=205 (down 15s, then restart); growth resumes each time."""
    b = Builder("memory_exhaustion", "api memory leak under a limit; OOM kill, restart, recurrence", duration=300)
    limit = 256e6
    holes = ("start_time", "memory_bytes", "request_rate", "latency_p95", "cpu_cores", "build_version")

    def cycle(t_start, t_oom, t_back, restart_epoch):
        slope = (limit - 100e6) / (t_oom - t_start)
        b.put("api", "memory_bytes", lambda t: 100e6 + (t - t_start) * slope, t_start, t_oom)
        b.put("api", "up", 0, t_oom, t_back)
        for h in holes:
            b.gap("api", h, t_oom, t_back)
        b.put("api", "error_ratio", 1.0, t_oom, t_back)
        b.put("api", "start_time", restart_epoch, t_back)

    b.put("api", "memory_bytes", lambda t: 120e6 + (t - 40) * 1.95e6, 40, 110)
    b.put("api", "up", 0, 110, 125)
    for h in holes:
        b.gap("api", h, 110, 125)
    b.put("api", "error_ratio", 1.0, 110, 125)
    b.put("api", "start_time", BASE_EPOCH + 125, 125)
    b.put("api", "memory_bytes", lambda t: 100e6 + (t - 125) * 1.95e6, 125, 205)
    b.put("api", "up", 0, 205, 220)
    for h in holes:
        b.gap("api", h, 205, 220)
    b.put("api", "error_ratio", 1.0, 205, 220)
    b.put("api", "start_time", BASE_EPOCH + 220, 220)
    b.put("api", "memory_bytes", lambda t: 100e6 + (t - 220) * 1.95e6, 220)
    b.event(110, "oom_kill", "api", container="cd-api", limit_bytes=int(limit))
    b.event(125, "container_start", "api", container="cd-api")
    b.event(205, "oom_kill", "api", container="cd-api", limit_bytes=int(limit))
    b.event(220, "container_start", "api", container="cd-api")
    b.log(108, "api", "info", "request served")  # logs simply stop: no clean error message at OOM
    return b.build()


def bad_deployment() -> dict:
    """EXP-07: api v2 deployed at t=60; errors from the moment of change; new error signature."""
    b = Builder("bad_deployment", "api v1 -> v2 at t=60s; one endpoint errors")
    T = 60
    b.event(T, "deploy", "api", version_from="v1", version_to="v2", container="cd-api")
    b.put("api", "build_version", "v2", T)
    b.put("api", "start_time", BASE_EPOCH + T, T)
    b.put("api", "error_ratio", lambda t: 0.35 + _noise(int(t), 0.04), T + 5)
    b.put("api", "latency_p95", 0.12, T + 5)
    for t in range(T + 6, 300, 3):
        b.log(t, "api", "error", "ValueError: invalid payload in /work handler", route="/work")
    return b.build()


def false_correlation() -> dict:
    """EXP-09: real fault = api CPU saturation from t=80 (latency up, no errors); decoy = healthy worker v2 deploy at t=60."""
    b = Builder("false_correlation", "Healthy worker deploy at t=60 (decoy); api CPU saturation from t=80 (real)")
    b.event(60, "deploy", "worker", version_from="v1", version_to="v2", container="cd-worker")
    b.put("worker", "start_time", BASE_EPOCH + 60, 60)
    b.put("api", "cpu_cores", ramp(80, 90, 0.2, 1.95), 80)
    b.put("api", "latency_p95", ramp(80, 100, 0.08, 1.4), 80)
    b.put("api", "request_rate", ramp(80, 100, 10, 6), 80)
    return b.build()


def db_saturation() -> dict:
    """EXP-05: connection exhaustion; process up and probe passing, callers cannot get connections."""
    b = Builder("db_saturation", "app-db max_connections exhausted by a leaking client at t=60s")
    T = 60
    b.put("api", "dependency_up:app-db", 0, T + 8)
    b.put("worker", "dependency_up:app-db", 0, T + 8)
    # measured on the sandbox (N=1): a client holding connections shows up in cd_db_connections_by_client under its application_name
    b.put("app-db", "db_connections", ramp(T, T + 8, 3, 100), T)
    b.put("app-db", "db_connections_by_client", lambda t: {"connection_hog": 94, "api": 4, "worker": 2} if t >= T + 8 else {"connection_hog": round(ramp(T, T + 8, 0, 94)(t)), "api": 2, "worker": 1}, T)
    b.put("api", "error_ratio", ramp(T + 5, T + 15, 0.004, 0.62), T + 5)
    b.put("api", "latency_p95", ramp(T + 5, T + 15, 0.08, 0.9), T + 5)
    for t in range(T + 8, 300, 4):
        b.log(t, "api", "error", "database query failed", error="FATAL: sorry, too many clients already")
        b.log(t + 1, "worker", "error", "database query failed", error="FATAL: sorry, too many clients already")
    return b.build()


def network_latency() -> dict:
    """EXP-06: latency injected on the api/worker -> app-db path. Client-side call time rises; the database answers its own probe quickly."""
    b = Builder("network_latency", "added latency between the application and app-db at t=60s; the database itself is healthy")
    T = 60
    for svc in ("api", "worker"):
        b.put(svc, "db_call_p95", ramp(T, T + 10, 0.03, 1.2), T)
    b.put("api", "latency_p95", ramp(T + 2, T + 12, 0.08, 1.5), T + 2)
    return b.build()


def disk_full() -> dict:
    """EXP-11 (draft): the log volume fills; the api starts failing writes."""
    b = Builder("disk_full", "the filesystem used by the api reaches 100% at t=60s")
    T = 60
    b.put("api", "fs_used_ratio", ramp(T - 10, T, 0.55, 1.0), T - 10)
    b.put("api", "error_ratio", ramp(T + 5, T + 15, 0.004, 0.5), T + 5)
    for t in range(T + 5, 300, 4):
        b.log(t, "api", "error", "write failed", error="OSError: [Errno 28] No space left on device")
    return b.build()


def flapping() -> dict:
    """Single-poll error spikes that never persist for 3 consecutive polls (hysteresis must absorb them)."""
    b = Builder("flapping", "api error ratio spikes for one poll at a time")
    for t in range(30, 280, 40):
        b.put("api", "error_ratio", 0.5, t, t + 5)   # one poll
    for t in range(50, 280, 40):
        b.put("api", "error_ratio", 0.4, t, t + 10)  # two consecutive polls, still below enter_after=3
    return b.build()


def low_traffic() -> dict:
    """Error ratio 1.0 at 0.3 rps: below the minimum-traffic floor, so no incident."""
    b = Builder("low_traffic", "very low traffic with 100% errors (noise)")
    b.put("api", "request_rate", 0.3, 40, 200)
    b.put("api", "error_ratio", 1.0, 40, 200)
    return b.build()


def telemetry_outage() -> dict:
    """Prometheus times out for t in [100, 200): services are fine, telemetry is not."""
    b = Builder("telemetry_outage", "Prometheus unreachable for 100s; services healthy")
    b.outage(100, 200, "timeout", "prom")
    return b.build()


def redis_outage_telemetry_failure() -> dict:
    b = redis_outage()
    b["name"] = "redis_outage_telemetry_failure"
    b["outages"].append({"from_s": 120, "to_s": 300, "mode": "timeout", "signal": "prom"})
    b["outages"].append({"from_s": 120, "to_s": 300, "mode": "error", "signal": "loki"})
    return b


def expected_down() -> dict:
    """redis is drained for maintenance 60..200 (declared in the expected-state registry); nothing else changes."""
    b = Builder("expected_down", "redis intentionally down (maintenance), dependents unaffected")
    b.put("redis", "cd_service_up", 0, 60, 200)
    b.event(60, "container_stop", "redis", container="cd-redis", reason="maintenance")
    return b.build()


def telemetry_gap() -> dict:
    """Target vanished: no `up` series for redis (unexpected missing data, not an outage statement)."""
    b = Builder("telemetry_gap", "redis up/cd_service_up series absent from t=80")
    b.gap("redis", "up", 80)
    b.gap("redis", "cd_service_up", 80)
    return b.build()


def concurrent_unrelated() -> dict:
    """worker crash at t=60 and an unrelated loadgen failure at t=90 (loadgen only touches api, which is healthy)."""
    b = worker_crash()
    b["name"] = "concurrent_unrelated"
    bb = Builder.__new__(Builder)
    bb.d, bb.step, bb.duration = b, b["step_seconds"], b["duration_seconds"]
    bb.put("loadgen", "up", 0, 90)
    bb.gap("loadgen", "start_time", 90)
    bb.gap("loadgen", "dependency_up:api", 90)
    return b


def restart_before_recovery() -> dict:
    """A restart (remediation) occurs at t=150 right before recovery; it must never be ranked a cause."""
    b = redis_outage(recover_at=150)
    b["name"] = "restart_before_recovery"
    b["samples"]["redis"]["start_time"] = [[0, BASE_EPOCH - 3600], [150, BASE_EPOCH + 150]]
    return b


ALL = {f.__name__: f for f in (control, redis_outage, worker_crash, memory_exhaustion, bad_deployment, false_correlation, db_saturation,
                               flapping, low_traffic, telemetry_outage, redis_outage_telemetry_failure, expected_down, telemetry_gap,
                               concurrent_unrelated, restart_before_recovery, network_latency, disk_full)}


def recovered_redis() -> dict:
    return redis_outage(recover_at=150)


ALL["redis_outage_recovered"] = recovered_redis
ALL["worker_crash_recovered"] = lambda: worker_crash(recover_at=145)


def write_all(directory: Path | None = None) -> None:
    out = directory or Path(__file__).parent
    for name, fn in ALL.items():
        (out / f"{name}.json").write_text(json.dumps(fn(), sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    write_all()
