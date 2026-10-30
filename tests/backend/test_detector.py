from datetime import timedelta

import pytest
from helpers import firing, run_detector

from backend.detector.expected import ExpectedStateRegistry
from backend.domain.clock import parse_ts


def run(world, catalog, cfg, name, **kw):
    w = world(name)
    return w, *run_detector(w, catalog, cfg, **kw)


def test_control_run_has_zero_alerts(world, catalog, cfg):
    w, det, fired = run(world, catalog, cfg, "control")
    assert fired == []
    assert all(s.state == "HEALTHY" for s in det.statuses.values())


def test_redis_outage_alerts_and_states(world, catalog, cfg):
    w, det, fired = run(world, catalog, cfg, "redis_outage", until_s=120)
    down = firing(fired, "service_down", "redis")
    assert down and 60 < down[0][0] <= 90  # cd_service_up==0 even though up{redis} stays 1
    assert firing(fired, "error_ratio", "api")
    assert firing(fired, "dependency_down", "api") and firing(fired, "dependency_down", "worker")
    assert firing(fired, "queue_absent", "worker")  # absent series is a signal, not 'healthy'
    assert det.statuses["redis"].state == "UNHEALTHY"
    assert det.statuses["api"].state == "UNHEALTHY"
    assert det.statuses["worker"].state == "DEGRADED"
    assert det.statuses["app-db"].state == "HEALTHY"


def test_hysteresis_enter_and_leave(world, catalog, cfg):
    w, det, fired = run(world, catalog, cfg, "redis_outage_recovered")
    first = firing(fired, "error_ratio", "api")[0][0]
    # breach starts at ~t=70 (ratio >= 0.05); enter_after=3 -> fires on the 3rd consecutive poll, not the 1st
    assert first >= 80
    res = firing(fired, "error_ratio", "api", "resolved")
    assert res and res[0][0] > 150 + 15  # leave_after polls after recovery
    assert det.statuses["api"].state == "HEALTHY"


def test_flapping_does_not_alert(world, catalog, cfg):
    _, det, fired = run(world, catalog, cfg, "flapping")
    assert fired == []


def test_low_traffic_guard_ignores_ratio(world, catalog, cfg):
    w = world("low_traffic")
    bg = []
    det, fired = run_detector(w, catalog, cfg, on_poll=lambda t, r: bg.extend(r.background))
    assert firing(fired, "error_ratio") == []
    assert any("below floor" in b.summary for b in bg)  # the ignored ratio is recorded, not hidden


def test_traffic_floor_is_above_one_rps(cfg):
    assert cfg.low_traffic_floor_rps > 1.0


def test_worker_crash_only_worker_side(world, catalog, cfg):
    _, det, fired = run(world, catalog, cfg, "worker_crash", until_s=140)
    assert firing(fired, "service_down", "worker")
    assert firing(fired, "queue_growth", "worker")
    assert not [a for _, a in fired if a.service == "api"]
    assert det.statuses["api"].state == "HEALTHY"


def test_restart_detection_event_time_is_start_time(world, catalog, cfg):
    _, det, fired = run(world, catalog, cfg, "memory_exhaustion")
    rs = firing(fired, "restart", "api")
    assert rs, "restart not detected"
    t, alert = rs[0]
    assert alert.observed_at == parse_ts("2026-11-02T09:02:05Z")  # process_start_time_seconds, not detection time
    assert alert.fired_at >= alert.observed_at
    assert len(rs) == 1 or rs[1][1].observed_at == parse_ts("2026-11-02T09:03:40Z")


def test_memory_growth_warns_before_oom(world, catalog, cfg):
    _, det, fired = run(world, catalog, cfg, "memory_exhaustion")
    mem = firing(fired, "memory_growth", "api")
    down = firing(fired, "service_down", "api")
    assert mem and down and mem[0][0] < 112 <= down[0][0] + 5


def test_telemetry_outage_is_unknown_not_healthy_and_holds_alerts(world, catalog, cfg):
    w = world("telemetry_outage")
    seen = {}
    det, fired = run_detector(w, catalog, cfg, on_poll=lambda t, r: seen.__setitem__(t, r))
    assert fired == []
    mid = seen[150]
    assert not mid.prometheus_ok
    assert all(s.state == "UNKNOWN" and s.missing_signal_state == "collection_failed" for s in mid.statuses.values())
    assert seen[250].statuses["api"].state == "HEALTHY"


def test_outage_does_not_resolve_firing_alert(world, catalog, cfg):
    data = world("redis_outage").scenario.data
    data["outages"].append({"from_s": 150, "to_s": 300, "mode": "timeout", "signal": "prom"})
    w = world(data)
    det, fired = run_detector(w, catalog, cfg)
    assert firing(fired, "service_down", "redis")
    assert firing(fired, "service_down", "redis", "resolved") == []


def test_unexpected_gap_is_no_data_unexpected(world, catalog, cfg):
    w, det, fired = run(world, catalog, cfg, "telemetry_gap")
    gap = firing(fired, "telemetry_gap", "redis")
    assert gap and not gap[0][1].suppressed
    assert det.statuses["redis"].state == "UNKNOWN" and det.statuses["redis"].missing_signal_state == "no_data_unexpected"
    assert not firing(fired, "service_down", "redis")  # missing data is not a statement that redis is down


def test_expected_down_is_suppressed_but_recorded(world, catalog, cfg):
    w = world("expected_down")
    reg = ExpectedStateRegistry()
    reg.declare("redis", "ops-jignesh", "planned maintenance", w.scenario.at(0), w.scenario.at(250))
    bg = []
    det, fired = run_detector(w, catalog, cfg, registry=reg, on_poll=lambda t, r: bg.extend(r.background))
    down = firing(fired, "service_down", "redis")
    assert down and all(a.suppressed and "planned maintenance" in a.suppress_reason for _, a in down)
    assert any("expected down" in b.summary and "ops-jignesh" in b.summary for b in bg)


def test_expected_declaration_expires(world, catalog, cfg):
    w = world("expected_down")
    reg = ExpectedStateRegistry()
    reg.declare("redis", "ops", "maint", w.scenario.at(0), w.scenario.at(100))  # expires while still down
    det, fired = run_detector(w, catalog, cfg, registry=reg)
    flags = [(t, a.suppressed) for t, a in firing(fired, "service_down", "redis")]
    assert flags and flags[0][1] is True
    assert any(not a.suppressed for _, a in firing(fired, "service_down", "redis")) or det.firing_services() == {"redis"}


def test_registry_requires_owner_reason_and_expiry():
    reg = ExpectedStateRegistry()
    t = parse_ts("2026-11-02T09:00:00Z")
    with pytest.raises(ValueError):
        reg.declare("redis", "", "x", t, t + timedelta(hours=1))
    with pytest.raises(ValueError):
        reg.declare("redis", "o", "x", t, t)
