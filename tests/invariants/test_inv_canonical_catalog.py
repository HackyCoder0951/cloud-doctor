import json
import pathlib

import pytest

import invariants as inv
from inv_helpers import CATALOG_DICT, make_plan

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEY = b"k" * 32


def test_canonical_json_is_sorted_compact_utf8():
    assert inv.canonical_json({"b": 1, "a": [1, {"z": 1, "y": "é"}]}) == '{"a":[1,{"y":"é","z":1}],"b":1}'.encode()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_canonical_json_rejects_nan(bad):
    with pytest.raises(ValueError):
        inv.canonical_json({"x": bad})


def test_sha256_tag_format():
    assert inv.sha256_tag(b"") == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_plan_hash_matches_contract_example():
    ex = json.loads((ROOT / "contracts/examples/plan.example.json").read_text())
    assert inv.plan_hash(ex) == ex["plan_hash"]


def test_plan_hash_ignores_its_own_field_and_changes_with_content():
    p = make_plan()
    assert inv.plan_hash(p) == p["plan_hash"]
    assert inv.plan_hash({**p, "plan_hash": "sha256:" + "0" * 64}) == p["plan_hash"]
    assert inv.plan_hash({**p, "rationale": "x"}) != p["plan_hash"]


def test_sign_verify_roundtrip_and_ignores_existing_signature_field():
    env = {"plan": make_plan(), "key_id": "mvp-1", "nonce": "n" * 16}
    sig = inv.sign_envelope(env, KEY)
    assert len(sig) == 64 and int(sig, 16) >= 0
    assert inv.sign_envelope({**env, "signature": "zz"}, KEY) == sig
    assert inv.verify_envelope({**env, "signature": sig}, KEY)


def test_verify_rejects_wrong_key_tamper_and_garbage():
    env = {"plan": make_plan(), "key_id": "mvp-1", "nonce": "n" * 16}
    signed = {**env, "signature": inv.sign_envelope(env, KEY)}
    assert not inv.verify_envelope(signed, b"x" * 32)
    assert not inv.verify_envelope({**signed, "nonce": "m" * 16}, KEY)
    assert not inv.verify_envelope({**signed, "signature": signed["signature"].upper()}, KEY)
    for sig in (None, 5, "", "0" * 64, "é" * 64):
        assert not inv.verify_envelope({**env, "signature": sig}, KEY)
    assert not inv.verify_envelope({**env}, KEY)
    assert not inv.verify_envelope(None, KEY)
    assert not inv.verify_envelope(signed, b"")
    with pytest.raises(ValueError):
        inv.sign_envelope(env, b"")


def test_verify_uses_constant_time_compare():
    src = (ROOT / "invariants/invariants/canonical.py").read_text()
    assert "hmac.compare_digest" in src


def test_catalog_from_dict_and_lookups():
    cat = inv.Catalog.from_dict(CATALOG_DICT)
    assert cat.service("redis").container == "cd-redis"
    assert cat.by_container("cd-api").name == "api"
    assert cat.by_container("cd-nope") is None and cat.service(None) is None and cat.service(["api"]) is None
    assert cat.sandbox_label_pair == ("cloud-doctor.sandbox", "true")
    assert cat.depends_transitively("api", "redis") and not cat.depends_transitively("redis", "api")
    assert cat.declared_labels("cd-api")["cloud-doctor.sandbox"] == "true"


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(catalog_version=2),
    lambda d: d.update(environment="prod"),
    lambda d: d.update(services=[]),
    lambda d: d["services"][0].update(container="api; rm"),
    lambda d: d["services"][0].update(name="Bad Name"),
    lambda d: d["services"][1].update(container="cd-loadgen"),
    lambda d: d["services"][1].update(allowed_actions=["run_shell"]),
    lambda d: d["services"][1].update(depends_on=[{"service": "ghost", "kind": "hard"}]),
    lambda d: d.update(sandbox_label="nolabel"),
])
def test_catalog_rejects_bad_input(mutate):
    import copy
    d = copy.deepcopy(CATALOG_DICT)
    mutate(d)
    with pytest.raises(inv.CatalogError):
        inv.Catalog.from_dict(d)


def test_catalog_load_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(CATALOG_DICT))
    assert inv.Catalog.load(p).service("worker").kind == "queue_worker"
    (tmp_path / "c.txt").write_text("{}")
    with pytest.raises(inv.CatalogError):
        inv.Catalog.load(tmp_path / "c.txt")


def test_catalog_load_repo_yaml():
    pytest.importorskip("yaml")
    cat = inv.Catalog.load(ROOT / "infra/catalog/services.yaml")
    assert set(cat.services) == {"loadgen", "api", "worker", "redis", "app-db"}
    assert cat.service("app-db").allowed_actions == frozenset({"escalate"})


def test_json_loading_needs_no_third_party_package():
    """invariants core imports only the standard library; PyYAML only inside yaml_loader."""
    import ast
    std = set(__import__("sys").stdlib_module_names)
    for path in (ROOT / "invariants/invariants").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module.split(".")[0]]
            for n in names:
                if n == "yaml":
                    assert path.name == "yaml_loader.py"
                else:
                    assert n in std or n == "invariants", f"{path.name} imports {n}"


def test_yaml_loader_without_pyyaml(monkeypatch):
    from invariants import yaml_loader
    monkeypatch.setattr(yaml_loader, "_yaml", None)
    assert not yaml_loader.available()
    with pytest.raises(RuntimeError):
        yaml_loader.load_yaml("a: 1")
