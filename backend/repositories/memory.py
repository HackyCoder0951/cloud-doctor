"""In-memory repository (default; used by tests, demo replay and the fake-backed API)."""
from __future__ import annotations

import threading
from collections import defaultdict

from backend.domain.canonical import ZERO_HASH
from backend.domain.catalog import Catalog
from backend.domain.models import (Alert, AuditEvent, Decision, Diagnosis, Evidence, Execution, Incident,
                                   Plan, TimelineEvent, Verification)

from .base import Repository, RepositoryError


def _has_nul(obj) -> bool:
    if isinstance(obj, str):
        return "\x00" in obj
    if isinstance(obj, list):
        return any(_has_nul(v) for v in obj)
    if isinstance(obj, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in obj.items())
    return False


class MemoryRepository(Repository):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._inc_seq = 0
        self._counters: dict[str, int] = defaultdict(int)
        self.catalog: Catalog | None = None
        self._incidents: dict[str, Incident] = {}
        self._alerts: dict[tuple[str, str], Alert] = {}
        self._evidence: dict[str, dict[str, Evidence]] = defaultdict(dict)
        self._events: dict[str, dict[str, TimelineEvent]] = defaultdict(dict)
        self._diagnoses: dict[str, list[Diagnosis]] = defaultdict(list)
        self._plans: dict[str, Plan] = {}
        self._decisions: dict[str, Decision] = {}
        self._approvals: dict[str, list[dict]] = defaultdict(list)
        self._executions: dict[str, Execution] = {}
        self._verifications: list[Verification] = []
        self._audit: list[AuditEvent] = []

    def _next(self, key: str, width: int, prefix: str) -> str:
        with self._lock:
            self._counters[key] += 1
            return f"{prefix}{self._counters[key]:0{width}d}"

    def sync_catalog(self, catalog: Catalog) -> None:
        self.catalog = catalog

    # incidents
    def next_incident_id(self) -> str:
        return self._next("inc", 4, "INC-")

    def save_incident(self, incident: Incident) -> None:
        with self._lock:
            self._incidents[incident.incident_id] = incident.model_copy(deep=True)

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._lock:
            i = self._incidents.get(incident_id)
            return i.model_copy(deep=True) if i else None

    def list_incidents(self, state: str | None = None, limit: int = 50) -> list[Incident]:
        with self._lock:
            rows = [i for i in self._incidents.values() if state is None or i.state == state]
            rows.sort(key=lambda i: (i.opened_at, i.incident_id), reverse=True)
            return [i.model_copy(deep=True) for i in rows[:limit]]

    # alerts
    def save_alert(self, alert: Alert) -> None:
        with self._lock:
            self._alerts[(alert.fingerprint, alert.fired_at.isoformat())] = alert.model_copy(deep=True)

    def list_alerts(self, incident_id: str | None = None, service: str | None = None) -> list[Alert]:
        with self._lock:
            rows = [a for a in self._alerts.values()
                    if (incident_id is None or a.incident_id == incident_id) and (service is None or a.service == service)]
            return sorted((a.model_copy(deep=True) for a in rows), key=lambda a: (a.fired_at, a.fingerprint))

    # evidence
    def next_evidence_id(self, incident_id: str) -> str:
        return self._next(f"ev:{incident_id}", 3, "EV-")

    def add_evidence(self, evidence: Evidence) -> None:
        with self._lock:
            if evidence.evidence_id in self._evidence[evidence.incident_id]:
                raise RepositoryError("duplicate evidence id")  # evidence is immutable
            if _has_nul(evidence.payload) or _has_nul(evidence.summary or "") or _has_nul(evidence.query):
                raise RepositoryError("NUL character in evidence (must be stripped before storing)")
            self._evidence[evidence.incident_id][evidence.evidence_id] = evidence.model_copy(deep=True)

    def get_evidence(self, incident_id: str, evidence_id: str) -> Evidence | None:
        with self._lock:
            e = self._evidence[incident_id].get(evidence_id)
            return e.model_copy(deep=True) if e else None

    def list_evidence(self, incident_id: str) -> list[Evidence]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._evidence[incident_id].values()]

    # timeline
    def next_event_id(self, incident_id: str) -> str:
        return self._next(f"tl:{incident_id}", 4, "TL-")

    def add_event(self, event: TimelineEvent) -> None:
        with self._lock:
            self._events[event.incident_id][event.event_id] = event.model_copy(deep=True)

    def list_events(self, incident_id: str) -> list[TimelineEvent]:
        with self._lock:
            rows = list(self._events[incident_id].values())
            rows.sort(key=lambda e: (e.event_time, e.event_id))
            return [e.model_copy(deep=True) for e in rows]

    # diagnoses
    def save_diagnosis(self, diagnosis: Diagnosis) -> None:
        with self._lock:
            self._diagnoses[diagnosis.incident_id].append(diagnosis.model_copy(deep=True))

    def latest_diagnosis(self, incident_id: str) -> Diagnosis | None:
        with self._lock:
            rows = self._diagnoses[incident_id]
            return rows[-1].model_copy(deep=True) if rows else None

    # remediation
    def next_plan_id(self) -> str:
        return self._next("pl", 4, "PL-")

    def save_plan(self, plan: Plan) -> None:
        with self._lock:
            self._plans[plan.plan_id] = plan.model_copy(deep=True)

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._lock:
            p = self._plans.get(plan_id)
            return p.model_copy(deep=True) if p else None

    def list_plans(self, incident_id: str) -> list[Plan]:
        with self._lock:
            return sorted((p.model_copy(deep=True) for p in self._plans.values() if p.incident_id == incident_id),
                          key=lambda p: (p.created_at, p.plan_id))

    def next_decision_id(self) -> str:
        return self._next("dec", 4, "DEC-")

    def save_decision(self, decision: Decision) -> None:
        with self._lock:
            self._decisions[decision.decision_id] = decision.model_copy(deep=True)

    def list_decisions(self, incident_id: str) -> list[Decision]:
        with self._lock:
            plan_ids = {p.plan_id for p in self._plans.values() if p.incident_id == incident_id}
            return sorted((d.model_copy(deep=True) for d in self._decisions.values() if d.plan_id in plan_ids),
                          key=lambda d: (d.decided_at, d.decision_id))

    def save_approval(self, plan_id, plan_hash, approver, decision, reason, decided_at) -> None:
        with self._lock:
            self._approvals[plan_id].append({"plan_id": plan_id, "plan_hash": plan_hash, "approver": approver,
                                             "decision": decision, "reason": reason, "decided_at": decided_at})

    def list_approvals(self, plan_id: str) -> list[dict]:
        with self._lock:
            return list(self._approvals[plan_id])

    def next_execution_id(self) -> str:
        return self._next("ex", 4, "EX-")

    def save_execution(self, execution: Execution) -> None:
        with self._lock:
            self._executions[execution.execution_id] = execution.model_copy(deep=True)

    def list_executions(self, incident_id: str) -> list[Execution]:
        with self._lock:
            plan_ids = {p.plan_id for p in self._plans.values() if p.incident_id == incident_id}
            return sorted((e.model_copy(deep=True) for e in self._executions.values() if e.plan_id in plan_ids),
                          key=lambda e: (e.started_at, e.execution_id))

    def get_execution_by_key(self, idempotency_key: str) -> Execution | None:
        with self._lock:
            for e in self._executions.values():
                if e.idempotency_key == idempotency_key:
                    return e.model_copy(deep=True)
            return None

    def save_verification(self, verification: Verification) -> None:
        with self._lock:
            self._verifications.append(verification.model_copy(deep=True))

    def list_verifications(self, incident_id: str) -> list[Verification]:
        with self._lock:
            return [v.model_copy(deep=True) for v in self._verifications if v.incident_id == incident_id]

    # audit
    def last_audit(self) -> AuditEvent | None:
        with self._lock:
            return self._audit[-1].model_copy(deep=True) if self._audit else None

    def append_audit(self, event: AuditEvent) -> None:
        with self._lock:
            if not self._audit:
                if event.seq != 1 or event.prev_hash != ZERO_HASH:
                    raise RepositoryError("audit chain must start at seq 1 with a zero prev_hash")
            else:
                last = self._audit[-1]
                if event.seq != last.seq + 1 or event.prev_hash != last.hash:
                    raise RepositoryError("audit chain broken")
            self._audit.append(event.model_copy(deep=True))

    def list_audit(self, incident_id: str | None = None, after_seq: int = 0, limit: int = 100) -> list[AuditEvent]:
        with self._lock:
            rows = [e for e in self._audit if e.seq > after_seq and (incident_id is None or e.incident_id == incident_id)]
            return [e.model_copy(deep=True) for e in rows[:limit]]

    def all_audit(self) -> list[AuditEvent]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._audit]
