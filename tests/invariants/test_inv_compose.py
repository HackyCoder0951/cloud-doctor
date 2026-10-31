import itertools
import pathlib

import pytest

import invariants as inv
from inv_helpers import NOW, approval_for, make_ctx, make_plan

ROOT = pathlib.Path(__file__).resolve().parents[2]
SEV = {"allow": 0, "allow_with_approval": 1, "deny": 2}


def L2(result="allow", **over):
    d = {"result": result, "rule_ids": ["C-X"], "bundle_revision": "r1", "bundle_signed": True}
    d.update(over)
    return d


def validate(doc_name="decision"):
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    import json
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    schemas = {p.stem: json.loads(p.read_text()) for p in (ROOT / "contracts/schemas").glob("*.json")}
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas.values()])
    v = jsonschema.Draft202012Validator(schemas[doc_name], registry=reg, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    return v


def l1_pass():
    return inv.validate_plan(make_plan(), make_ctx())


def l1_deny():
    return inv.validate_plan(make_plan(params={"service": "ghost"}), make_ctx())


def l1_pending():
    return inv.validate_plan(make_plan(params={"service": "redis"}, risk="medium"), make_ctx())


def test_final_allow_and_schema_valid():
    d = inv.compose_decision(l1_pass(), L2(), now=NOW)
    assert d["final"] == "allow" and d["l1"]["result"] == "pass" and d["l2"]["result"] == "allow"
    assert d["invariants_version"] == "inv-0.1" and d["plan_id"] == "PL-0001"
    assert not list(validate().iter_errors(d))


def test_layer1_only_mode_when_l2_none():
    d = inv.compose_decision(l1_pass(), None, now=NOW)
    assert d["final"] == "allow" and "l2" not in d
    assert not list(validate().iter_errors(d))


def test_pending_approval_from_l1():
    d = inv.compose_decision(l1_pending(), L2(), now=NOW)
    assert d["final"] == "allow_with_approval" and d["l1"]["result"] == "pass" and "I-03" in d["l1"]["rule_ids"]
    assert not list(validate().iter_errors(d))


def test_l1_deny_is_final_even_if_l2_allows():
    d = inv.compose_decision(l1_deny(), L2("allow"), now=NOW)
    assert d["final"] == "deny" and d["l1"]["result"] == "deny" and d["l1"]["rule_ids"]
    assert not list(validate().iter_errors(d))


@pytest.mark.parametrize("l2", [
    "garbage", 5, [], {}, {"result": "allow"}, {"rule_ids": []},
    {"result": "maybe", "rule_ids": [], "bundle_signed": True},
    {"result": "allow", "rule_ids": "C-X", "bundle_signed": True},
    {"result": "allow", "rule_ids": [1], "bundle_signed": True},
    L2(bundle_signed=False), L2(bundle_signed=None), {"result": "allow", "rule_ids": []},
    L2(stale=True), L2(problem="timeout"),
])
def test_any_layer2_problem_is_final_deny(l2):
    d = inv.compose_decision(l1_pass(), l2, now=NOW)
    assert d["final"] == "deny"
    assert d["l2"]["result"] == "deny"
    assert not list(validate().iter_errors(d))


def test_layer2_tightens_to_approval_and_deny():
    assert inv.compose_decision(l1_pass(), L2("allow_with_approval"), now=NOW)["final"] == "allow_with_approval"
    assert inv.compose_decision(l1_pass(), L2("deny"), now=NOW)["final"] == "deny"
    assert inv.compose_decision(l1_pending(), L2("allow_with_approval"), now=NOW)["final"] == "allow_with_approval"


def test_composition_matrix_layer2_can_never_loosen_layer1():
    l1s = {"pass": l1_pass(), "pending": l1_pending(), "deny": l1_deny(),
           "dict_pass": {"result": "pass", "rule_ids": ["I-01"]},
           "dict_approval": {"result": "pass", "rule_ids": ["I-01"], "requires_approval": True},
           "dict_deny": {"result": "deny", "rule_ids": ["I-02"]}, "bad": None}
    l1_sev = {"pass": 0, "pending": 1, "deny": 2, "dict_pass": 0, "dict_approval": 1, "dict_deny": 2, "bad": 2}
    l2s = {"none": None, "allow": L2("allow"), "approval": L2("allow_with_approval"), "deny": L2("deny"),
           "malformed": {"x": 1}, "unsigned": L2(bundle_signed=False), "stale": L2(stale=True)}
    l2_sev = {"none": 0, "allow": 0, "approval": 1, "deny": 2, "malformed": 2, "unsigned": 2, "stale": 2}
    v = validate()
    for (n1, a), (n2, b) in itertools.product(l1s.items(), l2s.items()):
        d = inv.compose_decision(a, b, now=NOW)
        assert not list(v.iter_errors(d)), (n1, n2)
        assert SEV[d["final"]] == max(l1_sev[n1], l2_sev[n2]), (n1, n2, d["final"])
        assert SEV[d["final"]] >= l1_sev[n1]            # Layer 2 never loosens Layer 1
        assert SEV[d["final"]] >= l2_sev[n2]


def test_layer2_result_from_an_attacker_cannot_loosen():
    # a Layer 2 that claims "allow" while carrying extra keys is still only conjoined
    d = inv.compose_decision(l1_deny(), {**L2("allow"), "override": True, "final": "allow"}, now=NOW)
    assert d["final"] == "deny" and "override" not in d["l2"]


def test_compose_never_raises():
    class Weird:
        def __getattr__(self, n):
            raise RuntimeError
    for l1 in (Weird(), 5, "x", {"result": object()}):
        d = inv.compose_decision(l1, Weird())
        assert d["final"] == "deny"
        assert not list(validate().iter_errors(d))


def test_decision_id_and_plan_override():
    p = make_plan()
    d = inv.compose_decision(l1_pass(), None, plan=p, decision_id="DEC-0042", now=NOW)
    assert d["decision_id"] == "DEC-0042" and d["plan_hash"] == p["plan_hash"]
    again = inv.compose_decision(l1_pass(), None, now=NOW)
    assert again["decision_id"] == inv.compose_decision(l1_pass(), None, now=NOW)["decision_id"]


def test_long_reasons_are_clipped_to_schema():
    d = inv.compose_decision({"result": "deny", "rule_ids": ["I-01"]}, L2("allow", rule_ids=["x" * 1000]), now=NOW)
    assert all(len(r) <= 300 for r in d["reasons"])
    assert not list(validate().iter_errors(d))
