import pytest
from helpers import run_detector

from backend.audit import AuditWriter
from backend.detector.expected import ExpectedStateRegistry
from backend.domain.clock import FakeClock
from backend.domain.contracts import validate_against_contract
from backend.evidence import EvidenceCollector
from backend.incidents.manager import IncidentManager
from backend.rca.engine import RcaEngine
from backend.repositories import MemoryRepository


def diagnose(world, catalog, cfg, name, at_s, lookback=300, scenario_data=None, until=None):
    w = world(scenario_data or name)
    repo, clock = MemoryRepository(), FakeClock(w.scenario.at(5))
    audit = AuditWriter(repo, clock)
    mgr = IncidentManager(repo, catalog, cfg, audit, clock)
    run_detector(w, catalog, cfg, until_s=until or at_s, on_poll=lambda t, r: (clock.set(r.at), mgr.ingest(r)))
    incs = repo.list_incidents()
    assert incs, "no incident opened"
    inc = sorted(incs, key=lambda i: i.opened_at)[0]
    clock.set(w.scenario.at(at_s))
    col = EvidenceCollector(repo, catalog, cfg, w.prom, w.logs, w.feed, w.prober, ExpectedStateRegistry(), audit, clock, mgr.timeline, lookback)
    col.collect(inc.incident_id)
    ev = repo.list_evidence(inc.incident_id)
    d = RcaEngine(catalog, clock).diagnose(inc.incident_id, ev, inc.services)
    validate_against_contract(d.to_contract(), "diagnosis")
    ids = {e.evidence_id for e in ev}
    for h in d.hypotheses:  # every claim, including contradicting ones, cites existing evidence
        for cl in h.claims + h.contradicting:
            assert cl.evidence and set(cl.evidence) <= ids
        assert h.status != "confirmed"
    return d, inc, repo


def top(d):
    return d.hypotheses[0]


def test_redis_outage_cascade_attributed_to_redis(world, catalog, cfg):
    d, inc, _ = diagnose(world, catalog, cfg, "redis_outage", 140)
    t = top(d)
    assert t.cause_id == "redis_unavailable" and t.service == "redis" and t.status == "supported" and t.confidence >= 0.8
    assert {c.type for c in t.claims} >= {"observation", "inference", "temporal_correlation"}
    others = {h.cause_id: h for h in d.hypotheses[1:]}
    assert "api_local_fault" in others and others["api_local_fault"].status == "refuted"
    assert others["api_local_fault"].contradicting and t.alternatives and t.unknowns
    assert any("why redis stopped" in u for u in t.unknowns)
    assert d.recommended_action.action_id == "restart_service" and d.recommended_action.params == {"service": "redis"}
    assert any("independent_signal_types=3" in b for b in t.confidence_basis)


def test_worker_crash_is_worker_not_redis(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "worker_crash", 140)
    t = top(d)
    assert t.cause_id == "worker_unavailable" and t.confidence >= 0.7
    assert not any(h.cause_id == "redis_unavailable" for h in d.hypotheses)
    assert any(a.startswith("redis_unavailable (rejected") for a in t.alternatives)  # considered and rejected, with the reason
    assert d.recommended_action.action_id == "restart_service" and d.recommended_action.params["service"] == "worker"
    assert any("user-facing services stay healthy" in c.text for c in t.claims)


def test_memory_exhaustion_recurrence_escalates(world, catalog, cfg):
    d1, _, _ = diagnose(world, catalog, cfg, "memory_exhaustion", 118, until=118)
    t = top(d1)
    assert t.cause_id == "api_memory_exhaustion" and t.confidence >= 0.6
    assert d1.recommended_action.action_id == "restart_service"  # first OOM: restart is the bounded mitigation
    d2, _, _ = diagnose(world, catalog, cfg, "memory_exhaustion", 260, until=260)
    t2 = top(d2)
    assert t2.cause_id == "api_memory_exhaustion"
    assert d2.recommended_action.action_id == "escalate"  # recurs after restart: loop guard path
    assert any("recurred" in u for u in t2.unknowns)


def test_bad_deployment(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "bad_deployment", 140)
    t = top(d)
    assert t.cause_id == "api_bad_deployment" and t.confidence >= 0.7
    kinds = {c.type for c in t.claims}
    assert "temporal_correlation" in kinds and "observation" in kinds
    assert d.recommended_action.action_id == "rollback_service"
    assert d.recommended_action.params == {"service": "api", "version": "v1"}


def test_false_correlation_decoy_is_not_ranked_first(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "false_correlation", 150)
    t = top(d)
    assert t.cause_id == "api_cpu_saturation", [h.cause_id for h in d.hypotheses]
    generic = [h for h in d.hypotheses if h.cause_id == "api_local_fault"]
    assert not generic or generic[0].confidence <= 0.35 < t.confidence
    decoy = [h for h in d.hypotheses if h.cause_id == "worker_bad_deployment"]
    assert decoy and decoy[0].rank > 1 and decoy[0].status == "refuted"
    assert decoy[0].confidence <= 0.3 and decoy[0].contradicting
    assert any("temporal order" in b for b in decoy[0].confidence_basis)


def test_db_saturation_is_exhaustion_not_down(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "db_saturation", 150)
    t = top(d)
    assert t.cause_id == "app_db_connection_exhaustion"
    down = [h for h in d.hypotheses if h.cause_id == "app_db_unavailable"]
    assert (not down) or (down[0].status == "refuted" and down[0].contradicting)
    assert any("app_db_unavailable" in a for a in t.alternatives)
    assert d.recommended_action.action_id == "escalate"  # restarting a database is never allowed
    assert any("connection counts" in u for u in t.unknowns)


def test_restart_before_recovery_is_never_a_cause(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "restart_before_recovery", 160)
    ids = [h.cause_id for h in d.hypotheses]
    assert not any("restart" in i for i in ids)
    assert top(d).cause_id != "redis_memory_exhaustion"


def test_temporal_only_support_is_capped(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "false_correlation", 150)
    for h in d.hypotheses:
        if all(c.type == "temporal_correlation" for c in h.claims):
            assert h.confidence <= 0.3


def test_telemetry_failure_gives_unknown_not_healthy(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "redis_outage_telemetry_failure", 150, until=125)
    ids = [h.cause_id for h in d.hypotheses]
    assert "telemetry_collection_failed" in ids
    t = [h for h in d.hypotheses if h.cause_id == "telemetry_collection_failed"][0]
    assert any("unknown" in u or "cannot be established" in u for u in t.unknowns)
    assert d.recommended_action.action_id in ("escalate", "restart_service")


def test_diagnosis_is_deterministic(world, catalog, cfg):
    a, _, _ = diagnose(world, catalog, cfg, "redis_outage", 140)
    b, _, _ = diagnose(world, catalog, cfg, "redis_outage", 140)
    assert [(h.cause_id, h.confidence) for h in a.hypotheses] == [(h.cause_id, h.confidence) for h in b.hypotheses]
