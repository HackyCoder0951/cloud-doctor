"""PostgreSQL repository (SQLAlchemy 2.x Core, sync). Tables mirror contracts/db/schema.sql exactly.

Schema creation is NOT done here: the frozen contracts/db/schema.sql is the migration (Alembic 0001 in
meaning). ``apply_contract_schema`` loads that file verbatim for tests / local setups.
Id allocation uses incident_seq for incidents and max()+1 elsewhere (collisions fail on the primary key).
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.domain.canonical import strip_nul
from backend.domain.catalog import Catalog
from backend.domain.contracts import REPO_ROOT
from backend.domain.models import (Alert, AuditEvent, Decision, Diagnosis, Evidence, Execution, Incident,
                                   Plan, TimelineEvent, Verification)

from .base import Repository, RepositoryError

md = sa.MetaData()
TS = sa.TIMESTAMP(timezone=True)
Text = sa.Text
TA = ARRAY(sa.Text)

services = sa.Table("services", md, sa.Column("name", Text, primary_key=True), sa.Column("kind", Text), sa.Column("container", Text))
service_dependencies = sa.Table("service_dependencies", md, sa.Column("service", Text, primary_key=True),
                                sa.Column("depends_on", Text, primary_key=True), sa.Column("kind", Text))
incidents = sa.Table("incidents", md, sa.Column("incident_id", Text, primary_key=True), sa.Column("state", Text),
                     sa.Column("severity", Text), sa.Column("opened_at", TS), sa.Column("closed_at", TS),
                     sa.Column("services", TA), sa.Column("symptoms", TA), sa.Column("outcome", Text),
                     sa.Column("root_cause_confirmed", sa.Boolean), sa.Column("run_id", Text))
alerts = sa.Table("alerts", md, sa.Column("alert_id", sa.BigInteger, primary_key=True, autoincrement=True),
                  sa.Column("incident_id", Text), sa.Column("service", Text), sa.Column("rule", Text),
                  sa.Column("state", Text), sa.Column("fired_at", TS), sa.Column("resolved_at", TS), sa.Column("fingerprint", Text))
evidence = sa.Table("evidence", md, sa.Column("incident_id", Text, primary_key=True), sa.Column("evidence_id", Text, primary_key=True),
                    sa.Column("source", Text), sa.Column("type", Text), sa.Column("service", Text), sa.Column("observed_at", TS),
                    sa.Column("collected_at", TS), sa.Column("query", Text), sa.Column("status", Text),
                    sa.Column("missing_signal_state", Text), sa.Column("summary", Text), sa.Column("payload", JSONB),
                    sa.Column("payload_hash", Text), sa.Column("untrusted", sa.Boolean))
timeline_events = sa.Table("timeline_events", md, sa.Column("event_id", Text, primary_key=True), sa.Column("incident_id", Text, primary_key=True),
                           sa.Column("event_time", TS), sa.Column("collected_at", TS), sa.Column("kind", Text), sa.Column("service", Text),
                           sa.Column("summary", Text), sa.Column("evidence_refs", TA), sa.Column("suppressed", sa.Boolean))
hypotheses = sa.Table("hypotheses", md, sa.Column("incident_id", Text, primary_key=True), sa.Column("rank", sa.Integer, primary_key=True),
                      sa.Column("generated_at", TS, primary_key=True), sa.Column("cause_id", Text), sa.Column("service", Text),
                      sa.Column("description", Text), sa.Column("confidence", sa.Float), sa.Column("status", Text),
                      sa.Column("origin", Text), sa.Column("body", JSONB))
plans = sa.Table("plans", md, sa.Column("plan_id", Text, primary_key=True), sa.Column("incident_id", Text), sa.Column("action_id", Text),
                 sa.Column("params", JSONB), sa.Column("risk_class", Text), sa.Column("origin", Text), sa.Column("evidence_refs", TA),
                 sa.Column("rationale", Text), sa.Column("plan_hash", Text), sa.Column("created_at", TS))
policy_decisions = sa.Table("policy_decisions", md, sa.Column("decision_id", Text, primary_key=True), sa.Column("plan_id", Text),
                            sa.Column("plan_hash", Text), sa.Column("l1", JSONB), sa.Column("l2", JSONB), sa.Column("final", Text),
                            sa.Column("reasons", TA), sa.Column("invariants_version", Text), sa.Column("decided_at", TS))
approvals = sa.Table("approvals", md, sa.Column("plan_id", Text, primary_key=True), sa.Column("decided_at", TS, primary_key=True),
                     sa.Column("plan_hash", Text), sa.Column("approver", Text), sa.Column("decision", Text), sa.Column("reason", Text))
executions = sa.Table("executions", md, sa.Column("execution_id", Text, primary_key=True), sa.Column("plan_id", Text),
                      sa.Column("idempotency_key", Text), sa.Column("started_at", TS), sa.Column("ended_at", TS), sa.Column("result", Text),
                      sa.Column("refusal_rule_ids", TA), sa.Column("executed_argv", TA), sa.Column("detail", Text))
verifications = sa.Table("verifications", md, sa.Column("verification_id", sa.BigInteger, primary_key=True, autoincrement=True),
                         sa.Column("incident_id", Text), sa.Column("execution_id", Text), sa.Column("verdict", Text),
                         sa.Column("window_start", TS), sa.Column("window_end", TS), sa.Column("checks", JSONB))
audit_log = sa.Table("audit_log", md, sa.Column("seq", sa.BigInteger, primary_key=True), sa.Column("incident_id", Text), sa.Column("actor", Text),
                     sa.Column("event", Text), sa.Column("detail", JSONB), sa.Column("prev_hash", Text), sa.Column("hash", Text),
                     sa.Column("created_at", TS))


def apply_contract_schema(engine: sa.Engine) -> None:
    """Execute the frozen contracts/db/schema.sql verbatim (tests / local bootstrap only)."""
    sql = (REPO_ROOT / "contracts/db/schema.sql").read_text()
    raw = engine.raw_connection()  # raw DBAPI: the script contains '%' (RAISE formats) that must not be treated as params
    try:
        cur = raw.cursor()
        cur.execute(sql)
        raw.commit()
    finally:
        raw.close()


def _iso_dt(v) -> datetime:
    return v


class SqlRepository(Repository):
    def __init__(self, url: str) -> None:
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = sa.create_engine(url, pool_pre_ping=True, future=True)

    # helpers
    def _one(self, stmt):
        with self.engine.connect() as c:
            return c.execute(stmt).mappings().first()

    def _all(self, stmt):
        with self.engine.connect() as c:
            return list(c.execute(stmt).mappings())

    def _exec(self, stmt):
        try:
            with self.engine.begin() as c:
                return c.execute(stmt)
        except sa.exc.SQLAlchemyError as exc:
            raise RepositoryError(type(exc).__name__) from exc  # no SQL text / params leak upward

    def _next_max(self, table: sa.Table, col: str, prefix: str, width: int, where=None) -> str:
        expr = sa.func.coalesce(sa.func.max(sa.cast(sa.func.substr(table.c[col], len(prefix) + 1), sa.Integer)), 0)
        q = sa.select(expr)
        if where is not None:
            q = q.where(where)
        n = self._one(q)
        return f"{prefix}{list(n.values())[0] + 1:0{width}d}"

    def _upsert(self, table: sa.Table, row: dict, keys: list[str]) -> None:
        stmt = pg_insert(table).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=keys, set_={k: v for k, v in row.items() if k not in keys})
        self._exec(stmt)

    # catalog
    def sync_catalog(self, catalog: Catalog) -> None:
        with self.engine.begin() as c:
            for s in catalog.services.values():
                c.execute(pg_insert(services).values(name=s.name, kind=s.kind, container=s.container).on_conflict_do_nothing())
            for a, b, k in catalog.edges():
                c.execute(pg_insert(service_dependencies).values(service=a, depends_on=b, kind=k).on_conflict_do_nothing())

    # incidents
    def next_incident_id(self) -> str:
        with self.engine.begin() as c:
            return f"INC-{c.execute(sa.text('SELECT nextval(\'incident_seq\')')).scalar_one():04d}"

    def save_incident(self, i: Incident) -> None:
        self._upsert(incidents, dict(incident_id=i.incident_id, state=i.state, severity=i.severity, opened_at=i.opened_at,
                                     closed_at=i.closed_at, services=list(i.services), symptoms=list(i.symptoms), outcome=i.outcome,
                                     root_cause_confirmed=i.root_cause_confirmed, run_id=i.run_id), ["incident_id"])

    @staticmethod
    def _inc(r) -> Incident:
        return Incident(incident_id=r["incident_id"], state=r["state"], severity=r["severity"], opened_at=r["opened_at"],
                        closed_at=r["closed_at"], services=r["services"], symptoms=r["symptoms"] or [], outcome=r["outcome"],
                        root_cause_confirmed=r["root_cause_confirmed"], run_id=r["run_id"])

    def get_incident(self, incident_id: str) -> Incident | None:
        r = self._one(sa.select(incidents).where(incidents.c.incident_id == incident_id))
        return self._inc(r) if r else None

    def list_incidents(self, state: str | None = None, limit: int = 50) -> list[Incident]:
        q = sa.select(incidents).order_by(incidents.c.opened_at.desc(), incidents.c.incident_id.desc()).limit(limit)
        if state:
            q = q.where(incidents.c.state == state)
        return [self._inc(r) for r in self._all(q)]

    # alerts (unique on (fingerprint, fired_at))
    def save_alert(self, a: Alert) -> None:
        stmt = pg_insert(alerts).values(incident_id=a.incident_id, service=a.service, rule=a.rule, state=a.state,
                                        fired_at=a.fired_at, resolved_at=a.resolved_at, fingerprint=a.fingerprint)
        stmt = stmt.on_conflict_do_update(constraint="alerts_fingerprint_fired_at_key",
                                          set_=dict(state=a.state, resolved_at=a.resolved_at, incident_id=a.incident_id))
        self._exec(stmt)

    def list_alerts(self, incident_id: str | None = None, service: str | None = None) -> list[Alert]:
        q = sa.select(alerts).order_by(alerts.c.fired_at)
        if incident_id:
            q = q.where(alerts.c.incident_id == incident_id)
        if service:
            q = q.where(alerts.c.service == service)
        return [Alert(fingerprint=r["fingerprint"], service=r["service"], rule=r["rule"], state=r["state"], layer="symptom",
                      severity="warning", observed_at=r["fired_at"], fired_at=r["fired_at"], resolved_at=r["resolved_at"],
                      summary=r["rule"], incident_id=r["incident_id"]) for r in self._all(q)]

    # evidence
    def next_evidence_id(self, incident_id: str) -> str:
        return self._next_max(evidence, "evidence_id", "EV-", 3, evidence.c.incident_id == incident_id)

    def add_evidence(self, e: Evidence) -> None:
        payload = strip_nul(e.payload)
        if payload != e.payload:
            raise RepositoryError("NUL character in evidence (must be stripped before storing)")
        self._exec(sa.insert(evidence).values(
            incident_id=e.incident_id, evidence_id=e.evidence_id, source=e.source, type=e.type, service=e.service,
            observed_at=e.observed_at, collected_at=e.collected_at, query=e.query, status=e.status,
            missing_signal_state=e.missing_signal_state, summary=e.summary, payload=e.payload,
            payload_hash=e.payload_hash, untrusted=e.untrusted))

    @staticmethod
    def _ev(r) -> Evidence:
        return Evidence(**{k: r[k] for k in ("evidence_id", "incident_id", "source", "type", "service", "observed_at", "collected_at",
                                             "query", "status", "missing_signal_state", "summary", "payload", "payload_hash", "untrusted")})

    def get_evidence(self, incident_id: str, evidence_id: str) -> Evidence | None:
        r = self._one(sa.select(evidence).where(evidence.c.incident_id == incident_id, evidence.c.evidence_id == evidence_id))
        return self._ev(r) if r else None

    def list_evidence(self, incident_id: str) -> list[Evidence]:
        return [self._ev(r) for r in self._all(sa.select(evidence).where(evidence.c.incident_id == incident_id).order_by(evidence.c.evidence_id))]

    # timeline
    def next_event_id(self, incident_id: str) -> str:
        return self._next_max(timeline_events, "event_id", "TL-", 4, timeline_events.c.incident_id == incident_id)

    def add_event(self, e: TimelineEvent) -> None:
        self._upsert(timeline_events, dict(event_id=e.event_id, incident_id=e.incident_id, event_time=e.event_time, collected_at=e.collected_at,
                                           kind=e.kind, service=e.service, summary=e.summary, evidence_refs=list(e.evidence_refs),
                                           suppressed=e.suppressed), ["incident_id", "event_id"])

    def list_events(self, incident_id: str) -> list[TimelineEvent]:
        rows = self._all(sa.select(timeline_events).where(timeline_events.c.incident_id == incident_id)
                         .order_by(timeline_events.c.event_time, timeline_events.c.event_id))
        return [TimelineEvent(**{k: r[k] for k in ("event_id", "incident_id", "event_time", "collected_at", "kind", "service",
                                                   "summary", "evidence_refs", "suppressed")}) for r in rows]

    # diagnoses: one row per hypothesis; rank-1 body also carries `_diagnosis` extras (assumption, see STATUS)
    def save_diagnosis(self, d: Diagnosis) -> None:
        with self.engine.begin() as c:
            for h in d.hypotheses:
                body = h.to_contract()
                if h.rank == 1:
                    body["_diagnosis"] = {"engine_version": d.engine_version,
                                          "recommended_action": d.recommended_action.to_contract() if d.recommended_action else None}
                c.execute(pg_insert(hypotheses).values(
                    incident_id=d.incident_id, rank=h.rank, generated_at=d.generated_at, cause_id=h.cause_id, service=h.service,
                    description=h.description, confidence=h.confidence, status=h.status, origin=d.origin, body=body))

    def latest_diagnosis(self, incident_id: str) -> Diagnosis | None:
        latest = self._one(sa.select(sa.func.max(hypotheses.c.generated_at).label("g")).where(hypotheses.c.incident_id == incident_id))
        if not latest or latest["g"] is None:
            return None
        rows = self._all(sa.select(hypotheses).where(hypotheses.c.incident_id == incident_id, hypotheses.c.generated_at == latest["g"])
                         .order_by(hypotheses.c.rank))
        hyps, meta = [], {}
        for r in rows:
            body = dict(r["body"])
            meta = body.pop("_diagnosis", meta)
            hyps.append(body)
        return Diagnosis(incident_id=incident_id, generated_at=latest["g"], origin=rows[0]["origin"], hypotheses=hyps,
                         engine_version=meta.get("engine_version"), recommended_action=meta.get("recommended_action"))

    # remediation
    def next_plan_id(self) -> str:
        return self._next_max(plans, "plan_id", "PL-", 4)

    def save_plan(self, p: Plan) -> None:
        self._upsert(plans, dict(plan_id=p.plan_id, incident_id=p.incident_id, action_id=p.action_id,
                                 params=p.params.to_contract(), risk_class=p.risk_class, origin=p.origin,
                                 evidence_refs=list(p.evidence_refs), rationale=p.rationale, plan_hash=p.plan_hash,
                                 created_at=p.created_at), ["plan_id"])

    @staticmethod
    def _plan(r) -> Plan:
        return Plan(plan_id=r["plan_id"], incident_id=r["incident_id"], action_id=r["action_id"], params=r["params"],
                    risk_class=r["risk_class"], origin=r["origin"], evidence_refs=r["evidence_refs"], rationale=r["rationale"],
                    created_at=r["created_at"], plan_hash=r["plan_hash"])

    def get_plan(self, plan_id: str) -> Plan | None:
        r = self._one(sa.select(plans).where(plans.c.plan_id == plan_id))
        return self._plan(r) if r else None

    def list_plans(self, incident_id: str) -> list[Plan]:
        return [self._plan(r) for r in self._all(sa.select(plans).where(plans.c.incident_id == incident_id).order_by(plans.c.created_at, plans.c.plan_id))]

    def next_decision_id(self) -> str:
        return self._next_max(policy_decisions, "decision_id", "DEC-", 4)

    def save_decision(self, d: Decision) -> None:
        self._upsert(policy_decisions, dict(decision_id=d.decision_id, plan_id=d.plan_id, plan_hash=d.plan_hash, l1=d.l1.to_contract(),
                                            l2=d.l2.to_contract() if d.l2 else None, final=d.final, reasons=list(d.reasons),
                                            invariants_version=d.invariants_version, decided_at=d.decided_at), ["decision_id"])

    def list_decisions(self, incident_id: str) -> list[Decision]:
        q = (sa.select(policy_decisions).join(plans, plans.c.plan_id == policy_decisions.c.plan_id)
             .where(plans.c.incident_id == incident_id).order_by(policy_decisions.c.decided_at, policy_decisions.c.decision_id))
        return [Decision(decision_id=r["decision_id"], plan_id=r["plan_id"], plan_hash=r["plan_hash"], l1=r["l1"], l2=r["l2"],
                         final=r["final"], reasons=r["reasons"] or [], invariants_version=r["invariants_version"],
                         decided_at=r["decided_at"]) for r in self._all(q)]

    def save_approval(self, plan_id, plan_hash, approver, decision, reason, decided_at) -> None:
        self._exec(sa.insert(approvals).values(plan_id=plan_id, plan_hash=plan_hash, approver=approver, decision=decision,
                                                reason=reason, decided_at=decided_at))

    def list_approvals(self, plan_id: str) -> list[dict]:
        return [dict(r) for r in self._all(sa.select(approvals).where(approvals.c.plan_id == plan_id).order_by(approvals.c.decided_at))]

    def next_execution_id(self) -> str:
        return self._next_max(executions, "execution_id", "EX-", 4)

    def save_execution(self, x: Execution) -> None:
        self._upsert(executions, dict(execution_id=x.execution_id, plan_id=x.plan_id, idempotency_key=x.idempotency_key,
                                      started_at=x.started_at, ended_at=x.ended_at, result=x.result,
                                      refusal_rule_ids=list(x.refusal_rule_ids or []), executed_argv=list(x.executed_argv or []),
                                      detail=x.detail), ["execution_id"])

    @staticmethod
    def _ex(r) -> Execution:
        return Execution(execution_id=r["execution_id"], plan_id=r["plan_id"], idempotency_key=r["idempotency_key"],
                         started_at=r["started_at"], ended_at=r["ended_at"], result=r["result"],
                         refusal_rule_ids=r["refusal_rule_ids"] or None, executed_argv=r["executed_argv"] or None, detail=r["detail"])

    def list_executions(self, incident_id: str) -> list[Execution]:
        q = (sa.select(executions).join(plans, plans.c.plan_id == executions.c.plan_id)
             .where(plans.c.incident_id == incident_id).order_by(executions.c.started_at, executions.c.execution_id))
        return [self._ex(r) for r in self._all(q)]

    def get_execution_by_key(self, idempotency_key: str) -> Execution | None:
        r = self._one(sa.select(executions).where(executions.c.idempotency_key == idempotency_key))
        return self._ex(r) if r else None

    def save_verification(self, v: Verification) -> None:
        c = v.to_contract()
        self._exec(sa.insert(verifications).values(incident_id=v.incident_id, execution_id=v.execution_id, verdict=v.verdict,
                                                   window_start=v.window_start, window_end=v.window_end, checks=c["checks"]))

    def list_verifications(self, incident_id: str) -> list[Verification]:
        rows = self._all(sa.select(verifications).where(verifications.c.incident_id == incident_id).order_by(verifications.c.verification_id))
        return [Verification(incident_id=r["incident_id"], execution_id=r["execution_id"], verdict=r["verdict"],
                             window_start=r["window_start"], window_end=r["window_end"], checks=r["checks"]) for r in rows]

    # audit
    def last_audit(self) -> AuditEvent | None:
        r = self._one(sa.select(audit_log).order_by(audit_log.c.seq.desc()).limit(1))
        return self._au(r) if r else None

    @staticmethod
    def _au(r) -> AuditEvent:
        return AuditEvent(seq=r["seq"], incident_id=r["incident_id"], actor=r["actor"], event=r["event"], detail=r["detail"],
                          prev_hash=r["prev_hash"], hash=r["hash"], created_at=r["created_at"])

    def append_audit(self, e: AuditEvent) -> None:
        # the BEFORE INSERT trigger verifies seq/prev_hash and serialises writers
        self._exec(sa.insert(audit_log).values(seq=e.seq, incident_id=e.incident_id, actor=e.actor, event=e.event, detail=e.detail,
                                                prev_hash=e.prev_hash, hash=e.hash, created_at=e.created_at))

    def list_audit(self, incident_id: str | None = None, after_seq: int = 0, limit: int = 100) -> list[AuditEvent]:
        q = sa.select(audit_log).where(audit_log.c.seq > after_seq).order_by(audit_log.c.seq).limit(limit)
        if incident_id:
            q = q.where(audit_log.c.incident_id == incident_id)
        return [self._au(r) for r in self._all(q)]

    def all_audit(self) -> list[AuditEvent]:
        return [self._au(r) for r in self._all(sa.select(audit_log).order_by(audit_log.c.seq))]
