import pytest
from stack import KEY, build, key_file

from backend.domain.clock import parse_ts
from backend.domain.contracts import validate_against_contract
from backend.remediation.actuator import ActuatorUnavailable, InProcessFakeActuator
from backend.remediation.engine import (EngineConfig, RemediationConflict, RemediationDenied, diagnosis_is_valid)
from backend.remediation.signing import SigningUnavailable
from backend.verifier import VerifierConfig


from backend.remediation.planner import Planner


class RepeatingPlanner(Planner):
    def plan(self, incident_id, diagnosis, now, failed_before=None):
        return super().plan(incident_id, diagnosis, now, set())


def all_contracts(s, iid):
    for p in s.repo.list_plans(iid):
        validate_against_contract(p.to_contract(), "plan")
    for d in s.repo.list_decisions(iid):
        validate_against_contract(d.to_contract(), "decision")
    for x in s.repo.list_executions(iid):
        validate_against_contract(x.to_contract(), "execution")
    for v in s.repo.list_verifications(iid):
        validate_against_contract(v.to_contract(), "verification")
    for e in s.repo.list_events(iid):
        validate_against_contract(e.to_contract(), "incident", "#/$defs/timeline_event")
    for a in s.repo.all_audit():
        validate_against_contract(a.to_contract(), "audit_event")
    assert s.audit.chain_valid()


def test_worker_crash_low_risk_auto_restart_recovers(world, catalog, cfg):
    s = build(world, catalog, cfg, "worker_crash_recovered")
    s.poll_until(140)
    iid = s.incident().incident_id
    assert s.eng.run(iid) == "Succeeded"
    inc = s.repo.get_incident(iid)
    assert inc.state == "recovered" and inc.outcome == "mitigated" and inc.root_cause_confirmed is False
    assert s.act.commands == [["docker", "restart", "cd-worker"]]
    ver = s.repo.list_verifications(iid)[0]
    assert ver.verdict == "recovered" and {c.name for c in ver.checks} == {
        "readiness", "dependencies", "error_sli", "latency_sli", "synthetic_transaction", "no_regression", "telemetry_fresh"}
    assert all(c.passed is True for c in ver.checks)
    err = [c for c in ver.checks if c.name == "error_sli"][0]
    assert err.pre_action is not None and err.post_action is not None and err.baseline is not None
    assert s.col.has_pre_action_snapshot(iid)
    all_contracts(s, iid)
    # snapshot was taken BEFORE the action
    snap_audit = [a.seq for a in s.repo.all_audit() if a.event == "evidence.pre_action_snapshot"][0]
    exec_audit = [a.seq for a in s.repo.all_audit() if a.event == "execution.finished"][0]
    assert snap_audit < exec_audit


def test_redis_restart_needs_approval_bound_to_plan_hash(world, catalog, cfg):
    s = build(world, catalog, cfg, "redis_outage_recovered")
    s.poll_until(140)
    iid = s.incident().incident_id
    assert s.eng.run(iid) == "AwaitingApproval"
    plan = s.repo.list_plans(iid)[0]
    assert plan.risk_class == "medium" and plan.action_id == "restart_service" and plan.params.service == "redis"
    assert s.act.commands == []  # nothing ran without approval
    dec = s.repo.list_decisions(iid)[0]
    assert dec.final == "allow_with_approval"
    with pytest.raises(RemediationConflict):
        s.eng.approve(iid, plan.plan_id, "sha256:" + "0" * 64, "alice", "wrong hash")
    assert s.act.commands == []
    s.clock.set(s.world.scenario.at(142))
    dec2 = s.eng.approve(iid, plan.plan_id, plan.plan_hash, "alice", "redis restart is acceptable")
    assert dec2.final == "allow"
    with pytest.raises(RemediationConflict):  # double approval
        s.eng.approve(iid, plan.plan_id, plan.plan_hash, "alice", "again")
    assert s.eng.run(iid) == "Succeeded"
    assert s.act.commands == [["docker", "restart", "cd-redis"]]
    assert s.repo.get_incident(iid).root_cause_confirmed is False
    assert s.repo.list_approvals(plan.plan_id)[0]["decision"] == "approved"
    all_contracts(s, iid)


def test_reject_escalates(world, catalog, cfg):
    s = build(world, catalog, cfg, "redis_outage_recovered")
    s.poll_until(140)
    iid = s.incident().incident_id
    s.eng.run(iid)
    plan = s.repo.list_plans(iid)[0]
    s.eng.reject(iid, plan.plan_id, "alice", "not now")
    assert s.repo.get_incident(iid).state == "escalated" and s.act.commands == []
    with pytest.raises(RemediationConflict):
        s.eng.reject(iid, plan.plan_id, "alice", "twice")


def persistent_redis(world, catalog, cfg, engine_cfg=None):
    s = build(world, catalog, cfg, "redis_outage", engine_cfg=engine_cfg)  # never recovers, even after a restart
    s.poll_until(140)
    return s, s.incident().incident_id


def approve_current(s, iid):
    plan = [p for p in s.repo.list_plans(iid) if s.eng.plan_state(iid, p.plan_id) == "AwaitingApproval"][0]
    s.eng.approve(iid, plan.plan_id, plan.plan_hash, "alice", "approved")


def test_failed_remediation_escalates_without_repeating_same_action(world, catalog, cfg):
    s, iid = persistent_redis(world, catalog, cfg)
    s.eng.run(iid)
    approve_current(s, iid)
    assert s.eng.run(iid) == "Cooldown"  # first restart failed verification
    assert s.repo.list_verifications(iid)[0].verdict in ("failed", "partial")
    s.clock.sleep(21)  # cooldown elapsed; the diagnosis is unchanged -> strategy change required
    s.eng.run(iid)
    assert s.repo.get_incident(iid).state == "escalated"
    assert len(s.act.commands) == 1  # never a second identical restart
    assert any(p.action_id == "escalate" for p in s.repo.list_plans(iid))
    all_contracts(s, iid)


def test_attempt_budget_cooldown_and_circuit_breaker(world, catalog, cfg):
    s, iid = persistent_redis(world, catalog, cfg)
    # permit repeating the action (as if new evidence had changed the diagnosis) so the attempt budget/breaker is exercised
    s.eng.planner = RepeatingPlanner(s.repo, catalog)
    s.eng.run(iid)
    approve_current(s, iid)
    assert s.eng.run(iid) == "Cooldown"
    t1 = s.eng.cfg.cooldown_seconds
    s.clock.sleep(5)
    assert s.eng.run(iid) == "Cooldown"  # still cooling down: no action
    assert len(s.act.commands) == 1
    s.clock.sleep(t1)
    assert s.eng.run(iid) == "AwaitingApproval"  # second attempt needs approval again
    approve_current(s, iid)
    s.eng.run(iid)
    assert len(s.act.commands) == 2
    assert [v.verdict for v in s.repo.list_verifications(iid)] == ["failed", "failed"]
    assert s.eng.circuit(iid) == "open" and s.repo.get_incident(iid).state == "escalated"
    assert s.eng.view(iid)["attempts_remaining"] == 0 and s.eng.view(iid)["circuit_breaker"] == "open"
    s.eng.run(iid)
    assert len(s.act.commands) == 2  # no third restart, ever
    # a human may reset it (half_open), but escalated incidents stay terminal for the engine
    s.eng.reset_breaker(iid, "alice")
    assert s.eng.circuit(iid) == "half_open"


def test_regression_aborts_and_escalates(world, catalog, cfg):
    data = world("redis_outage_recovered").scenario.data
    # worker (not in the original redis incident services? it is) -> use loadgen: breaks after the restart
    data["samples"]["loadgen"]["up"] = [[t, 0 if t >= 152 else 1] for t, _ in data["samples"]["loadgen"]["up"]]
    s = build(world, catalog, cfg, data)
    s.poll_until(140)
    iid = s.incident().incident_id
    s.eng.run(iid)
    approve_current(s, iid)
    s.eng.run(iid)
    assert s.repo.list_verifications(iid)[0].verdict == "regression"
    assert s.eng.circuit(iid) == "open" and s.repo.get_incident(iid).state == "escalated"
    assert len(s.act.commands) == 1


def test_unverifiable_fails_closed(world, catalog, cfg):
    data = world("redis_outage_recovered").scenario.data
    data["outages"].append({"from_s": 150, "to_s": 300, "mode": "timeout", "signal": "prom"})
    s = build(world, catalog, cfg, data)
    s.poll_until(140)
    iid = s.incident().incident_id
    s.eng.run(iid)
    approve_current(s, iid)
    s.eng.run(iid)
    ver = s.repo.list_verifications(iid)[0]
    assert ver.verdict == "unverifiable" and any(c.passed is None for c in ver.checks)
    assert s.repo.get_incident(iid).state == "escalated" and s.repo.get_incident(iid).outcome == "escalated"
    all_contracts(s, iid)


def test_no_signing_key_fails_closed(world, catalog, cfg):
    def no_key():
        raise SigningUnavailable("missing")

    s = build(world, catalog, cfg, "worker_crash_recovered", key_loader=no_key)
    s.poll_until(140)
    iid = s.incident().incident_id
    s.eng.run(iid)
    assert s.act.commands == [] and s.repo.get_incident(iid).state == "escalated"


def test_actuator_unavailable_fails_closed(world, catalog, cfg):
    act = InProcessFakeActuator(catalog, KEY, None, available=False)
    s = build(world, catalog, cfg, "worker_crash_recovered", actuator=act)
    act.clock = s.clock
    s.poll_until(140)
    iid = s.incident().incident_id
    s.eng.run(iid)
    assert act.commands == [] and s.repo.get_incident(iid).state == "escalated"


def test_database_is_never_restarted_only_escalated(world, catalog, cfg):
    s = build(world, catalog, cfg, "db_saturation")
    s.poll_until(150)
    iid = s.incident().incident_id
    s.eng.run(iid)
    plans = s.repo.list_plans(iid)
    assert [p.action_id for p in plans] == ["escalate"]
    assert s.act.commands == [] and s.repo.get_incident(iid).state == "escalated"


def test_decoy_does_not_trigger_remediation_of_the_decoy(world, catalog, cfg):
    s = build(world, catalog, cfg, "false_correlation")
    s.poll_until(150)
    iid = s.incident().incident_id
    s.eng.run(iid)
    assert s.act.commands == []  # CPU saturation has no safe catalogue action -> escalate; the deployed worker is untouched


def test_diagnosis_validation_requires_existing_evidence(world, catalog, cfg):
    s = build(world, catalog, cfg, "worker_crash_recovered")
    s.poll_until(140)
    iid = s.incident().incident_id
    d = s.eng.diagnose(iid)
    ids = {e.evidence_id for e in s.repo.list_evidence(iid)}
    assert diagnosis_is_valid(d, ids) and not diagnosis_is_valid(d, set())
