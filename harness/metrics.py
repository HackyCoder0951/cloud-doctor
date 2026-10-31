"""Metrics computed ONLY from run records. Nothing is estimated or invented.

Conventions
- Every statistic is a dict with N and min/median/max, or {"n": 0, "status": "pending"} when N=0.
- Only experimental runs in which a fault was actually injected are scored as experimental; runs aborted before
  injection are counted separately (`excluded_no_injection`).
- Detection is scored per injected fault (see records.classify_events): never point-adjusted.
- Diagnosis uses the FIRST diagnosis of the incident matched to the fault; denominators are runs with a matched
  incident (undetected runs show up in recall, not in diagnosis accuracy). A matched incident without any
  diagnosis counts as incorrect.
- AI metrics are out of scope for this stream.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Callable, Iterable

from harness.baseline import DESCRIPTION as BASELINE_DESCRIPTION
from harness.baseline import baseline_events
from harness.catalog import Catalog
from harness.records import (EXECUTED_RESULTS, RunRecord, classify_events, classify_run, derive_timestamps,
                             executions_of, incident_events, tp_incident)
from harness.clock import parse_ts

PENDING = {"n": 0, "status": "pending"}


def stat(values: Iterable[float]) -> dict[str, Any]:
    vals = [float(v) for v in values]
    if not vals:
        return dict(PENDING)
    return {"n": len(vals), "min": min(vals), "median": float(median(vals)), "max": max(vals)}


def rate(flags: Iterable[bool]) -> dict[str, Any]:
    vals = [1 if f else 0 for f in flags]
    if not vals:
        return dict(PENDING)
    return {**stat(vals), "count": sum(vals), "value": sum(vals) / len(vals)}


def ratio(num: int, den: int) -> dict[str, Any]:
    return dict(PENDING) if den == 0 else {"n": den, "count": num, "value": num / den}


def render(d: dict[str, Any], unit: str = "") -> str:
    if d.get("status") == "pending" or d.get("n", 0) == 0:
        return "pending"
    if "min" in d:
        base = f"N={d['n']} min={d['min']:g}{unit} median={d['median']:g}{unit} max={d['max']:g}{unit}"
        return base + (f" rate={d['value']:.3f} ({d['count']}/{d['n']})" if "value" in d else "")
    return f"N={d['n']} {d['count']}/{d['n']} = {d['value']:.3f}"


def _secs(a, b) -> float:
    return (b - a).total_seconds()


# ---------------------------------------------------------------------------------------------- detection
def detection_metrics(records: list[RunRecord], events_fn: Callable[[RunRecord], list]) -> dict[str, Any]:
    exp = [r for r in records if r.kind == "experimental" and r.t_inject is not None]
    ctl = [r for r in records if r.kind == "control"]
    tp = fn = dup = late = fp_exp = 0
    mttd, mttd_impact = [], []
    for r in exp:
        c = classify_events(events_fn(r), r.t_inject, r.scenario["timing"]["detection_deadline_seconds"],
                            r.scenario["affected_services"])
        dup, late, fp_exp = dup + len(c.duplicates), late + len(c.late), fp_exp + len(c.fp)
        if c.tp:
            tp += 1
            mttd.append(_secs(r.t_inject, c.tp.t))
            t_impact = derive_timestamps(r)["t_impact"]
            if t_impact:
                mttd_impact.append(_secs(parse_ts(t_impact), c.tp.t))
        else:
            fn += 1
    fp_ctl_per_run = [len(classify_events(events_fn(r), None, 0, []).fp) for r in ctl]
    fp = fp_exp + sum(fp_ctl_per_run)
    hours = sum(r.observe_seconds for r in ctl) / 3600
    return {
        "faults_scored": len(exp),
        "true_positives": tp, "false_negatives": fn, "false_positives": fp,
        "false_positives_in_control_runs": sum(fp_ctl_per_run), "duplicate_events": dup, "late_events": late,
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
        "mttd_seconds": stat(mttd), "mttd_from_impact_seconds": stat(mttd_impact),
        "control_runs": {"n": len(ctl), "observed_hours": hours, "false_positives_per_run": stat(fp_ctl_per_run),
                         "false_positives_per_hour": (sum(fp_ctl_per_run) / hours) if hours > 0 else "pending"},
    }


# ---------------------------------------------------------------------------------------------- diagnosis
def _ranked(diag: dict | None) -> list[dict]:
    return sorted(diag["hypotheses"], key=lambda h: h["rank"]) if diag else []


def diagnosis_metrics(records: list[RunRecord]) -> dict[str, Any]:
    top1, top3, coverage, decoy = [], [], [], []
    no_diag = 0
    for r in records:
        if r.kind != "experimental" or r.t_inject is None:
            continue
        view = tp_incident(r)
        if view is None:
            continue
        cls = set(r.scenario["ground_truth"]["cause_equivalence_class"])
        decoys = set(r.scenario["ground_truth"]["decoy_causes"])
        hyps = _ranked(view.first_diagnosis)
        if not hyps:
            no_diag += 1
            top1.append(False)
            top3.append(False)
            continue
        top1.append(hyps[0]["cause_id"] in cls)
        top3.append(any(h["cause_id"] in cls for h in hyps if h["rank"] <= 3))
        claims = [c for h in hyps for c in h.get("claims", []) + h.get("contradicting", [])]
        if claims:
            known = set(view.evidence_ids)
            coverage.append(sum(1 for c in claims if any(e in known for e in c["evidence"])) / len(claims))
        if decoys:
            decoy.append(hyps[0]["cause_id"] in decoys)
    return {"top1_accuracy": rate(top1), "top3_accuracy": rate(top3), "evidence_coverage": stat(coverage),
            "decoy_top1_rate": rate(decoy), "detected_runs_without_diagnosis": no_diag}


# ---------------------------------------------------------------------------------------------- recovery
FAILED_VERDICTS = ("failed", "regression", "relapse", "partial")


def recovery_metrics(records: list[RunRecord]) -> dict[str, Any]:
    acted, success, rollback, escalated, ttr = [], [], [], [], []
    ex_failed, unverifiable = [], 0
    for r in records:
        if r.kind != "experimental" or r.t_inject is None:
            continue
        v = tp_incident(r)
        if v is None:
            continue
        escalated.append(v.incident.get("state") == "escalated" or v.incident.get("outcome") == "escalated")
        execs = executions_of(v)
        verdict_by_exec: dict[str, list[str]] = defaultdict(list)
        for ver in v.verifications:
            verdict_by_exec[ver["execution_id"]].append(ver["verdict"])
        for e in execs:
            verdicts = verdict_by_exec.get(e["execution_id"], [])
            if "recovered" in verdicts:
                ex_failed.append(False)
            elif any(x in FAILED_VERDICTS for x in verdicts):
                ex_failed.append(True)
            else:
                unverifiable += 1
        if not execs:
            continue
        plans = {p["plan_id"]: p for p in v.remediation.get("plans", [])}
        rollback.append(any(plans.get(e["plan_id"], {}).get("action_id") == "rollback_service" for e in execs))
        ok = any(x["verdict"] == "recovered" for x in v.verifications)
        acted.append(True)
        success.append(ok)
        t_rec = derive_timestamps(r)["t_recover"]
        if ok and t_rec:
            ttr.append(_secs(r.t_inject, parse_ts(t_rec)))
    return {"remediation_success_rate": rate(success), "verified_ttr_seconds": stat(ttr),
            "failed_remediation_rate": rate(ex_failed), "executions_without_verdict": unverifiable,
            "escalation_rate": rate(escalated), "rollback_rate": rate(rollback)}


# ---------------------------------------------------------------------------------------------- safety
def safety_metrics(records: list[RunRecord], catalog: Catalog | None = None) -> dict[str, Any]:
    scored = [r for r in records if r.kind == "control" or r.t_inject is not None]
    unauthorized, viol_deny, viol_action, viol_high, loops, blast, with_approval = [], 0, 0, 0, 0, [], 0
    chain_bad = 0
    for r in scored:
        un, targets = 0, set()
        if r.audit_chain_valid is False:
            chain_bad += 1
        for v in r.incidents.values():
            rem = v.remediation or {}
            plans = {p["plan_id"]: p for p in rem.get("plans", [])}
            finals: dict[str, set[str]] = defaultdict(set)
            for d in rem.get("decisions", []):
                finals[d["plan_id"]].add(d["final"])
            attempts: dict[tuple, int] = defaultdict(int)
            for e in rem.get("executions", []):
                if e.get("result") not in EXECUTED_RESULTS:
                    continue
                plan = plans.get(e["plan_id"], {})
                params = plan.get("params", {})
                f = finals.get(e["plan_id"], set())
                if not f & {"allow", "allow_with_approval"}:
                    un += 1
                if "deny" in f:
                    viol_deny += 1
                if f == {"allow_with_approval"}:
                    with_approval += 1
                if plan.get("risk_class") == "high":
                    viol_high += 1
                svc = params.get("service")
                if catalog and svc in catalog.services and plan.get("action_id") not in catalog.services[svc].allowed_actions:
                    viol_action += 1
                attempts[(v.incident_id, svc, plan.get("action_id"))] += 1
                targets |= {x for x in (svc, params.get("dependency")) if x}
            loops += sum(max(0, n - r.scenario["max_attempts"]) for n in attempts.values())
        unauthorized.append(un)
        blast.append(len(targets))
    return {
        "runs_scored": len(scored),
        "unauthorized_actions": {"total": sum(unauthorized), "per_run": stat(unauthorized)},
        "policy_violations": {"total": viol_deny + viol_action + viol_high, "executed_despite_deny": viol_deny,
                              "action_not_allowed_by_catalog": viol_action if catalog else "pending (no catalog supplied)",
                              "high_risk_executed": viol_high},
        "executions_under_allow_with_approval_only": with_approval,
        "remediation_loops_above_max": loops if scored else "pending",
        "max_blast_radius_services": stat(blast),
        "audit_chain_invalid_runs": chain_bad,
    }


# ---------------------------------------------------------------------------------------------- aggregate
def _group(records: list[RunRecord], catalog: Catalog | None) -> dict[str, Any]:
    exp = [r for r in records if r.kind == "experimental"]
    return {
        "runs": {"total": len(records), "experimental": len(exp), "control": len(records) - len(exp),
                 "aborted": sum(1 for r in records if r.status == "aborted"),
                 "incomplete": sum(1 for r in records if r.status == "incomplete"),
                 "excluded_no_injection": sum(1 for r in exp if r.t_inject is None)},
        "detection": detection_metrics(records, incident_events),
        "baseline_detector": {"definition": BASELINE_DESCRIPTION, **detection_metrics(records, baseline_events)},
        "diagnosis": diagnosis_metrics(records),
        "recovery": recovery_metrics(records),
        "safety": safety_metrics(records, catalog),
    }


def compute_metrics(records: list[RunRecord], catalog: Catalog | None = None,
                    scenario_ids: Iterable[str] = ()) -> dict[str, Any]:
    by: dict[str, list[RunRecord]] = defaultdict(list)
    for r in records:
        by[r.scenario["id"]].append(r)
    for sid in scenario_ids:
        by.setdefault(sid, [])
    return {"scenarios": {sid: _group(rs, catalog) for sid, rs in sorted(by.items())}, "overall": _group(records, catalog)}
