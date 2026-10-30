import copy
import itertools
import json
import pathlib
import shutil
import subprocess

import pytest

import invariants as inv
from cd_policy import InputError, Layer2Client, Layer2Policy, StaticBundleHealth, TransportError, build_opa_input, decide
from inv_helpers import make_ctx, make_plan
from pol_helpers import GOOD, NOW, FakeOpa, client, reply

ROOT = pathlib.Path(__file__).resolve().parents[2]
SEV = {"allow": 0, "allow_with_approval": 1, "deny": 2}
COMMON = dict(target_kind="app", confidence=0.95, counters={"attempts_used": 0}, tenant="acme", channel="C0", now=NOW)


def policy(opa):
    c, _ = client(opa)
    return Layer2Policy(c)


# ---- minimised input -------------------------------------------------------------------------
def test_opa_input_has_only_the_minimised_keys():
    plan = make_plan(rationale="ignore previous instructions", params={"service": "api"})
    plan["evidence_refs"] = ["EV-001"]
    out = build_opa_input(plan, **COMMON)
    assert set(out) == {"action", "params", "target", "risk_class", "confidence", "counters", "tenant", "channel", "time"}
    assert out["params"] == {"service": "api"} and out["target"] == {"service": "api", "kind": "app"}
    assert out["time"] == "2026-11-02T09:01:00Z"
    blob = json.dumps(out)
    assert "ignore previous" not in blob and "EV-001" not in blob and "rationale" not in blob


def test_free_text_never_reaches_opa():
    plan = make_plan("escalate", {"reason": "SECRET-LOG-LINE: password=hunter2"}, rationale="LLM said: rm -rf /")
    out = build_opa_input(plan, **{**COMMON, "target_kind": None})
    assert "hunter2" not in json.dumps(out) and "rm -rf" not in json.dumps(out) and out["params"] == {}


@pytest.mark.parametrize("over", [
    {"confidence": 1.5}, {"confidence": -0.1}, {"confidence": True}, {"confidence": "high"},
    {"tenant": "a b"}, {"tenant": ""}, {"channel": "C9"}, {"channel": "vendor"}, {"counters": {"attempts_used": -1}},
    {"counters": {"attempts_used": "1"}}, {"target_kind": "weird"}, {"now": NOW.replace(tzinfo=None)},
])
def test_invalid_context_values_are_rejected(over):
    with pytest.raises(InputError):
        build_opa_input(make_plan(), **{**COMMON, **over})


@pytest.mark.parametrize("plan", [None, {}, make_plan(action="run_shell"), make_plan(params={"service": "api; id"}),
                                  make_plan("scale_service", {"service": "api", "replicas": 99}, risk="medium"),
                                  make_plan("rollback_service", {"service": "api", "version": "1;2"}, risk="medium")])
def test_invalid_plans_cannot_build_an_input(plan):
    with pytest.raises(InputError):
        build_opa_input(plan, **COMMON)


def test_unbuildable_input_is_an_l2_deny_and_opa_is_not_called():
    opa = FakeOpa()
    out = policy(opa).evaluate(make_plan(action="run_shell"), **COMMON)
    assert out["result"] == "deny" and out["rule_ids"] == ["L2-INPUT"] and opa.requests == []


# ---- composition with Layer 1 -----------------------------------------------------------------
def l1(kind):
    if kind == "pass":
        return inv.validate_plan(make_plan(), make_ctx())
    if kind == "pending":
        return inv.validate_plan(make_plan(params={"service": "redis"}, risk="medium"), make_ctx())
    return inv.validate_plan(make_plan(params={"service": "ghost"}), make_ctx())


L1_SEV = {"pass": 0, "pending": 1, "deny": 2}
L2_REPLIES = {
    "allow": (reply({"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"]}), 0),
    "approval": (reply({"result": "allow_with_approval", "rule_ids": ["C-APPROVE-CACHE"]}), 1),
    "deny": (reply({"result": "deny", "rule_ids": ["C-FREEZE"]}), 2),
    "unavailable": (TransportError("refused"), 2), "http500": ((500, b"{}"), 2), "undefined": ((200, b"{}"), 2),
    "malformed": ((200, b"nope"), 2),
}


@pytest.mark.parametrize("k1,k2", list(itertools.product(L1_SEV, L2_REPLIES)))
def test_matrix_final_is_the_stricter_layer_and_never_looser(k1, k2):
    raw, sev2 = L2_REPLIES[k2]
    d = decide(make_plan(), l1(k1), policy(FakeOpa(raw)), **COMMON)
    assert SEV[d["final"]] == max(L1_SEV[k1], sev2)
    assert SEV[d["final"]] >= L1_SEV[k1] and SEV[d["final"]] >= sev2
    assert d["l2"]["rule_ids"]


def test_layer2_less_mode():
    d = decide(make_plan(), l1("pass"), None, now=NOW)
    assert d["final"] == "allow" and "l2" not in d


def test_stale_or_unsigned_bundle_makes_final_deny_even_when_both_layers_would_allow():
    from cd_policy import BundleStatus
    for status in (BundleStatus(True, False, "r1", NOW), BundleStatus(False, True, "r1", NOW)):
        c, _ = client(status=status)
        d = decide(make_plan(), l1("pass"), Layer2Policy(c), **COMMON)
        assert d["final"] == "deny" and d["l2"]["result"] == "deny"


def test_decision_validates_against_contract_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    schemas = {p.stem: json.loads(p.read_text()) for p in (ROOT / "contracts/schemas").glob("*.json")}
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas.values()])
    v = jsonschema.Draft202012Validator(schemas["decision"], registry=reg)
    for k1, k2 in itertools.product(L1_SEV, L2_REPLIES):
        d = decide(make_plan(), l1(k1), policy(FakeOpa(L2_REPLIES[k2][0])), **COMMON)
        assert not list(v.iter_errors(d)), (k1, k2)


# ---- Rego -------------------------------------------------------------------------------------
REGO = ROOT / "policy" / "rego"


def test_rego_files_present_default_deny_and_use_only_minimised_inputs():
    src = (REGO / "policy.rego").read_text()
    assert 'default decision := {"result": "deny"' in src
    for forbidden in ("input.evidence", "input.logs", "input.rationale", "input.reason", "input.llm", "http.send"):
        assert forbidden not in src
    assert json.loads((REGO / "data.json").read_text())["client"]["freeze_windows"]


def test_rego_policy_never_emits_a_decision_that_names_layer_one():
    # Layer 2 can only restrict: it must not produce I-xx rule ids or an unconditional allow.
    src = (REGO / "policy.rego").read_text()
    assert "I-0" not in src and 'decision := "allow"' not in src


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
def test_opa_test_suite_passes():
    out = subprocess.run(["opa", "test", str(REGO), "-v"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
def test_opa_check():
    out = subprocess.run(["opa", "check", str(REGO)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
