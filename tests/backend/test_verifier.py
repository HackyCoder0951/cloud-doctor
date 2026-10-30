import pytest
from stack import build

from backend.domain.contracts import validate_against_contract


def prepared(world, catalog, cfg, data, at=140):
    s = build(world, catalog, cfg, data)
    s.poll_until(at)
    iid = s.incident().incident_id
    s.eng.diagnose(iid)
    s.col.snapshot_before_action(iid)
    return s, iid


def verify(s, iid, **kw):
    inc = s.repo.get_incident(iid)
    v = s.ver.verify(iid, "EX-0001", list(inc.services), s.clock.now(), **kw)
    validate_against_contract(v.to_contract(), "verification")
    return v


def data(world, name="redis_outage_recovered"):
    return world(name).scenario.data


def test_recovered_all_seven_checks_pass(world, catalog, cfg):
    s, iid = prepared(world, catalog, cfg, "redis_outage_recovered")
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict == "recovered" and len(v.checks) == 7 and all(c.passed for c in v.checks)
    syn = [c for c in v.checks if c.name == "synthetic_transaction"][0]
    assert syn.post_action == 1.0


def test_partial_when_service_back_but_sli_not_yet_ok(world, catalog, cfg):
    d = data(world)
    d["samples"]["api"]["error_ratio"] = [[t, 0.3 if t >= 142 else v] for t, v in d["samples"]["api"]["error_ratio"]]
    s, iid = prepared(world, catalog, cfg, d)
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict == "partial"
    e = [c for c in v.checks if c.name == "error_sli"][0]
    assert e.passed is False and e.post_action < e.pre_action


def test_failed_when_nothing_improves(world, catalog, cfg):
    s, iid = prepared(world, catalog, cfg, "redis_outage")
    v = verify(s, iid)
    assert v.verdict == "failed"
    assert [c.passed for c in v.checks if c.name in ("readiness", "error_sli")] == [False, False]


def test_regression_in_another_service(world, catalog, cfg):
    d = data(world)
    d["samples"]["loadgen"]["up"] = [[t, 0 if t >= 150 else 1] for t, _ in d["samples"]["loadgen"]["up"]]
    s, iid = prepared(world, catalog, cfg, d)
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict == "regression" and [c for c in v.checks if c.name == "no_regression"][0].passed is False


def test_unverifiable_when_traffic_too_low_to_establish_sli(world, catalog, cfg):
    d = data(world)
    d["samples"]["api"]["request_rate"] = [[t, 0.3 if t >= 142 else v] for t, v in d["samples"]["api"]["request_rate"]]
    s, iid = prepared(world, catalog, cfg, d)
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict == "unverifiable"
    assert [c.passed for c in v.checks if c.name in ("error_sli", "latency_sli")] == [None, None]


def test_unverifiable_when_probe_cannot_be_established(world, catalog, cfg):
    d = data(world)
    d["outages"].append({"from_s": 175, "to_s": 300, "mode": "timeout", "signal": "probe"})
    s, iid = prepared(world, catalog, cfg, d)
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict == "unverifiable" and [c for c in v.checks if c.name == "synthetic_transaction"][0].passed is None


def test_failed_probe_blocks_recovery(world, catalog, cfg):
    d = data(world)
    d["probes"] = {"api": [{"from_s": 180, "to_s": 190, "ok": False}]}
    s, iid = prepared(world, catalog, cfg, d)
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict != "recovered" and [c for c in v.checks if c.name == "synthetic_transaction"][0].passed is False


def test_relapse_after_earlier_recovery(world, catalog, cfg):
    s, iid = prepared(world, catalog, cfg, "redis_outage")
    v = verify(s, iid, prior_recovered=True)
    assert v.verdict == "relapse"


def test_telemetry_gap_inside_window_is_not_fresh(world, catalog, cfg):
    d = data(world)
    d["samples"]["redis"]["up"] = [[t, v] for t, v in d["samples"]["redis"]["up"] if not 180 <= t < 190]
    s, iid = prepared(world, catalog, cfg, d)
    s.clock.set(s.world.scenario.at(160))
    v = verify(s, iid)
    assert v.verdict in ("unverifiable", "failed") and v.verdict != "recovered"
    assert [c for c in v.checks if c.name == "telemetry_fresh"][0].passed is False
