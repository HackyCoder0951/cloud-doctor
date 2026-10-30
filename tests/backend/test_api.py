import json
import os
import re

import pytest
from fastapi.testclient import TestClient
from helpers import run_detector
from stack import KEY

from backend.api.app import Settings, create_app
from backend.domain.clock import FakeClock
from backend.domain.contracts import validate_against_contract
from backend.remediation.actuator import InProcessFakeActuator
from backend.repositories import MemoryRepository
from backend.services import build_services
from backend.verifier import VerifierConfig

TOKEN = "correct-horse-battery-staple"
IK = lambda n: {"Idempotency-Key": f"idem-key-{n:04d}"}  # noqa: E731


@pytest.fixture()
def token_file(tmp_path, monkeypatch):
    p = tmp_path / "token"
    p.write_text(TOKEN + "\n")
    os.chmod(p, 0o600)
    monkeypatch.setenv("CD_SESSION_TOKEN_FILE", str(p))
    return p


def make_client(world, catalog, cfg, name="redis_outage_recovered", until=140, with_actuator=True, settings=None, actuator=None):
    w = world(name)
    clock = FakeClock(w.scenario.at(5))
    act = actuator or (InProcessFakeActuator(catalog, KEY, clock) if with_actuator else None)
    svc = build_services(MemoryRepository(), catalog, cfg, clock, w.prom, w.logs, w.feed, w.prober, act, key_loader=lambda: KEY,
                         vcfg=VerifierConfig(10, 30, 5))
    app = create_app(svc, settings or Settings(sse_max_idle_seconds=0.2))  # listeners attach before events happen
    t = 5
    while t <= until:
        clock.set(w.scenario.at(t))
        svc.mgr.ingest(svc.detector.poll(clock.now()))
        t += 5
    return TestClient(app, base_url="https://testserver", raise_server_exceptions=False), svc, w


def login(c):
    r = c.post("/api/v1/auth/login", json={"token": TOKEN})
    assert r.status_code == 204
    return r


def test_login_cookie_attributes_and_auth_required(world, catalog, cfg, token_file):
    c, svc, _ = make_client(world, catalog, cfg)
    assert c.get("/api/v1/services").status_code == 401
    bad = c.post("/api/v1/auth/login", json={"token": "wrong-token-value"})
    assert bad.status_code == 401 and set(bad.json()) <= {"code", "message", "rule_ids"}
    r = login(c)
    sc = r.headers["set-cookie"].lower()
    assert "cd_session=" in sc and "httponly" in sc and "secure" in sc and "samesite=lax" in sc
    assert c.get("/api/v1/services").status_code == 200
    assert c.post("/api/v1/auth/logout").status_code == 204
    assert c.get("/api/v1/services").status_code == 401


def test_login_fails_closed_without_token_file_and_rate_limits(world, catalog, cfg, monkeypatch, token_file):
    c, *_ = make_client(world, catalog, cfg, settings=Settings(login_max_failures=3))
    for _ in range(3):
        assert c.post("/api/v1/auth/login", json={"token": "wrong-token-value"}).status_code == 401
    assert c.post("/api/v1/auth/login", json={"token": TOKEN}).status_code == 429
    monkeypatch.delenv("CD_SESSION_TOKEN_FILE")
    c2, *_ = make_client(world, catalog, cfg)
    assert c2.post("/api/v1/auth/login", json={"token": TOKEN}).status_code == 503
    assert c2.post("/api/v1/auth/login", json={"token": "x"}).status_code == 422  # minLength 8


def test_read_endpoints_conform_to_contracts(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    iid = c.get("/api/v1/incidents").json()[0]["incident_id"]
    svc.engine.diagnose(iid)
    for inc in c.get("/api/v1/incidents").json():
        validate_against_contract(inc, "incident")
    assert c.get("/api/v1/incidents", params={"state": "bogus"}).status_code == 422
    for e in c.get(f"/api/v1/incidents/{iid}/timeline").json():
        validate_against_contract(e, "incident", "#/$defs/timeline_event")
    ev = c.get(f"/api/v1/incidents/{iid}/evidence").json()
    assert ev and all(validate_against_contract(e, "evidence") is None for e in ev)
    validate_against_contract(c.get(f"/api/v1/incidents/{iid}/diagnosis").json(), "diagnosis")
    rem = c.get(f"/api/v1/incidents/{iid}/remediation").json()
    assert set(rem) >= {"plans", "decisions", "executions"}
    rep = c.get(f"/api/v1/incidents/{iid}/report")
    validate_against_contract(rep.json(), "report")
    md = c.get(f"/api/v1/incidents/{iid}/report", headers={"Accept": "text/markdown"})
    assert md.headers["content-type"].startswith("text/markdown") and md.text.startswith("# Incident report")
    audit = c.get("/api/v1/audit").json()
    assert audit["chain_valid"] is True and audit["events"]
    for a in audit["events"]:
        validate_against_contract(a, "audit_event")
    svcs = c.get("/api/v1/services").json()
    assert {s["name"] for s in svcs} == set(catalog.names())
    redis = [s for s in svcs if s["name"] == "redis"][0]
    assert redis["state"] == "UNHEALTHY" and iid in redis["open_incident_ids"]
    topo = c.get("/api/v1/topology").json()
    assert {"from": "api", "to": "redis", "kind": "hard"} in topo["edges"]
    assert c.get("/api/v1/services/nope/health").status_code == 404
    assert c.get("/api/v1/incidents/INC-9999").status_code == 404
    assert c.get("/api/v1/incidents/garbage").status_code == 404


def test_metrics_and_logs_endpoints(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    m = c.get("/api/v1/services/api/metrics", params={"name": "error_ratio", "since_seconds": 120}).json()
    assert m["status"] == "ok" and m["points"] and set(m["points"][0]) == {"t", "v"}
    assert c.get("/api/v1/services/api/metrics", params={"name": "nope"}).status_code == 422
    assert c.get("/api/v1/services/api/metrics", params={"name": "up", "since_seconds": 5}).status_code == 422
    lg = c.get("/api/v1/services/api/logs", params={"limit": 5}).json()
    assert lg["status"] == "ok" and 0 < len(lg["lines"]) <= 5


def test_failed_collection_is_error_not_empty_in_api(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg, name="redis_outage_telemetry_failure", until=125)
    svc.clock.set(w.scenario.at(150))
    login(c)
    m = c.get("/api/v1/services/api/metrics", params={"name": "error_ratio"}).json()
    assert m["status"] == "timeout" and m["points"] == []
    assert c.get("/api/v1/services/api/logs").json()["status"] == "error"
    services = c.get("/api/v1/status").json()
    assert services["state"] == "degraded"


def test_mutating_routes_require_idempotency_key_and_replay(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    iid = c.get("/api/v1/incidents").json()[0]["incident_id"]
    assert c.post(f"/api/v1/incidents/{iid}/diagnose").status_code == 400
    assert c.post(f"/api/v1/incidents/{iid}/diagnose", headers={"Idempotency-Key": "short"}).status_code == 400
    r1 = c.post(f"/api/v1/incidents/{iid}/diagnose", headers=IK(1))
    r2 = c.post(f"/api/v1/incidents/{iid}/diagnose", headers=IK(1))
    assert r1.status_code == r2.status_code == 202
    n = len([e for e in svc.repo.all_audit() if e.event == "diagnose.requested"])
    assert n == 1  # replay did not repeat the side effect
    svc.engine.diagnose(iid)
    plan_body = {"plan_hash": "sha256:" + "a" * 64, "reason": "ok to restart"}
    for path in ("approve", "reject"):
        body = plan_body if path == "approve" else {"reason": "no"}
        assert c.post(f"/api/v1/incidents/{iid}/remediation/plans/PL-0001/{path}", json=body).status_code == 400


def test_approve_bound_to_plan_hash_then_executes(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    iid = c.get("/api/v1/incidents").json()[0]["incident_id"]
    svc.engine.diagnose(iid)
    assert svc.engine.run(iid) == "AwaitingApproval"
    plan = c.get(f"/api/v1/incidents/{iid}/remediation").json()["plans"][0]
    base = f"/api/v1/incidents/{iid}/remediation/plans/{plan['plan_id']}"
    r = c.post(f"{base}/approve", headers=IK(10), json={"plan_hash": "sha256:" + "0" * 64, "reason": "wrong hash"})
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert svc.actuator.commands == []
    assert c.post(f"{base}/approve", headers=IK(11), json={"plan_hash": plan["plan_hash"]}).status_code == 422
    assert c.post(f"{base}/approve", headers=IK(12), json={"plan_hash": plan["plan_hash"], "reason": "ok", "extra": 1}).status_code == 422
    svc.clock.set(w.scenario.at(142))
    ok = c.post(f"{base}/approve", headers=IK(13), json={"plan_hash": plan["plan_hash"], "reason": "ok to restart redis"})
    assert ok.status_code == 200
    validate_against_contract(ok.json(), "decision")
    assert svc.actuator.commands == [["docker", "restart", "cd-redis"]]  # queued run happened after the response
    again = c.post(f"{base}/approve", headers=IK(13), json={"plan_hash": plan["plan_hash"], "reason": "ok to restart redis"})
    assert again.status_code == 200 and again.json() == ok.json() and len(svc.actuator.commands) == 1
    clash = c.post(f"{base}/approve", headers=IK(13), json={"plan_hash": plan["plan_hash"], "reason": "different body"})
    assert clash.status_code == 409 and clash.json()["code"] == "idempotency_key_reused"
    assert c.post(f"/api/v1/incidents/{iid}/remediation/plans/PL-0099/reject", headers=IK(14), json={"reason": "nope"}).status_code in (404, 409)
    verdicts = [v["verdict"] for v in c.get(f"/api/v1/incidents/{iid}/verification").json()]
    assert verdicts[-1] == "recovered" and "regression" not in verdicts  # an early 'partial' window may precede the recovered one
    inc = c.get(f"/api/v1/incidents/{iid}").json()
    assert inc["state"] == "recovered" and inc["root_cause_confirmed"] is False


def test_reject_route(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    iid = c.get("/api/v1/incidents").json()[0]["incident_id"]
    svc.engine.diagnose(iid)
    svc.engine.run(iid)
    pid = c.get(f"/api/v1/incidents/{iid}/remediation").json()["plans"][0]["plan_id"]
    r = c.post(f"/api/v1/incidents/{iid}/remediation/plans/{pid}/reject", headers=IK(20), json={"reason": "not now"})
    assert r.status_code == 200
    assert c.get(f"/api/v1/incidents/{iid}").json()["state"] == "escalated"
    assert c.post(f"/api/v1/incidents/{iid}/remediation/plans/{pid}/reject", headers=IK(21), json={"reason": "again"}).status_code == 409


def test_error_bodies_do_not_leak_internals(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    svc.repo.list_incidents = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret path /etc/passwd SELECT * FROM x"))
    r = c.get("/api/v1/incidents")
    assert r.status_code == 500 and r.json() == {"code": "internal_error", "message": "internal error"}
    bad = c.post("/api/v1/auth/login", content="{not json", headers={"content-type": "application/json"})
    assert bad.status_code == 422 and "not json" not in bad.text
    nf = c.get("/api/v1/nonexistent")
    assert nf.status_code == 404 and set(nf.json()) == {"code", "message"}
    assert "traceback" not in nf.text.lower()


def test_status_reports_degraded_and_fail_closed(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    s = c.get("/api/v1/status")  # no auth needed
    assert s.status_code == 200
    body = s.json()
    assert {d["name"] for d in body["dependencies"]} == {"prometheus", "logs", "database", "actuator", "policy_layer2", "llm"}
    assert any("LOCAL STUB" in d.get("detail", "") for d in body["dependencies"] if d["name"] == "policy_layer2")
    svc.actuator.available = False
    assert c.get("/api/v1/status").json()["state"] == "fail_closed"
    c2, *_ = make_client(world, catalog, cfg, with_actuator=False)
    d = {x["name"]: x["state"] for x in c2.get("/api/v1/status").json()["dependencies"]}
    assert d["actuator"] == "disabled" and d["llm"] == "disabled"


def test_remediation_unavailable_without_actuator_fails_closed(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg, with_actuator=False)
    login(c)
    iid = c.get("/api/v1/incidents").json()[0]["incident_id"]
    r = c.post(f"/api/v1/incidents/{iid}/remediation/plans/PL-0001/approve", headers=IK(1), json={"plan_hash": "sha256:" + "0" * 64, "reason": "okay"})
    assert r.status_code == 503


def test_sse_stream_emits_stream_events_and_supports_last_event_id(world, catalog, cfg, token_file):
    c, svc, w = make_client(world, catalog, cfg)
    login(c)
    with c.stream("GET", "/api/v1/stream") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [json.loads(m) for m in re.findall(r"^data: (.*)$", body, re.M)]
    ids = re.findall(r"^id: (\d+)$", body, re.M)
    assert events and len(ids) == len(events)
    for e in events:
        assert e["type"] in {"incident.opened", "incident.updated", "plan.created", "decision.recorded", "execution.finished",
                             "verification.finished", "timeline.event", "service.health", "status.changed"} and "at" in e
    assert any(e["type"] == "incident.opened" for e in events)
    last = ids[-1]
    with c.stream("GET", "/api/v1/stream", headers={"Last-Event-ID": last}) as r2:
        assert "".join(r2.iter_text()).count("data:") == 0


def test_sse_requires_auth(world, catalog, cfg, token_file):
    c, *_ = make_client(world, catalog, cfg)
    assert c.get("/api/v1/stream").status_code == 401


def test_every_openapi_operation_is_implemented(world, catalog, cfg):
    import yaml
    from pathlib import Path

    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts/openapi.yaml").read_text())
    want = {(m.upper(), "/api/v1" + p) for p, v in spec["paths"].items() for m in v if m in ("get", "post")}
    c, *_ = make_client(world, catalog, cfg)
    have = {(m, r.path) for r in c.app.routes if hasattr(r, "methods") for m in r.methods if m in ("GET", "POST")}
    assert want <= have
