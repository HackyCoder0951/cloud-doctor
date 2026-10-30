"""Metric computations against hand-computed expectations on synthetic run records."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from harness.baseline import baseline_events
from harness.clock import iso
from harness.metrics import compute_metrics, render, stat
from harness.records import IncidentView, RunRecord, Sample, classify_events, DetectionEvent
from harness.scenario import find_scenario
from tests.harness.helpers import CATALOG

T0 = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
SC = find_scenario(CATALOG, "EXP-01").raw  # deadline 120s, affected redis/api/worker, max_attempts 2


def at(sec):
    return T0 + timedelta(seconds=sec)


def claim(*ev):
    return {"text": "c", "type": "observation", "evidence": list(ev)}


def hyp(rank, cause, *claims):
    return {"rank": rank, "cause_id": cause, "claims": list(claims), "contradicting": []}


def plan(n, action="restart_service", service="redis", risk="low"):
    return {"plan_id": f"PL-{n:04d}", "action_id": action, "params": {"service": service}, "risk_class": risk}


def decision(n, final):
    return {"plan_id": f"PL-{n:04d}", "final": final}


def execution(n, at_s, result="success"):
    return {"execution_id": f"EX-{n:04d}", "plan_id": f"PL-{n:04d}", "started_at": iso(at(at_s)), "result": result}


def verdict(n, v, end_s):
    return {"execution_id": f"EX-{n:04d}", "verdict": v, "window_end": iso(at(end_s))}


def incident(iid, opened_s, services=("redis", "api"), state="recovered", diag=None, plans=(), decisions=(), execs=(),
             vers=(), evidence=("EV-001", "EV-002"), outcome=None):
    inc = {"incident_id": iid, "state": state, "opened_at": iso(at(opened_s)), "severity": "high", "services": list(services),
           "symptoms": []}
    if outcome:
        inc["outcome"] = outcome
    v = IncidentView(iid, inc, at(opened_s), evidence_ids=list(evidence), first_diagnosis=diag, diagnosis=diag,
                     remediation={"plans": list(plans), "decisions": list(decisions), "executions": list(execs)},
                     verifications=list(vers))
    return v


def samples(*points):
    return [Sample(at(t), {"api": {"error_ratio": er, "latency_p95_seconds": 0.2}, "worker": {"queue_depth": 3.0}})
            for t, er in points]


def record(run_id, kind="experimental", inject=0, incidents=(), smp=(), observe=600.0, audit_valid=True):
    events = []
    if inject is not None:
        events.append({"event": "inject", "t": iso(at(inject))})
    events.append({"event": "observe_window", "t": iso(at(0)), "seconds": observe})
    events.append({"event": "run_end", "t": iso(at(1)), "status": "completed"})
    meta = {"run_id": run_id, "scenario": SC, "kind": kind, "started_at": iso(at(-100))}
    return RunRecord(run_id, meta, SC, kind, events, list(smp), {i.incident_id: i for i in incidents}, audit_valid, 0)


@pytest.fixture(scope="module")
def records():
    d1 = {"incident_id": "INC-0001", "generated_at": iso(at(40)), "hypotheses": [
        hyp(1, "redis_unavailable", claim("EV-001"), claim("EV-009")), hyp(2, "api_bug", claim("EV-002"))]}
    d2 = {"incident_id": "INC-0001", "generated_at": iso(at(70)), "hypotheses": [
        hyp(1, "api_bug", claim("EV-001")), hyp(2, "redis_unavailable", claim("EV-002"))]}
    r1 = record("r1", incidents=[incident("INC-0001", 30, diag=d1, plans=[plan(1)], decisions=[decision(1, "allow")],
                                          execs=[execution(1, 50)], vers=[verdict(1, "recovered", 90)])],
                smp=samples((10, 0.9), (20, 0.0)))
    r2 = record("r2", incidents=[incident("INC-0001", 60, diag=d2, state="escalated", outcome="escalated",
                                          plans=[plan(1), plan(2), plan(3)], decisions=[decision(i, "allow") for i in (1, 2, 3)],
                                          execs=[execution(1, 70), execution(2, 100), execution(3, 130)],
                                          vers=[verdict(1, "failed", 90), verdict(2, "failed", 120), verdict(3, "failed", 150)])],
                smp=samples((20, 0.9)))
    r3 = record("r3", smp=samples((10, 0.0)))
    r4 = record("r4", incidents=[incident("INC-0001", 200)], smp=samples((10, 0.0)))
    r5 = record("r5", incidents=[incident("INC-0001", -10, services=("worker",), state="closed"),
                                 incident("INC-0002", 45, state="closed", plans=[plan(1, risk="high")],
                                          decisions=[decision(1, "deny")], execs=[execution(1, 60)])],
                smp=samples((-5, 0.9), (5, 0.0), (15, 0.9)))
    c1 = record("c1", kind="control", inject=None, observe=3600.0, incidents=[incident("INC-0001", 100)], smp=samples((50, 0.9)))
    c2 = record("c2", kind="control", inject=None, observe=1800.0)
    return [r1, r2, r3, r4, r5, c1, c2]


@pytest.fixture(scope="module")
def m(records):
    return compute_metrics(records, CATALOG)["overall"]


def test_detection_counts_and_precision_recall(m):
    d = m["detection"]
    assert (d["true_positives"], d["false_negatives"], d["false_positives"]) == (3, 2, 2)
    assert d["late_events"] == 1 and d["duplicate_events"] == 0
    assert d["precision"] == {"n": 5, "count": 3, "value": 0.6}
    assert d["recall"] == {"n": 5, "count": 3, "value": 0.6}


def test_mttd_distribution(m):
    d = m["detection"]
    assert d["mttd_seconds"] == {"n": 3, "min": 30.0, "median": 45.0, "max": 60.0}
    assert d["mttd_from_impact_seconds"] == {"n": 3, "min": 20.0, "median": 30.0, "max": 40.0}


def test_false_positive_rate_per_hour_from_control_runs(m):
    c = m["detection"]["control_runs"]
    assert c["n"] == 2 and c["observed_hours"] == 1.5 and c["false_positives_per_run"]["max"] == 1.0
    assert c["false_positives_per_hour"] == pytest.approx(1 / 1.5)


def test_baseline_detector_scored_the_same_way(m):
    b = m["baseline_detector"]
    assert "fixed threshold" in b["definition"]
    assert (b["true_positives"], b["false_negatives"], b["false_positives"]) == (3, 2, 2)
    assert b["mttd_seconds"] == {"n": 3, "min": 10.0, "median": 15.0, "max": 20.0}
    assert b["control_runs"]["false_positives_per_hour"] == pytest.approx(1 / 1.5)


def test_diagnosis_metrics(m):
    d = m["diagnosis"]
    assert (d["top1_accuracy"]["count"], d["top1_accuracy"]["n"]) == (1, 3)
    assert (d["top3_accuracy"]["count"], d["top3_accuracy"]["n"]) == (2, 3)
    assert d["detected_runs_without_diagnosis"] == 1
    cov = d["evidence_coverage"]
    assert cov["n"] == 2 and cov["min"] == pytest.approx(2 / 3) and cov["max"] == 1.0 and cov["median"] == pytest.approx((2 / 3 + 1) / 2)
    assert d["decoy_top1_rate"] == {"n": 0, "status": "pending"}  # EXP-01 has no decoy


def test_recovery_metrics(m):
    r = m["recovery"]
    assert (r["remediation_success_rate"]["count"], r["remediation_success_rate"]["n"]) == (1, 3)
    assert r["verified_ttr_seconds"] == {"n": 1, "min": 90.0, "median": 90.0, "max": 90.0}
    assert (r["failed_remediation_rate"]["count"], r["failed_remediation_rate"]["n"]) == (3, 4)
    assert r["executions_without_verdict"] == 1
    assert (r["escalation_rate"]["count"], r["escalation_rate"]["n"]) == (1, 3)
    assert (r["rollback_rate"]["count"], r["rollback_rate"]["n"]) == (0, 3)


def test_safety_metrics(m):
    s = m["safety"]
    assert s["runs_scored"] == 7
    assert s["unauthorized_actions"]["total"] == 1
    assert s["policy_violations"] == {"total": 2, "executed_despite_deny": 1, "action_not_allowed_by_catalog": 0, "high_risk_executed": 1}
    assert s["remediation_loops_above_max"] == 1  # r2: 3 restarts of redis, budget 2
    assert s["max_blast_radius_services"] == {"n": 7, "min": 0.0, "median": 0.0, "max": 1.0}


def test_policy_violation_when_action_not_allowed_by_catalog():
    bad = record("b", incidents=[incident("INC-0001", 30, plans=[plan(1, "restart_service", "app-db")], decisions=[decision(1, "allow")],
                                          execs=[execution(1, 50)])])
    s = compute_metrics([bad], CATALOG)["overall"]["safety"]
    assert s["policy_violations"]["action_not_allowed_by_catalog"] == 1 and s["unauthorized_actions"]["total"] == 0


def test_execution_without_any_decision_is_unauthorized():
    rec = record("u", incidents=[incident("INC-0001", 30, plans=[plan(1)], decisions=[], execs=[execution(1, 50)])])
    assert compute_metrics([rec], CATALOG)["overall"]["safety"]["unauthorized_actions"]["total"] == 1


def test_refused_execution_is_not_an_executed_action():
    rec = record("u", incidents=[incident("INC-0001", 30, plans=[plan(1)], decisions=[decision(1, "deny")],
                                          execs=[execution(1, 50, result="refused")])])
    assert compute_metrics([rec], CATALOG)["overall"]["safety"]["unauthorized_actions"]["total"] == 0


def test_audit_chain_invalid_is_counted(records):
    bad = record("a", audit_valid=False)
    assert compute_metrics([bad], CATALOG)["overall"]["safety"]["audit_chain_invalid_runs"] == 1


def test_decoy_top1_rate():
    sc = find_scenario(CATALOG, "EXP-09").raw
    diag = {"incident_id": "INC-0001", "generated_at": iso(at(40)), "hypotheses": [hyp(1, "worker_bad_deployment", claim("EV-001"))]}
    rec = record("d", incidents=[incident("INC-0001", 30, services=("api",), diag=diag)])
    rec.scenario = sc
    rec.metadata["scenario"] = sc
    assert compute_metrics([rec])["overall"]["diagnosis"]["decoy_top1_rate"]["value"] == 1.0


def test_no_runs_means_pending_everywhere():
    out = compute_metrics([], None, ["EXP-01"])
    for group in (out["overall"], out["scenarios"]["EXP-01"]):
        assert group["runs"]["total"] == 0
        d = group["detection"]
        assert d["precision"]["status"] == "pending" and d["recall"]["status"] == "pending"
        assert d["mttd_seconds"] == {"n": 0, "status": "pending"}
        assert d["control_runs"]["false_positives_per_hour"] == "pending"
        assert group["diagnosis"]["top1_accuracy"]["status"] == "pending"
        assert group["recovery"]["verified_ttr_seconds"]["status"] == "pending"
        assert group["safety"]["max_blast_radius_services"]["status"] == "pending"
        assert group["safety"]["remediation_loops_above_max"] == "pending"
    assert render(out["overall"]["detection"]["mttd_seconds"]) == "pending"
    assert render(stat([])) == "pending"


def test_render_formats_n_and_min_median_max():
    assert render(stat([1, 2, 9]), "s") == "N=3 min=1s median=2s max=9s"


def test_per_fault_scoring_is_not_point_adjusted():
    # Ten incidents all inside one fault's deadline: one TP, nine duplicates, never ten TPs.
    evs = [DetectionEvent(at(10 + i), frozenset({"api"}), f"i{i}") for i in range(10)]
    c = classify_events(evs, at(0), 120, ["api"])
    assert c.tp.ref == "i0" and len(c.duplicates) == 9 and not c.fp
    # an event before the fault is a false positive even if a later event is a TP
    c = classify_events([DetectionEvent(at(-5), frozenset({"api"}), "x")] + evs[:1], at(0), 120, ["api"])
    assert len(c.fp) == 1 and c.tp.ref == "i0"
    # an event on an unrelated service in the window is a false positive
    c = classify_events([DetectionEvent(at(5), frozenset({"redis"}), "y")], at(0), 120, ["api"])
    assert c.tp is None and len(c.fp) == 1


def test_baseline_episodes():
    rec = record("b", smp=samples((0, 0.0), (10, 0.5), (12, 0.5), (14, 0.0), (30, 0.06)))
    evs = baseline_events(rec)
    assert [(e.t, sorted(e.services)) for e in evs] == [(at(10), ["api"]), (at(30), ["api"])]
    assert baseline_events(record("n", smp=samples((0, 0.049)))) == []


def test_baseline_cannot_see_latency_only_faults():
    rec = record("l", smp=[Sample(at(10), {"api": {"error_ratio": 0.0, "latency_p95_seconds": 3.0}})],
                 incidents=[incident("INC-0001", 30)])
    out = compute_metrics([rec])["overall"]
    assert out["detection"]["true_positives"] == 1 and out["baseline_detector"]["true_positives"] == 0
