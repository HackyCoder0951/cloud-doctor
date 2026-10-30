"""Shared builders for the Stream C tests (no Docker, no network)."""
import copy
from datetime import datetime, timedelta, timezone

import invariants as inv

NOW = datetime(2026, 11, 2, 9, 1, 0, tzinfo=timezone.utc)

CATALOG_DICT = {
    "catalog_version": 1, "environment": "sandbox", "network": "cd_sandbox",
    "sandbox_label": "cloud-doctor.sandbox=true",
    "services": [
        {"name": "loadgen", "kind": "load_generator", "container": "cd-loadgen",
         "depends_on": [{"service": "api", "kind": "hard"}], "health": {"liveness": "/healthz"},
         "allowed_actions": ["escalate"]},
        {"name": "api", "kind": "app", "container": "cd-api",
         "depends_on": [{"service": "redis", "kind": "hard"}, {"service": "app-db", "kind": "hard"}],
         "health": {"liveness": "/healthz"}, "allowed_actions": ["restart_service", "rollback_service", "escalate"]},
        {"name": "worker", "kind": "queue_worker", "container": "cd-worker",
         "depends_on": [{"service": "redis", "kind": "hard"}, {"service": "app-db", "kind": "hard"}],
         "health": {"liveness": "/healthz"}, "allowed_actions": ["restart_service", "escalate"]},
        {"name": "redis", "kind": "cache", "container": "cd-redis", "depends_on": [],
         "health": {"liveness": "tcp:6379"}, "allowed_actions": ["restart_service", "clear_cache", "escalate"]},
        {"name": "app-db", "kind": "database", "container": "cd-app-db", "depends_on": [],
         "health": {"liveness": "tcp:5432"}, "allowed_actions": ["escalate"]},
    ],
}


def catalog():
    return inv.Catalog.from_dict(copy.deepcopy(CATALOG_DICT))


def make_plan(action="restart_service", params=None, risk="low", **over):
    plan = {
        "plan_id": "PL-0001", "incident_id": "INC-0001", "action_id": action,
        "params": params if params is not None else {"service": "api"}, "risk_class": risk,
        "origin": "rule", "evidence_refs": ["EV-001", "EV-003"],
        "rationale": "catalogue remedy", "created_at": "2026-11-02T09:00:27Z",
    }
    plan.update(over)
    plan.pop("plan_hash", None)
    plan["plan_hash"] = inv.plan_hash(plan)
    return plan


def rehash(plan):
    plan = dict(plan)
    plan.pop("plan_hash", None)
    plan["plan_hash"] = inv.plan_hash(plan)
    return plan


def make_ctx(**over):
    cat = over.pop("catalog", None) or catalog()
    ctx = inv.PolicyContext(
        catalog=cat, now=NOW,
        attempts_used=lambda i, s, a: 0, last_attempt_at=lambda i, s, a: None,
        circuit_open=lambda i: False, known_evidence_ids={"EV-001", "EV-002", "EV-003"},
        diagnosis_validated=True, top_cause_service=None, approval=None,
        container_labels=lambda c: {"cloud-doctor.sandbox": "true"},
    )
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


def approval_for(plan, **over):
    a = {"approver": "operator-1", "approved_at": "2026-11-02T09:00:50Z", "plan_hash": plan["plan_hash"]}
    a.update(over)
    return a


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
