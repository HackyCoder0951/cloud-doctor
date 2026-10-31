import json
import os
import socketserver
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler

import pytest
from stack import KEY, key_file

from backend import policy_adapter as pa
from backend.domain.clock import FakeClock, iso, parse_ts
from backend.domain.contracts import validate_against_contract
from backend.remediation.actuator import ActuatorUnavailable, InProcessFakeActuator, UnixSocketActuatorClient
from backend.remediation.signing import SigningUnavailable, load_key, sign_plan

NOW = parse_ts("2026-11-02T09:02:00Z")


def mkplan(action="restart_service", params=None, risk="low", refs=("EV-001",), incident="INC-0001", **kw):
    p = {"plan_id": "PL-0001", "incident_id": incident, "action_id": action, "params": params or {"service": "worker"}, "risk_class": risk,
         "origin": "rule", "evidence_refs": list(refs), "rationale": "test", "created_at": iso(NOW)}
    p.update(kw)
    p["plan_hash"] = pa.plan_hash(p)
    return p


def ctx(catalog, **kw):
    base = dict(catalog=catalog, now=NOW, attempts_used=lambda i, s, a: 0, last_attempt_at=lambda i, s, a: None, circuit_open=lambda i: False,
                known_evidence_ids={"EV-001"}, diagnosis_validated=True, top_cause_service="worker", approval=None)
    base.update(kw)
    return pa.make_context(**base)


@pytest.mark.skipif(pa.IS_REAL, reason="asserts the local stub; the real package is covered by tests/invariants")
def test_adapter_uses_stub_and_says_so():
    assert pa.IS_REAL is False and pa.VERSION.startswith("inv-stub")
    assert "STUB" in pa.__doc__


def test_stub_allows_a_clean_low_risk_restart(catalog):
    r = pa.evaluate(mkplan(), ctx(catalog))
    assert (r.final, r.rule_ids) == ("allow", [])


@pytest.mark.skipif(pa.IS_REAL, reason="asserts the local stub; the real package is covered by tests/invariants")
@pytest.mark.parametrize("name,plan_kw,ctx_kw,rule", [
    ("unknown action", dict(action="run_shell"), {}, "I-01"),
    ("extra param", dict(params={"service": "worker", "cmd": "rm -rf /"}), {}, "I-01"),
    ("not in catalog", dict(params={"service": "evil"}), {}, "I-06"),
    ("action not allowed for service", dict(params={"service": "app-db"}), {}, "I-02"),
    ("high risk", dict(risk="high"), {}, "I-03"),
    ("risk below catalogue", dict(params={"service": "redis"}, risk="low"), dict(top_cause_service="redis"), "I-03"),
    ("attempts exhausted", {}, dict(attempts_used=lambda i, s, a: 2), "I-04"),
    ("circuit open", {}, dict(circuit_open=lambda i: True), "I-04"),
    ("cooldown", {}, dict(last_attempt_at=lambda i, s, a: NOW - timedelta(seconds=5)), "I-04"),
    ("unknown evidence", dict(refs=("EV-999",)), {}, "I-05"),
    ("diagnosis not validated", {}, dict(diagnosis_validated=False), "I-05"),
    ("victim restart", {}, dict(top_cause_service="redis"), "I-07"),
])
def test_stub_denies(catalog, name, plan_kw, ctx_kw, rule):
    r = pa.evaluate(mkplan(**plan_kw), ctx(catalog, **ctx_kw))
    assert r.final == "deny" and rule in r.rule_ids, (name, r)


def test_stub_tampered_plan_hash_is_denied(catalog):
    p = mkplan()
    p["rationale"] = "changed after hashing"
    assert "I-01" in pa.evaluate(p, ctx(catalog)).rule_ids


@pytest.mark.skipif(pa.IS_REAL, reason="asserts the local stub; the real package is covered by tests/invariants")
def test_stub_medium_needs_bound_approval(catalog):
    p = mkplan(params={"service": "redis"}, risk="medium")
    c = ctx(catalog, top_cause_service="redis")
    assert pa.evaluate(p, c).final == "allow_with_approval"
    good = {"approver": "a", "approved_at": iso(NOW), "plan_hash": p["plan_hash"]}
    assert pa.evaluate(p, ctx(catalog, top_cause_service="redis", approval=good)).final == "allow"
    bad = dict(good, plan_hash="sha256:" + "1" * 64)
    assert pa.evaluate(p, ctx(catalog, top_cause_service="redis", approval=bad)).final == "allow_with_approval"


def test_internal_error_denies_i08(catalog):
    def boom(i, s, a):
        raise RuntimeError("x")

    r = pa.evaluate(mkplan(), ctx(catalog, attempts_used=boom))
    assert r.final == "deny" and "I-08" in r.rule_ids


def test_signing_key_from_file_only(tmp_path, monkeypatch):
    monkeypatch.delenv("CD_SIGNING_KEY_FILE", raising=False)
    with pytest.raises(SigningUnavailable):
        load_key()
    monkeypatch.setenv("CD_SIGNING_KEY_FILE", key_file(tmp_path))
    assert load_key() == KEY
    with pytest.raises(SigningUnavailable):
        load_key(key_file(tmp_path, mode=0o644))  # readable by others -> refuse
    with pytest.raises(SigningUnavailable):
        load_key(key_file(tmp_path, content=b"short"))
    with pytest.raises(SigningUnavailable):
        load_key(str(tmp_path / "missing"))


def test_signed_plan_envelope_contract_and_hmac():
    sp = sign_plan(mkplan(), KEY, NOW)
    validate_against_contract(sp, "signed_plan")
    body = {k: v for k, v in sp.items() if k != "signature"}
    import hashlib, hmac
    assert sp["signature"] == hmac.new(KEY, pa.canonical_json(body), hashlib.sha256).hexdigest()
    assert pa.verify_envelope(sp, KEY) and not pa.verify_envelope(sp, b"another-key-0123456789abc")
    sp2 = dict(sp, plan=dict(sp["plan"], rationale="tampered"))
    assert not pa.verify_envelope(sp2, KEY)
    assert sign_plan(mkplan(), KEY, NOW)["nonce"] != sp["nonce"]


def test_fake_actuator_checks_signature_expiry_replay_idempotency(catalog):
    clock = FakeClock(NOW)
    act = InProcessFakeActuator(catalog, KEY, clock)
    sp = sign_plan(mkplan(), KEY, NOW)
    assert act.validate(sp)["ok"]
    ex = act.execute(sp, "idem-key-0001")
    validate_against_contract({"execution": ex.to_contract()}, "actuator", "#/$defs/execute_response")
    assert ex.result == "success" and ex.executed_argv == ["docker", "restart", "cd-worker"]
    assert act.execute(sp, "idem-key-0001") == ex and len(act.commands) == 1  # idempotent
    replay = act.execute(sp, "idem-key-0002")
    assert replay.result == "refused" and len(act.commands) == 1  # nonce replay
    bad = dict(sp, signature="0" * 64)
    assert act.execute(bad, "idem-key-0003").result == "refused"
    clock.sleep(600)
    assert act.execute(sign_plan(mkplan(), KEY, NOW), "idem-key-0004").result == "refused"  # expired
    assert len(act.commands) == 1


def test_fake_actuator_uses_fixed_argv_never_shell(catalog):
    seen = []
    act = InProcessFakeActuator(catalog, KEY, FakeClock(NOW), runner=lambda argv: (seen.append(argv) or (0, "")))
    act.execute(sign_plan(mkplan(), KEY, NOW), "idem-key-0001")
    assert seen == [["docker", "restart", "cd-worker"]] and isinstance(seen[0], list)


class _UnixHTTPServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def serve(path, handler_fn):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def address_string(self):
            return "unix"

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            code, obj = handler_fn("GET", self.path, None)
            self._send(code, obj)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            code, obj = handler_fn("POST", self.path, body)
            self._send(code, obj)

    srv = _UnixHTTPServer(path, H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_unix_socket_client_follows_actuator_openapi(tmp_path):
    sock = str(tmp_path / "act.sock")
    sp = sign_plan(mkplan(), KEY, NOW)
    calls = []

    def handler(method, path, body):
        calls.append((method, path, body))
        if path == "/healthz":
            return 200, {"state": "ok", "invariants_version": "inv-x"}
        if path == "/v1/validate":
            return 200, {"ok": True, "rule_ids": [], "reasons": [], "invariants_version": "inv-x"}
        if path == "/v1/execute":
            return 200, {"execution": {"execution_id": "EX-0001", "plan_id": "PL-0001", "idempotency_key": body["idempotency_key"],
                                       "started_at": iso(NOW), "result": "success", "executed_argv": ["docker", "restart", "cd-worker"]}}
        return 404, {}

    srv = serve(sock, handler)
    try:
        c = UnixSocketActuatorClient(sock)
        assert c.health()["state"] == "ok"
        assert c.validate(sp)["ok"] is True
        ex = c.execute(sp, "idem-key-0001")
        assert ex.result == "success" and ex.executed_argv == ["docker", "restart", "cd-worker"]
        assert ("POST", "/v1/execute") in [(m, p) for m, p, _ in calls]
        assert calls[-1][2] == {"signed_plan": sp, "idempotency_key": "idem-key-0001"}
    finally:
        srv.shutdown()
        srv.server_close()


def test_unix_socket_client_fails_closed(tmp_path):
    with pytest.raises(ActuatorUnavailable):
        UnixSocketActuatorClient(str(tmp_path / "nothing.sock")).validate(sign_plan(mkplan(), KEY, NOW))
    sock = str(tmp_path / "bad.sock")
    srv = serve(sock, lambda m, p, b: (200, {"unexpected": True}) if p != "/v1/validate" else (500, {}))
    try:
        c = UnixSocketActuatorClient(sock)
        with pytest.raises(ActuatorUnavailable):
            c.validate(sign_plan(mkplan(), KEY, NOW))  # HTTP 500
        with pytest.raises(ActuatorUnavailable):
            c.execute(sign_plan(mkplan(), KEY, NOW), "idem-key-0001")  # response violates the contract
    finally:
        srv.shutdown()
        srv.server_close()
