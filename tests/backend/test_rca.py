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
    # queue growth is not observable while the worker is dead (the series is absent), so confidence is lower than it would be with it
    assert t.cause_id == "worker_unavailable" and t.confidence >= 0.6
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
    # connection counts are measured (cd_db_connections, harness-4), so saturation is a cited observation and the leaker is named
    assert any("of 100 allowed connections" in c.text for c in t.claims)
    assert any("'connection_hog'" in c.text and "likely leaker" in c.text for c in t.claims)
    assert not any("leaking client is not identified" in u for u in t.unknowns)


def test_db_saturation_without_connection_series_keeps_the_unknowns(world, catalog, cfg):
    import copy

    from fixtures import scenarios
    data = copy.deepcopy(scenarios.ALL["db_saturation"]())
    for metric in ("db_connections", "db_max_connections", "db_connections_by_client"):
        data["samples"]["app-db"].pop(metric, None)
    d, _, _ = diagnose(world, catalog, cfg, data, 150)
    t = top(d)
    assert t.cause_id == "app_db_connection_exhaustion"
    assert any("connection saturation is not measured" in u for u in t.unknowns)
    assert any("leaking client is not identified" in u for u in t.unknowns)


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


def test_bad_deployment_without_change_feed_uses_build_info_history(world, catalog, cfg):
    data = world("bad_deployment").scenario.data
    data["events"] = []  # no deploy events at all (the live deployment has no change feed yet)
    d, _, _ = diagnose(world, catalog, cfg, "bad_deployment", 140, scenario_data=data)
    t = top(d)
    assert t.cause_id == "api_bad_deployment"
    assert d.recommended_action.action_id == "rollback_service" and d.recommended_action.params == {"service": "api", "version": "v1"}
    assert t.confidence < 0.95  # fewer independent signals than with the deploy event


def test_network_latency_is_the_path_not_the_database(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "network_latency", 150)
    t = top(d)
    assert t.cause_id == "app_db_network_latency" and t.status == "supported"
    assert any("database is not slow" in c.text for c in t.claims)  # server-side probe time normal
    assert any("inferred by exclusion" in u for u in t.unknowns)  # the path itself is not measured
    assert d.recommended_action.action_id == "escalate"  # no safe catalogue action for a network fault


def test_slow_database_is_not_called_network_latency(world, catalog, cfg):
    import copy

    from fixtures import scenarios
    data = copy.deepcopy(scenarios.ALL["network_latency"]())
    data["samples"]["app-db"]["db_probe_seconds"] = [[t, 0.9] for t in range(0, 301, 5)]  # the database itself is slow
    d, _, _ = diagnose(world, catalog, cfg, data, 150)
    t = top(d)
    assert t.cause_id != "app_db_network_latency" or any("answers slowly" in c.text for c in t.contradicting)


def test_disk_full_is_diagnosed_and_not_restarted(world, catalog, cfg):
    d, _, _ = diagnose(world, catalog, cfg, "disk_full", 150)
    t = top(d)
    assert t.cause_id == "api_disk_full"
    assert any("filesystem usage is 100%" in c.text for c in t.claims)
    assert any("not identified" in u for u in t.unknowns)  # the volume is shared, the filler is unknown
    assert d.recommended_action.action_id == "escalate"  # restarting does not free the disk


def test_db_saturation_when_the_probe_is_locked_out_still_names_exhaustion(world, catalog, cfg):
    """At the connection limit the probe itself is refused, so the counts vanish exactly when they matter; the refusal flag remains."""
    import copy

    from fixtures import scenarios
    data = copy.deepcopy(scenarios.ALL["db_saturation"]())
    for metric in ("db_connections", "db_connections_by_client"):
        data["samples"]["app-db"][metric] = [s for s in data["samples"]["app-db"][metric] if s[0] < 68]  # series end when the limit is reached
    d, _, _ = diagnose(world, catalog, cfg, data, 150)
    t = top(d)
    assert t.cause_id == "app_db_connection_exhaustion"
    assert any("refused the monitoring connection" in c.text for c in t.claims)
    assert not any("of 100 allowed connections" in c.text and "100%" not in c.text for c in t.claims)


def test_stale_low_counts_do_not_contradict_a_refused_probe(world, catalog, cfg):
    """Seen live: the probe was refused, but Prometheus still returned an old low count (1 of 100, 'unknown'); that stale sample must
    not count as a contradiction or name a leaker."""
    import copy

    from fixtures import scenarios
    data = copy.deepcopy(scenarios.ALL["db_saturation"]())
    for metric in ("db_connections", "db_connections_by_client"):
        data["samples"]["app-db"][metric] = [[t, 1] if metric == "db_connections" else s for s in data["samples"]["app-db"][metric] if (t := s[0]) < 10] \
            if metric == "db_connections" else [s for s in data["samples"]["app-db"][metric] if s[0] < 10]
    d, _, _ = diagnose(world, catalog, cfg, data, 150)
    t = top(d)
    assert t.cause_id == "app_db_connection_exhaustion"
    assert not any("uses only" in c.text for c in t.contradicting)
    assert not any("likely leaker" in c.text for c in t.claims)
    assert any("counts and the leaking client are unavailable" in u for u in t.unknowns)
