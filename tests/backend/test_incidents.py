from datetime import timedelta

import pytest
from helpers import run_detector

from backend.audit import AuditWriter
from backend.domain.clock import FakeClock, parse_ts
from backend.domain.contracts import validate_against_contract
from backend.incidents.manager import IncidentManager, InvalidTransition
from backend.repositories import MemoryRepository


def build(world, catalog, cfg, name, registry=None, until=None, **mkw):
    w = world(name)
    repo, clock = MemoryRepository(), FakeClock(w.scenario.at(0))
    mgr = IncidentManager(repo, catalog, cfg, AuditWriter(repo, clock), clock, **mkw)

    def on_poll(t, res):
        clock.set(res.at)
        mgr.ingest(res)
        mgr.sweep(res.at)

    det, _ = run_detector(w, catalog, cfg, until_s=until, registry=registry, on_poll=on_poll)
    return w, repo, mgr, det


def test_redis_cascade_is_one_incident_with_all_services(world, catalog, cfg):
    _, repo, mgr, _ = build(world, catalog, cfg, "redis_outage", until=140)
    incs = repo.list_incidents()
    assert len(incs) == 1
    inc = incs[0]
    assert set(inc.services) == {"redis", "api", "worker"} and inc.severity == "high" and inc.state == "detected"
    validate_against_contract(inc.to_contract(), "incident")
    for e in repo.list_events(inc.incident_id):
        validate_against_contract(e.to_contract(), "incident", "#/$defs/timeline_event")


def test_unrelated_concurrent_fault_is_a_separate_incident(world, catalog, cfg):
    _, repo, _, _ = build(world, catalog, cfg, "concurrent_unrelated", until=150)
    incs = sorted(repo.list_incidents(), key=lambda i: i.opened_at)
    assert [set(i.services) for i in incs] == [{"worker"}, {"loadgen"}]


def test_control_flapping_low_traffic_open_nothing(world, catalog, cfg):
    for name in ("control", "flapping", "low_traffic", "telemetry_outage"):
        _, repo, _, _ = build(world, catalog, cfg, name)
        assert repo.list_incidents() == [], name


def test_expected_down_opens_no_incident_but_appears_in_background(world, catalog, cfg):
    from backend.detector.expected import ExpectedStateRegistry
    w = world("expected_down")
    reg = ExpectedStateRegistry()
    reg.declare("redis", "ops", "planned maintenance", w.scenario.at(0), w.scenario.at(400))
    _, repo, mgr, _ = build(world, catalog, cfg, "expected_down", registry=reg)
    assert repo.list_incidents() == []
    texts = [b.summary for b in mgr.background]
    assert any("expected down" in t for t in texts) and any(b.suppressed for b in mgr.background)


def test_expected_down_appears_in_timeline_of_related_incident(world, catalog, cfg):
    from backend.detector.expected import ExpectedStateRegistry
    data = world("expected_down").scenario.data
    # a real api fault during the declared redis maintenance
    data["samples"]["api"]["error_ratio"] = [[t, 0.9 if t >= 100 else 0.004] for t, _ in data["samples"]["api"]["error_ratio"]]
    w = world(data)
    reg = ExpectedStateRegistry()
    reg.declare("redis", "ops", "planned maintenance", w.scenario.at(0), w.scenario.at(400))
    repo, clock = MemoryRepository(), FakeClock(w.scenario.at(0))
    mgr = IncidentManager(repo, catalog, cfg, AuditWriter(repo, clock), clock)

    def on_poll(t, res):
        clock.set(res.at)
        mgr.ingest(res)

    run_detector(w, catalog, cfg, registry=reg, on_poll=on_poll)
    incs = repo.list_incidents()
    assert len(incs) == 1 and "api" in incs[0].services
    evs = repo.list_events(incs[0].incident_id)
    assert any(e.suppressed and "redis" == e.service for e in evs)  # suppressed events stay in the timeline


def test_timeline_event_time_vs_collected_at_and_ordering(world, catalog, cfg):
    _, repo, _, _ = build(world, catalog, cfg, "memory_exhaustion", until=150)
    inc = repo.list_incidents()[0]
    evs = repo.list_events(inc.incident_id)
    times = [e.event_time for e in evs]
    assert times == sorted(times)
    assert any(e.collected_at > e.event_time for e in evs)


def test_timeline_dedup(world, catalog, cfg):
    _, repo, mgr, _ = build(world, catalog, cfg, "redis_outage", until=100)
    inc = repo.list_incidents()[0]
    n = len(repo.list_events(inc.incident_id))
    ev = repo.list_events(inc.incident_id)[0]
    assert mgr.timeline.add(inc.incident_id, ev.event_time, ev.kind, ev.summary, ev.service) is None
    assert len(repo.list_events(inc.incident_id)) == n


def test_state_machine(world, catalog, cfg):
    _, repo, mgr, _ = build(world, catalog, cfg, "redis_outage", until=100)
    iid = repo.list_incidents()[0].incident_id
    with pytest.raises(InvalidTransition):
        mgr.transition(iid, "recovered")
    for s in ("investigating", "diagnosed", "remediating", "verifying"):
        mgr.transition(iid, s)
    inc = mgr.transition(iid, "recovered", outcome="mitigated", root_cause_confirmed=False)
    assert inc.closed_at and inc.outcome == "mitigated"
    mgr.transition(iid, "closed")
    with pytest.raises(InvalidTransition):
        mgr.transition(iid, "investigating")
    assert mgr.audit.chain_valid()


def test_self_recovered_incident_is_swept_closed(world, catalog, cfg):
    data = world("redis_outage").scenario.data
    for k in ("outages",):
        data[k] = []
    # short blip: redis down 60-80 only, everything else healthy again
    data["samples"]["redis"]["cd_service_up"] = [[t, 0 if 60 <= t < 80 else 1] for t, _ in data["samples"]["redis"]["cd_service_up"]]
    for s in ("api", "worker"):
        for dep in ("redis",):
            data["samples"][s][f"dependency_up:{dep}"] = [[t, 1] for t, _ in data["samples"][s][f"dependency_up:{dep}"]]
    data["samples"]["api"]["error_ratio"] = [[t, 0.004] for t, _ in data["samples"]["api"]["error_ratio"]]
    data["samples"]["worker"]["queue_depth"] = [[t, 3] for t in range(0, 401, 5)]
    _, repo, mgr, _ = build(world, catalog, cfg, data)
    inc = repo.list_incidents()[0]
    assert inc.state == "closed" and inc.outcome == "unresolved"


def test_relapse_is_flagged(world, catalog, cfg):
    _, repo, mgr, _ = build(world, catalog, cfg, "memory_exhaustion", until=130)
    inc = repo.list_incidents()[0]
    for s in ("investigating", "diagnosed", "escalated"):
        mgr.transition(inc.incident_id, s) if s != "escalated" else mgr.transition(inc.incident_id, "escalated")
    mgr.transition(inc.incident_id, "closed")
    # second OOM at t=205 within relapse window of closure (clock is at ~130 -> fake: closure time 130)
    w = world("memory_exhaustion")
    clock = mgr.clock
    det, _ = run_detector(w, catalog, cfg, until_s=240, start_s=135, on_poll=lambda t, r: (clock.set(r.at), mgr.ingest(r)))
    flagged = [i for i in repo.list_incidents() if any("relapse" in s for s in i.symptoms)]
    assert flagged
