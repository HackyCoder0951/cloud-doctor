import copy
import json
import os

import pytest

import invariants as inv
from actuator.audit import AuditError, FileAuditSink, verify_chain
from actuator.core import Actuator, BadRequest, KeyFile
from actuator.executor import DockerExecutor
from act_helpers import KEY, FakeRunner, Rig, write_key
from inv_helpers import approval_for, make_plan


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def refused(ex, *rules):
    assert ex["result"] == "refused", ex
    assert ex["executed_argv"] == []
    for r in rules:
        assert r in ex["refusal_rule_ids"], ex
    return ex


# ---- happy path ----------------------------------------------------------------------------
def test_low_risk_restart_executes_fixed_argv(rig):
    ex = rig.execute()
    assert ex["result"] == "success" and ex["executed_argv"] == ["docker", "restart", "cd-api"]
    assert rig.runner.calls == [
        ["docker", "inspect", "--format", "{{json .Config.Labels}}", "cd-api"],
        ["docker", "restart", "cd-api"]]
    assert ex["plan_id"] == "PL-0001" and ex["idempotency_key"] == "idem-0000001"


def test_execution_record_matches_contract_schema(rig):
    jsonschema = pytest.importorskip("jsonschema")
    import pathlib
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    root = pathlib.Path(__file__).resolve().parents[2] / "contracts/schemas"
    schemas = {p.stem: json.loads(p.read_text()) for p in root.glob("*.json")}
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas.values()])
    v = lambda name: jsonschema.Draft202012Validator(schemas[name], registry=reg, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    ok = rig.execute()
    bad = rig.execute(rig.signed(make_plan(params={"service": "ghost"})), idem="idem-0000002")
    assert not list(v("execution").iter_errors(ok)) and not list(v("execution").iter_errors(bad))
    for ev in rig.audit_events():
        assert not list(v("audit_event").iter_errors(ev)), ev
    s = rig.signed()
    assert not list(v("signed_plan").iter_errors(s))
    resp = rig.actuator.validate({"signed_plan": rig.signed(nonce="validatenonce0001")})
    assert not list(jsonschema.Draft202012Validator({"$ref": "https://cloud-doctor.local/schemas/actuator.json#/$defs/validate_response"}, registry=reg).iter_errors(resp))


def test_medium_risk_with_bound_approval_executes(rig):
    plan = make_plan(params={"service": "redis"}, risk="medium")
    ex = rig.execute(rig.signed(plan, approval=approval_for(plan, approved_at="2026-11-02T09:00:10Z")))
    assert ex["result"] == "success" and ex["executed_argv"] == ["docker", "restart", "cd-redis"]


# ---- signature / key -------------------------------------------------------------------------
def test_tampered_plan_after_signing_refused(rig):
    s = rig.signed()
    s["plan"] = copy.deepcopy(s["plan"])
    s["plan"]["params"]["service"] = "worker"
    refused(rig.execute(s), "A-SIGNATURE")
    assert rig.runner.calls == []


@pytest.mark.parametrize("field,val", [("nonce", "z" * 20), ("expires_at", "2030-01-01T00:00:00Z"),
                                       ("issued_at", "2026-11-02T09:00:00Z")])
def test_tampered_envelope_fields_refused(rig, field, val):
    s = rig.signed()
    s[field] = val
    refused(rig.execute(s), "A-SIGNATURE")
    assert rig.runner.calls == []


def test_plan_that_is_not_an_object_is_a_bad_request(rig):
    s = rig.signed()
    s["plan"] = "not a plan"
    with pytest.raises(BadRequest):
        rig.execute(s)


def test_wrong_key_refused(rig):
    refused(rig.execute(rig.signed(key=b"another-key-0123456789abcdef")), "A-SIGNATURE")


def test_unknown_key_id_refused(rig):
    refused(rig.execute(rig.signed(key_id="other-key")), "A-KEY")


def test_missing_or_short_key_file_refused_and_health_degraded(tmp_path):
    rig = Rig(tmp_path)
    os.unlink(rig.key_path)
    refused(rig.execute(rig.signed()), "A-KEY")
    assert rig.actuator.degraded_reason == "signing key unavailable"


def test_insecure_key_file_mode_rejected(tmp_path):
    p = write_key(tmp_path, mode=0o644)
    with pytest.raises(PermissionError):
        KeyFile(str(p)).get()
    p2 = write_key(tmp_path, key=b"short", mode=0o600)
    with pytest.raises(ValueError):
        KeyFile(str(p2)).get()


@pytest.mark.parametrize("mutate", [
    lambda s: s.pop("nonce"), lambda s: s.update(extra=1), lambda s: s.update(signature="xyz"),
    lambda s: s.update(nonce="short"), lambda s: s.update(issued_at="soon"),
    lambda s: s.update(approval="yes"), lambda s: s.update(key_id="bad key!"),
])
def test_malformed_envelopes_refused(rig, mutate):
    s = rig.signed()
    mutate(s)
    refused(rig.execute(s), "A-ENVELOPE")
    assert rig.runner.calls == []


# ---- time window -----------------------------------------------------------------------------
def test_expired_plan_refused(rig):
    s = rig.signed(ttl=60)
    rig.clock.advance(61)
    refused(rig.execute(s), "A-EXPIRED")


def test_future_dated_plan_refused(rig):
    from datetime import timedelta
    refused(rig.execute(rig.signed(now=rig.clock() + timedelta(hours=1))), "A-NOT-YET-VALID")


def test_overlong_or_inverted_window_refused(rig):
    refused(rig.execute(rig.signed(ttl=100000)), "A-LIFETIME")
    refused(rig.execute(rig.signed(ttl=-5), idem="idem-0000002"), "A-EXPIRED")


# ---- nonce replay / hash / approval ----------------------------------------------------------
def test_replayed_nonce_with_new_idempotency_key_refused(rig):
    s = rig.signed()
    assert rig.execute(s, idem="idem-aaaaaaa1")["result"] == "success"
    refused(rig.execute(s, idem="idem-aaaaaaa2"), "A-REPLAY")
    assert len(rig.runner.restarts) == 1


def test_same_nonce_in_new_envelope_still_replay(rig):
    assert rig.execute(rig.signed(nonce="fixednonce0000001"), idem="idem-aaaaaaa1")["result"] == "success"
    rig.clock.advance(30)
    refused(rig.execute(rig.signed(nonce="fixednonce0000001"), idem="idem-aaaaaaa2"), "A-REPLAY")


def test_plan_hash_mismatch_with_valid_signature_refused(rig):
    plan = make_plan()
    plan["rationale"] = "changed after hashing"            # signed by the key holder but hash is stale
    refused(rig.execute(rig.signed(plan)), "A-HASH", "I-01")
    assert rig.runner.restarts == []


def test_approval_bound_to_other_plan_refused(rig):
    plan = make_plan(params={"service": "redis"}, risk="medium")
    other = make_plan(params={"service": "redis"}, risk="medium", rationale="other")
    refused(rig.execute(rig.signed(plan, approval=approval_for(other))), "A-APPROVAL", "I-03")
    assert rig.runner.restarts == []


def test_medium_risk_without_approval_refused(rig):
    plan = make_plan(params={"service": "redis"}, risk="medium")
    refused(rig.execute(rig.signed(plan)), "I-03")
    assert rig.runner.restarts == []


def test_high_risk_with_approval_still_refused(rig):
    plan = make_plan(params={"service": "app-db"}, risk="high")
    refused(rig.execute(rig.signed(plan, approval=approval_for(plan))), "I-03")
    assert rig.runner.restarts == []


# ---- Layer 1 re-run --------------------------------------------------------------------------
@pytest.mark.parametrize("plan,rule", [
    (make_plan(action="run_shell"), "I-01"),
    (make_plan(params={"service": "api", "cmd": "id"}), "I-01"),
    (make_plan(params={"service": "api; id"}), "I-06"),
    (make_plan(params={"service": "../etc"}), "I-06"),
    (make_plan(params={"service": "ghost"}), "I-02"),
    (make_plan("scale_service", {"service": "api", "replicas": 500}, risk="medium"), "I-01"),
])
def test_adversarial_plans_refused_before_any_docker_call(rig, plan, rule):
    refused(rig.execute(rig.signed(plan)), rule)
    assert [c for c in rig.runner.calls if c[1] == "restart"] == []


def test_unlabeled_container_refused(tmp_path):
    rig = Rig(tmp_path, runner=FakeRunner(labels={"other": "x"}))
    refused(rig.execute(), "I-02")
    assert rig.runner.restarts == []


def test_container_with_null_labels_refused(tmp_path):
    runner = FakeRunner()
    runner.per_container["cd-api"] = None      # docker prints `null` for a container without labels
    refused(Rig(tmp_path, runner=runner).execute(), "I-02")


def test_docker_inspect_failure_refused(tmp_path):
    rig = Rig(tmp_path, runner=FakeRunner(inspect_rc=1))
    refused(rig.execute(), "I-02")
    (tmp_path / "b").mkdir()
    rig2 = Rig(tmp_path / "b", runner=FakeRunner(raise_on="inspect"))
    refused(rig2.execute(), "I-02")


def test_non_restart_actions_not_executable_in_mvp(rig):
    plan = make_plan("rollback_service", {"service": "api", "version": "1.2.3"}, risk="medium")
    ex = rig.execute(rig.signed(plan, approval=approval_for(plan)))
    refused(ex, "A-UNSUPPORTED")
    esc = rig.execute(rig.signed(make_plan("escalate", {"reason": "human please"})), idem="idem-0000002")
    refused(esc, "A-UNSUPPORTED")
    assert rig.runner.restarts == []


def test_container_not_in_catalog_refused_by_executor(rig):
    ex = DockerExecutor(FakeRunner(), rig.cat)
    for name in ["cd-ghost", "cd-api; id", "cd-api\n", "../cd-api", "CD-API", "cd-", "", None, "cd-api --privileged", "-cd-api"]:
        with pytest.raises(Exception):
            ex.restart(name)
        with pytest.raises(Exception):
            ex.labels(name)


def test_executor_argv_has_no_privileged_flags_or_exec(rig):
    rig.execute()
    for argv in rig.runner.calls:
        assert argv[0] == "docker" and argv[1] in ("inspect", "restart")
        assert not any(a.startswith("--privileged") or a in ("exec", "run", "-v", "--volume", "--mount") for a in argv)


# ---- attempts, cooldown, circuit breaker -----------------------------------------------------
def test_cooldown_then_attempt_budget(rig):
    assert rig.execute(idem="idem-0000001")["result"] == "success"
    refused(rig.execute(idem="idem-0000002"), "I-04")                 # inside the 20 s cooldown
    rig.clock.advance(21)
    assert rig.execute(idem="idem-0000003")["result"] == "success"   # second attempt
    rig.clock.advance(21)
    refused(rig.execute(idem="idem-0000004"), "I-04")                 # budget of 2 spent
    assert len(rig.runner.restarts) == 2


def test_failed_restarts_open_the_circuit(tmp_path):
    rig = Rig(tmp_path, runner=FakeRunner(restart_rc=1))
    assert rig.execute(idem="idem-0000001")["result"] == "failed"
    rig.clock.advance(21)
    assert rig.execute(idem="idem-0000002")["result"] == "failed"
    rig.clock.advance(21)
    # a different service in the same incident is also blocked: circuit open
    ex = rig.execute(rig.signed(make_plan(params={"service": "worker"})), idem="idem-0000003")
    refused(ex, "I-04")
    assert len(rig.runner.restarts) == 2


def test_command_timeout_is_a_failed_execution_not_a_crash(tmp_path):
    rig = Rig(tmp_path, runner=FakeRunner(raise_on="restart"))
    ex = rig.execute()
    assert ex["result"] == "failed" and "not completed" in ex["detail"]


# ---- idempotency -----------------------------------------------------------------------------
def test_idempotent_replay_returns_original_and_never_reexecutes(rig):
    s = rig.signed()
    first = rig.execute(s, idem="idem-abcdefg1")
    again = rig.execute(s, idem="idem-abcdefg1")
    assert again == first and len(rig.runner.restarts) == 1
    rig.clock.advance(3600)                                   # even after the envelope expired
    assert rig.execute(s, idem="idem-abcdefg1") == first and len(rig.runner.restarts) == 1


def test_idempotency_key_reuse_with_different_request_refused(rig):
    rig.execute(idem="idem-abcdefg1")
    refused(rig.execute(rig.signed(make_plan(params={"service": "worker"})), idem="idem-abcdefg1"), "A-IDEMPOTENCY")
    assert len(rig.runner.restarts) == 1


def test_refusals_do_not_consume_the_idempotency_key(rig):
    s = rig.signed(ttl=60)
    rig.clock.advance(120)
    refused(rig.execute(s, idem="idem-abcdefg1"), "A-EXPIRED")
    assert rig.execute(rig.signed(), idem="idem-abcdefg1")["result"] == "success"


# ---- bad requests ----------------------------------------------------------------------------
@pytest.mark.parametrize("req", [None, [], {}, {"signed_plan": {}}, {"signed_plan": {}, "idempotency_key": "x"},
                                 {"signed_plan": {"plan": {"plan_id": "bad"}}, "idempotency_key": "idem-0000001"},
                                 {"signed_plan": {"plan": {"plan_id": "PL-0001"}}, "idempotency_key": "idem-0000001", "x": 1}])
def test_malformed_requests_are_bad_request(rig, req):
    with pytest.raises(BadRequest):
        rig.actuator.execute(req)
    with pytest.raises(BadRequest):
        rig.actuator.validate(req if not isinstance(req, dict) or "idempotency_key" in req else {"x": 1})


def test_unexpected_exception_fails_closed(rig, monkeypatch):
    monkeypatch.setattr(rig.actuator, "_assess", lambda s: 1 / 0)
    ex = rig.execute()
    refused(ex, "I-08")
    assert rig.runner.calls == []
    v = rig.actuator.validate({"signed_plan": rig.signed()})
    assert v["ok"] is False and v["rule_ids"] == ["I-08"]


# ---- validate is a dry run --------------------------------------------------------------------
def test_validate_has_no_side_effects(rig):
    s = rig.signed()
    for _ in range(3):
        v = rig.actuator.validate({"signed_plan": s})
        assert v == {"ok": True, "rule_ids": [], "reasons": v["reasons"], "invariants_version": "inv-0.1"}
    assert rig.runner.restarts == [] and not rig.audit_path.exists()
    assert rig.execute(s)["result"] == "success"       # the nonce was not consumed by validate


def test_validate_reports_only_invariant_ids_and_reasons(rig):
    plan = make_plan(params={"service": "redis"}, risk="medium")
    v = rig.actuator.validate({"signed_plan": rig.signed(plan)})
    assert v["ok"] is False and v["rule_ids"] == ["I-03"]
    v = rig.actuator.validate({"signed_plan": rig.signed(key=b"x" * 20)})
    assert v["ok"] is False and v["rule_ids"] == ["I-08"] and "A-SIGNATURE" in v["reasons"][0]
    assert all(r.startswith("I-") for r in v["rule_ids"])


# ---- audit -----------------------------------------------------------------------------------
def test_audit_chain_is_valid_and_complete(rig):
    rig.execute(idem="idem-0000001")
    rig.execute(rig.signed(make_plan(params={"service": "ghost"})), idem="idem-0000002")
    ok, n, msg = verify_chain(rig.audit_path)
    assert ok and n == len(rig.audit_events()) == 4, msg
    events = rig.audit_events()
    assert [e["event"] for e in events] == ["plan.accepted", "execution.started", "execution.finished", "plan.refused"]
    assert {e["actor"] for e in events} == {"policy", "actuator"}
    assert events[0]["prev_hash"] == "sha256:" + "0" * 64 and events[1]["prev_hash"] == events[0]["hash"]
    assert all(e["incident_id"] == "INC-0001" for e in events[:3])
    assert KEY.decode() not in rig.audit_path.read_text()


def test_audit_hash_matches_contract_example_algorithm():
    import pathlib
    from actuator.audit import event_hash
    ex = json.loads((pathlib.Path(__file__).resolve().parents[2] / "contracts/examples/audit_event.example.json").read_text())
    assert event_hash(ex) == ex["hash"]


def test_tampered_audit_file_is_detected(rig):
    rig.execute()
    lines = rig.audit_path.read_text().splitlines()
    ev = json.loads(lines[1])
    ev["detail"]["service"] = "worker"
    lines[1] = json.dumps(ev)
    rig.audit_path.write_text("\n".join(lines) + "\n")
    ok, _, msg = verify_chain(rig.audit_path)
    assert not ok and "hash mismatch" in msg
    with pytest.raises(AuditError):
        FileAuditSink(rig.audit_path)


def test_deleted_or_reordered_audit_lines_detected(rig):
    rig.execute()
    lines = rig.audit_path.read_text().splitlines()
    rig.audit_path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert not verify_chain(rig.audit_path)[0]
    rig.audit_path.write_text("\n".join(lines)[:-5])
    assert not verify_chain(rig.audit_path)[0]


def test_audit_failure_before_execution_refuses_the_action(rig):
    rig.audit.fail = True
    ex = rig.execute()
    refused(ex, "A-AUDIT")
    assert rig.runner.restarts == []
    rig.audit.fail = False
    assert rig.execute(rig.signed(), idem="idem-0000002")["result"] == "success"   # nonce not consumed


def test_audit_failure_after_execution_degrades_the_actuator(rig):
    real = rig.audit.append
    def flaky(actor, event, detail, incident_id=None):
        if event == "execution.finished":
            from actuator.audit import AuditError
            raise AuditError("disk full")
        return real(actor, event, detail, incident_id)
    rig.audit.append = flaky
    ex = rig.execute(idem="idem-0000001")
    assert ex["result"] == "success" and "audit write of the result failed" in ex["detail"]
    assert rig.actuator.degraded_reason
    rig.clock.advance(30)
    refused(rig.execute(rig.signed(), idem="idem-0000002"), "A-DEGRADED")
    assert len(rig.runner.restarts) == 1


def test_audit_sink_unwritable_path(tmp_path):
    sink = FileAuditSink(tmp_path / "ok.ndjson")
    sink.path = str(tmp_path / "missing-dir" / "a.ndjson")
    with pytest.raises(AuditError):
        sink.append("actuator", "execution.started", {})


def test_audit_rejects_invalid_events(tmp_path):
    sink = FileAuditSink(tmp_path / "a.ndjson")
    for args in [("hacker", "plan.accepted", {}), ("policy", "Bad Event", {}), ("policy", "plan.accepted", [])]:
        with pytest.raises(AuditError):
            sink.append(*args)
    with pytest.raises(AuditError):
        sink.append("policy", "plan.accepted", {"x": float("nan")})
    assert verify_chain(sink.path)[:2] == (True, 0)


# ---- restart recovery ------------------------------------------------------------------------
def test_state_is_rebuilt_from_the_audit_after_restart(rig):
    s = rig.signed()
    first = rig.execute(s, idem="idem-abcdefg1")
    runner2 = FakeRunner()
    a2 = Actuator(catalog=rig.cat, key_file=KeyFile(str(rig.key_path)), key_id="mvp-1",
                  audit=FileAuditSink(rig.audit_path, clock=rig.clock), executor=DockerExecutor(runner2, rig.cat), clock=rig.clock)
    assert a2.execute({"signed_plan": s, "idempotency_key": "idem-abcdefg1"})["execution"] == first
    replay = a2.execute({"signed_plan": s, "idempotency_key": "idem-abcdefg2"})["execution"]
    assert replay["result"] == "refused" and "A-REPLAY" in replay["refusal_rule_ids"]
    rig.clock.advance(5)
    cooling = a2.execute({"signed_plan": rig.signed(), "idempotency_key": "idem-abcdefg3"})["execution"]
    assert cooling["result"] == "refused" and "I-04" in cooling["refusal_rule_ids"]     # cooldown survived restart
    assert runner2.restarts == []


def test_started_without_finished_is_never_rerun(rig):
    rig.audit.append("actuator", "execution.started", {
        "execution_id": "EX-0001", "plan_id": "PL-0001", "plan_hash": "sha256:" + "0" * 64, "idempotency_key": "idem-crashed1",
        "fingerprint": "sha256:" + "1" * 64, "nonce": "nonce-crashed-0001", "expires_at": "2026-11-02T10:00:00Z",
        "incident_id": "INC-0001", "service": "api", "action_id": "restart_service",
        "argv": ["docker", "restart", "cd-api"], "started_at": "2026-11-02T09:00:30Z"}, "INC-0001")
    a2 = Actuator(catalog=rig.cat, key_file=KeyFile(str(rig.key_path)), key_id="mvp-1",
                  audit=FileAuditSink(rig.audit_path, clock=rig.clock), executor=DockerExecutor(rig.runner, rig.cat), clock=rig.clock)
    out = a2.execute({"signed_plan": rig.signed(), "idempotency_key": "idem-crashed1"})["execution"]
    assert out["result"] in ("failed", "refused") and rig.runner.restarts == []


# ---- source hygiene --------------------------------------------------------------------------
def test_actuator_source_has_no_dangerous_constructs():
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "actuator" / "actuator"
    banned_calls = {"eval", "exec", "compile", "__import__"}
    for path in root.glob("*.py"):
        text = path.read_text()
        assert "shell=True" not in text and "os.system" not in text and "os.popen" not in text, path.name
        assert "pickle" not in text and "yaml.load(" not in text, path.name
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                bare = isinstance(f, ast.Name)
                assert not (bare and name in banned_calls), f"{path.name}: {name}()"
                assert not (not bare and name in {"system", "popen", "eval", "exec"}), f"{path.name}: .{name}()"
                if name == "run" and isinstance(f, ast.Attribute) and getattr(f.value, "id", "") == "subprocess":
                    kw = {k.arg: k.value for k in node.keywords}
                    assert isinstance(kw["shell"], ast.Constant) and kw["shell"].value is False
    subprocess_users = [p.name for p in root.glob("*.py") if "subprocess" in p.read_text()]
    assert subprocess_users == ["runner.py"]
