"""Remediation engine: the state machine from docs/06-self-healing/remediation-loops.md.

States per plan: Proposed, Rejected, AwaitingApproval, Approved, Executing, Verifying, Succeeded, Failed, Cooldown,
RolledBack, Escalated. Guards: max attempts (2), cooldown (20 s), circuit breaker (opens after repeated failure,
regression or an unverifiable result; only a human resets it), regression abort and escalation.

Fail closed: no signing key, unreachable actuator, refused plan, policy error, missing evidence snapshot, or an
unverifiable outcome all end in escalation, never in a retry.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend import policy_adapter as pa
from backend.audit import AuditWriter
from backend.domain.clock import Clock, iso
from backend.domain.contracts import validate_against_contract
from backend.domain.models import Decision, Diagnosis, Plan, Verification
from backend.evidence import EvidenceCollector
from backend.incidents.manager import IncidentManager, InvalidTransition
from backend.rca.engine import RcaEngine
from backend.repositories.base import Repository
from backend.verifier import Verifier

from .actuator import ActuatorClient, ActuatorUnavailable
from .planner import Planner
from .signing import SigningUnavailable, load_key, sign_plan


class RemediationConflict(Exception):
    """409: wrong plan state or plan_hash mismatch."""


class RemediationDenied(Exception):
    """403: policy refused; carries rule ids (never internals)."""

    def __init__(self, rule_ids: list[str]) -> None:
        super().__init__("denied")
        self.rule_ids = rule_ids


class NotFound(KeyError):
    pass


@dataclass
class EngineConfig:
    max_attempts: int = 2
    cooldown_seconds: float = 20
    breaker_threshold: int = 2
    max_partial_rechecks: int = 1
    signed_plan_ttl_seconds: int = 120


@dataclass
class _Inc:
    plan_state: dict[str, str] = field(default_factory=dict)
    circuit: str = "closed"  # closed | open | half_open
    failures: int = 0
    cooldown_until: datetime | None = None
    awaiting: str | None = None
    approved: dict[str, dict] = field(default_factory=dict)  # plan_id -> approval dict, ready to execute
    failed_before: set = field(default_factory=set)
    last_attempt: dict[tuple[str, str], datetime] = field(default_factory=dict)
    need_new_evidence: bool = False
    diagnosis_cause: str | None = None
    last_state: str = "Proposed"


def diagnosis_is_valid(d: Diagnosis, evidence_ids: set[str]) -> bool:
    """Reference validation (grounding rule 2): every claim cites >= 1 evidence id that exists in this incident."""
    return all(c.evidence and set(c.evidence) <= evidence_ids for h in d.hypotheses for c in h.claims + h.contradicting)


class RemediationEngine:
    def __init__(self, repo: Repository, mgr: IncidentManager, planner: Planner, collector: EvidenceCollector, rca: RcaEngine,
                 verifier: Verifier, actuator: ActuatorClient, audit: AuditWriter, clock: Clock, cfg: EngineConfig | None = None,
                 key_loader=load_key) -> None:
        self.repo, self.mgr, self.planner, self.collector, self.rca = repo, mgr, planner, collector, rca
        self.verifier, self.actuator, self.audit, self.clock = verifier, actuator, audit, clock
        self.cfg, self._key_loader = cfg or EngineConfig(), key_loader
        self.catalog = mgr.catalog
        self._st: dict[str, _Inc] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ helpers
    def _s(self, incident_id: str) -> _Inc:
        return self._st.setdefault(incident_id, _Inc())

    def _emit(self, typ: str, incident_id: str, **data) -> None:
        self.mgr._emit(typ, incident_id, **data)

    def _set(self, incident_id: str, plan_id: str, state: str) -> None:
        st = self._s(incident_id)
        st.plan_state[plan_id] = state
        st.last_state = state
        self.audit.write("planner", "plan.state", {"plan_id": plan_id, "state": state}, incident_id)

    def plan_state(self, incident_id: str, plan_id: str) -> str:
        return self._s(incident_id).plan_state.get(plan_id, "Proposed")

    def circuit(self, incident_id: str) -> str:
        return self._s(incident_id).circuit

    def attempts_used(self, incident_id: str, service: str = "", action: str = "") -> int:
        n = 0
        for ex in self.repo.list_executions(incident_id):
            p = self.repo.get_plan(ex.plan_id)
            if ex.result != "refused" and p and (not action or p.action_id == action) and (not service or p.params.service == service):
                n += 1
        return n

    def _ctx(self, incident_id: str, diag: Diagnosis, approval: dict | None):
        st = self._s(incident_id)
        ev_ids = {e.evidence_id for e in self.repo.list_evidence(incident_id)}

        def used(inc, svc, act):
            return self.attempts_used(inc, svc, act)

        return pa.make_context(
            catalog=self.catalog, now=self.clock.now(), attempts_used=used,
            last_attempt_at=lambda inc, svc, act: st.last_attempt.get((svc, act)),
            circuit_open=lambda inc: self._s(inc).circuit == "open", known_evidence_ids=ev_ids,
            diagnosis_validated=diagnosis_is_valid(diag, ev_ids), top_cause_service=diag.hypotheses[0].service, approval=approval,
            container_labels=None)

    def _decide(self, incident_id: str, plan: Plan, diag: Diagnosis, approval: dict | None = None) -> Decision:
        out = pa.evaluate(plan.to_contract(), self._ctx(incident_id, diag, approval))
        dec = Decision(decision_id=self.repo.next_decision_id(), plan_id=plan.plan_id, plan_hash=plan.plan_hash,
                       l1={"result": out.l1_result, "rule_ids": out.rule_ids}, final=out.final, reasons=[r[:300] for r in out.reasons],
                       invariants_version=out.invariants_version, decided_at=self.clock.now())
        validate_against_contract(dec.to_contract(), "decision")
        self.repo.save_decision(dec)
        self.audit.write("policy", "decision.recorded", {"plan_id": plan.plan_id, "final": dec.final, "rules": out.rule_ids}, incident_id)
        self.mgr.timeline.add(incident_id, dec.decided_at, "policy_decision", f"policy decision for {plan.plan_id} ({plan.action_id}): {dec.final} {'; '.join(out.rule_ids)}")
        self._emit("decision.recorded", incident_id, plan_id=plan.plan_id)
        return dec

    def _transition(self, incident_id: str, new: str, reason: str = "", **kw) -> None:
        try:
            self.mgr.transition(incident_id, new, "planner", reason, **kw)
        except InvalidTransition:
            pass

    # ------------------------------------------------------------------ diagnosis
    def diagnose(self, incident_id: str, fresh_evidence: bool = True) -> Diagnosis:
        with self._lock:
            inc = self.repo.get_incident(incident_id)
            if inc is None:
                raise NotFound(incident_id)
            if inc.state == "detected":
                self._transition(incident_id, "investigating", "collecting evidence")
            if fresh_evidence or not self.repo.list_evidence(incident_id):
                self.collector.collect(incident_id, self.clock.now(), phase="initial")
            d = self.rca.diagnose(incident_id, self.repo.list_evidence(incident_id), inc.services)
            self.repo.save_diagnosis(d)
            top = d.hypotheses[0]
            self.audit.write("rca", "diagnosis.created", {"top": top.cause_id, "confidence": top.confidence, "status": top.status}, incident_id)
            self.mgr.timeline.add(incident_id, d.generated_at, "diagnosis",
                                  f"diagnosis: top cause {top.cause_id} (confidence {top.confidence:.2f}, {top.status})", top.service,
                                  [e for c in top.claims for e in c.evidence][:6])
            self._s(incident_id).diagnosis_cause = top.cause_id
            if self.repo.get_incident(incident_id).state == "investigating":
                self._transition(incident_id, "diagnosed", f"top cause {top.cause_id}")
            self._emit("incident.updated", incident_id, diagnosis=top.cause_id)
            return d

    # ------------------------------------------------------------------ main driver
    def run(self, incident_id: str) -> str:
        """Advance the remediation as far as it can go without a human or the clock. Returns the last plan state."""
        with self._lock:
            st = self._s(incident_id)
            for _ in range(8):  # bounded: at most max_attempts iterations plus escalation
                inc = self.repo.get_incident(incident_id)
                if inc is None:
                    raise NotFound(incident_id)
                if inc.state in ("recovered", "closed", "escalated"):
                    return st.last_state
                if st.circuit == "open":
                    self._escalate(incident_id, "circuit breaker is open; autonomous remediation stopped")
                    return st.last_state
                if st.cooldown_until and self.clock.now() < st.cooldown_until:
                    st.last_state = "Cooldown"
                    return "Cooldown"
                if st.awaiting:
                    return "AwaitingApproval"
                for pid, ap in list(st.approved.items()):
                    plan = self.repo.get_plan(pid)
                    st.approved.pop(pid)
                    self._execute(incident_id, plan, ap)
                    break
                else:
                    diag = self.repo.latest_diagnosis(incident_id)
                    if diag is None or st.need_new_evidence:
                        diag = self.diagnose(incident_id, fresh_evidence=True)
                        st.need_new_evidence = False
                    self._propose(incident_id, diag)
                continue
            return st.last_state

    def tick(self) -> list[str]:
        """Resume incidents whose cooldown elapsed; run approved plans. Called by the background worker."""
        out = []
        with self._lock:
            now = self.clock.now()
            for iid, st in list(self._st.items()):
                if (st.cooldown_until and now >= st.cooldown_until) or st.approved:
                    st.cooldown_until = None
                    self.run(iid)
                    out.append(iid)
        return out

    def _propose(self, incident_id: str, diag: Diagnosis) -> None:
        st = self._s(incident_id)
        plan = self.planner.plan(incident_id, diag, self.clock.now(), st.failed_before)
        self._set(incident_id, plan.plan_id, "Proposed")
        self.audit.write("planner", "plan.created", {"plan_id": plan.plan_id, "action": plan.action_id, "risk": plan.risk_class}, incident_id)
        self.mgr.timeline.add(incident_id, plan.created_at, "action", f"plan {plan.plan_id}: {plan.action_id} {plan.params.to_contract()} (risk {plan.risk_class})",
                              plan.params.service)
        self._emit("plan.created", incident_id, plan_id=plan.plan_id)
        dec = self._decide(incident_id, plan, diag)
        if dec.final == "deny":
            self._set(incident_id, plan.plan_id, "Rejected")
            self._escalate(incident_id, f"policy denied {plan.action_id}: {', '.join(dec.l1.rule_ids)}")
        elif dec.final == "allow_with_approval":
            st.awaiting = plan.plan_id
            self._set(incident_id, plan.plan_id, "AwaitingApproval")
        else:
            self._set(incident_id, plan.plan_id, "Approved")
            st.approved[plan.plan_id] = None  # executed by the run loop

    # ------------------------------------------------------------------ approval (human)
    def approve(self, incident_id: str, plan_id: str, plan_hash: str, approver: str, reason: str) -> Decision:
        with self._lock:
            plan = self.repo.get_plan(plan_id)
            st = self._s(incident_id)
            if plan is None or plan.incident_id != incident_id:
                raise NotFound(plan_id)
            if plan.plan_hash != plan_hash or st.plan_state.get(plan_id) != "AwaitingApproval" or st.awaiting != plan_id:
                raise RemediationConflict("plan is not awaiting approval, or plan_hash does not match")
            approval = {"approver": approver[:80], "approved_at": iso(self.clock.now()), "reason": reason[:300], "plan_hash": plan.plan_hash}
            diag = self.repo.latest_diagnosis(incident_id)
            dec = self._decide(incident_id, plan, diag, approval)  # policy is re-evaluated with the approval attached
            if dec.final != "allow":
                raise RemediationDenied(dec.l1.rule_ids)
            self.repo.save_approval(plan_id, plan_hash, approver, "approved", reason, self.clock.now())
            self.audit.write(f"operator:{approver}"[:60], "plan.approved", {"plan_id": plan_id, "plan_hash": plan_hash}, incident_id)
            st.awaiting = None
            self._set(incident_id, plan_id, "Approved")
            st.approved[plan_id] = approval
            return dec

    def reject(self, incident_id: str, plan_id: str, approver: str, reason: str) -> None:
        with self._lock:
            plan = self.repo.get_plan(plan_id)
            st = self._s(incident_id)
            if plan is None or plan.incident_id != incident_id:
                raise NotFound(plan_id)
            if st.plan_state.get(plan_id) != "AwaitingApproval":
                raise RemediationConflict("plan is not awaiting approval")
            self.repo.save_approval(plan_id, plan.plan_hash, approver, "rejected", reason, self.clock.now())
            self.audit.write(f"operator:{approver}"[:60], "plan.rejected", {"plan_id": plan_id}, incident_id)
            st.awaiting = None
            self._set(incident_id, plan_id, "Rejected")
            self._escalate(incident_id, f"operator rejected {plan.action_id}: {reason[:120]}")

    def reset_breaker(self, incident_id: str, operator: str) -> None:
        """Only a human resets the circuit breaker; it re-enters as half_open (one trial)."""
        with self._lock:
            st = self._s(incident_id)
            st.circuit, st.failures = "half_open", self.cfg.breaker_threshold - 1
            self.audit.write(f"operator:{operator}"[:60], "circuit.reset", {}, incident_id)

    # ------------------------------------------------------------------ execution
    def _execute(self, incident_id: str, plan: Plan, approval: dict | None) -> None:
        st = self._s(incident_id)
        if plan.action_id == "escalate":
            self._set(incident_id, plan.plan_id, "Escalated")
            self._escalate(incident_id, plan.params.reason or "escalation requested", plan=plan)
            return
        try:
            key = self._key_loader()
        except SigningUnavailable as exc:
            self._set(incident_id, plan.plan_id, "Failed")
            self._escalate(incident_id, f"cannot sign plans ({exc}); failing closed")
            return
        try:  # evidence BEFORE any action: a restart destroys in-memory state and logs
            self.collector.snapshot_before_action(incident_id)
        except Exception:
            self._set(incident_id, plan.plan_id, "Failed")
            self._escalate(incident_id, "pre-action evidence snapshot failed; failing closed")
            return
        if not self.collector.has_pre_action_snapshot(incident_id):
            self._set(incident_id, plan.plan_id, "Failed")
            self._escalate(incident_id, "no pre-action snapshot; failing closed")
            return
        self._transition(incident_id, "remediating", f"executing {plan.action_id}")
        signed = sign_plan(plan.to_contract(), key, self.clock.now(), self.cfg.signed_plan_ttl_seconds, approval=approval)
        validate_against_contract(signed, "signed_plan")
        self._set(incident_id, plan.plan_id, "Executing")
        try:
            dry = self.actuator.validate(signed)
            if not dry["ok"]:
                self._set(incident_id, plan.plan_id, "Rejected")
                self._escalate(incident_id, f"actuator refused in dry-run: {', '.join(dry['rule_ids'])}")
                return
            attempt = self.attempts_used(incident_id) + 1
            ex = self.actuator.execute(signed, f"{plan.plan_id}-a{attempt}")
        except ActuatorUnavailable:
            self._set(incident_id, plan.plan_id, "Failed")
            self._escalate(incident_id, "actuator unavailable or returned an invalid response; failing closed")
            return
        self.repo.save_execution(ex)
        self.audit.write("actuator", "execution.finished", {"execution_id": ex.execution_id, "result": ex.result}, incident_id)
        self.mgr.timeline.add(incident_id, ex.started_at, "action", f"execution {ex.execution_id} of {plan.plan_id}: {ex.result}", plan.params.service, collected_at=ex.ended_at or ex.started_at)
        self._emit("execution.finished", incident_id, execution_id=ex.execution_id)
        if ex.result == "refused":
            self._set(incident_id, plan.plan_id, "Rejected")
            self._escalate(incident_id, f"actuator refused execution: {', '.join(ex.refusal_rule_ids or [])}")
            return
        st.last_attempt[(plan.params.service or "", plan.action_id)] = ex.started_at
        if ex.result == "failed":
            self._set(incident_id, plan.plan_id, "Failed")
            self._after_failure(incident_id, plan)
            return
        self._transition(incident_id, "verifying", "action returned; verifying recovery")
        self._set(incident_id, plan.plan_id, "Verifying")
        inc = self.repo.get_incident(incident_id)
        ver = self.verifier.verify(incident_id, ex.execution_id, list(inc.services), ex.ended_at or ex.started_at)
        self._emit("verification.finished", incident_id, verdict=ver.verdict)
        rechecks = 0
        while ver.verdict == "partial" and rechecks < self.cfg.max_partial_rechecks:  # keep observing, no new action
            rechecks += 1
            ver = self.verifier.verify(incident_id, ex.execution_id, list(inc.services), self.clock.now())
            self._emit("verification.finished", incident_id, verdict=ver.verdict)
        self._after_verification(incident_id, plan, ver)

    def _after_verification(self, incident_id: str, plan: Plan, ver: Verification) -> None:
        st = self._s(incident_id)
        if ver.verdict == "recovered":
            self._set(incident_id, plan.plan_id, "Succeeded")
            st.circuit, st.failures = "closed", 0
            # mitigated, NOT root-cause-confirmed: only ground truth / further analysis may set that
            self._transition(incident_id, "recovered", "verified recovery over the stability window", outcome="mitigated", root_cause_confirmed=False)
        elif ver.verdict == "regression":
            self._set(incident_id, plan.plan_id, "RolledBack")  # restart has no rollback; abort and escalate
            st.circuit = "open"
            self._escalate(incident_id, "regression detected after the action; autonomous remediation aborted")
        elif ver.verdict == "unverifiable":
            self._set(incident_id, plan.plan_id, "Failed")
            st.circuit = "open"
            self._escalate(incident_id, "recovery could not be verified (a check was unestablishable); failing closed")
        else:  # failed | partial (after rechecks) | relapse
            self._set(incident_id, plan.plan_id, "Failed")
            self._after_failure(incident_id, plan)

    def _after_failure(self, incident_id: str, plan: Plan) -> None:
        st = self._s(incident_id)
        st.failures += 1
        diag = self.repo.latest_diagnosis(incident_id)
        st.failed_before.add((diag.hypotheses[0].cause_id, plan.action_id, plan.params.service or ""))
        used = self.attempts_used(incident_id, plan.params.service or "", plan.action_id)
        if used >= self.cfg.max_attempts or st.failures >= self.cfg.breaker_threshold:
            st.circuit = "open"
            self.audit.write("planner", "circuit.opened", {"failures": st.failures, "attempts": used}, incident_id)
            self._escalate(incident_id, f"{used} attempt(s) did not recover the service; circuit breaker opened")
            return
        self._set(incident_id, plan.plan_id, "Cooldown")
        st.cooldown_until = self.clock.now() + timedelta(seconds=self.cfg.cooldown_seconds)
        st.need_new_evidence = True
        self._transition(incident_id, "remediating", "attempt failed; cooling down before a re-diagnosis")

    # ------------------------------------------------------------------ escalation
    def _escalate(self, incident_id: str, reason: str, plan: Plan | None = None) -> None:
        st = self._s(incident_id)
        inc = self.repo.get_incident(incident_id)
        if inc.state in ("escalated", "closed", "recovered"):
            return
        if plan is None:
            diag = self.repo.latest_diagnosis(incident_id)
            refs = [e for c in (diag.hypotheses[0].claims if diag else []) for e in c.evidence][:6] or [self.repo.list_evidence(incident_id)[0].evidence_id]
            raw = {"plan_id": self.repo.next_plan_id(), "incident_id": incident_id, "action_id": "escalate", "params": {"reason": reason[:300]},
                   "risk_class": "low", "origin": "rule", "evidence_refs": refs, "rationale": f"Escalation: {reason}"[:500],
                   "created_at": iso(self.clock.now())}
            raw["plan_hash"] = pa.plan_hash(raw)
            plan = Plan.model_validate(raw)
            self.repo.save_plan(plan)
            self._emit("plan.created", incident_id, plan_id=plan.plan_id)
            if diag:
                self._decide(incident_id, plan, diag)
        st.plan_state[plan.plan_id] = "Escalated"
        st.last_state = "Escalated"
        st.cooldown_until, st.awaiting = None, None
        self.audit.write("planner", "remediation.escalated", {"plan_id": plan.plan_id, "reason": reason[:200]}, incident_id)
        self.mgr.timeline.add(incident_id, self.clock.now(), "action", f"escalated to a human: {reason[:200]}")
        if inc.state in ("detected",):
            self._transition(incident_id, "investigating")
        self._transition(incident_id, "escalated", reason[:150], outcome="escalated")

    # ------------------------------------------------------------------ views
    def view(self, incident_id: str) -> dict:
        st = self._s(incident_id)
        return {"plans": [p.to_contract() for p in self.repo.list_plans(incident_id)],
                "decisions": [d.to_contract() for d in self.repo.list_decisions(incident_id)],
                "executions": [e.to_contract() for e in self.repo.list_executions(incident_id)],
                "circuit_breaker": st.circuit,
                "attempts_remaining": max(0, self.cfg.max_attempts - self.attempts_used(incident_id))}
