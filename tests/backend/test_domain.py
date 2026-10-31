import json
from pathlib import Path

import pytest

from backend.audit import AuditWriter, compute_hash, verify_chain
from backend.domain.canonical import ZERO_HASH, canonical_json, payload_hash, plan_hash, strip_nul
from backend.domain.catalog import Catalog
from backend.domain.clock import FakeClock, iso, parse_ts
from backend.domain.contracts import ContractViolation, validate_against_contract
from backend.domain.models import (AuditEvent, Diagnosis, Evidence, Execution, Incident, Plan, TimelineEvent,
                                   Verification, Decision)
from backend.repositories import MemoryRepository
from backend.repositories.base import RepositoryError

EX = Path(__file__).resolve().parents[2] / "contracts/examples"


def load(name):
    return json.loads((EX / name).read_text())


def test_canonical_json_is_sorted_compact_utf8():
    assert canonical_json({"b": 1, "a": [1, {"d": "é", "c": None}]}) == '{"a":[1,{"c":null,"d":"é"}],"b":1}'.encode()
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_hashes_match_frozen_examples():
    ev = load("evidence.example.json")
    assert payload_hash(ev["payload"]) == ev["payload_hash"]
    plan = load("plan.example.json")
    assert plan_hash(plan) == plan["plan_hash"]
    a = load("audit_event.example.json")
    assert compute_hash(a["seq"], a["incident_id"], a["actor"], a["event"], a["detail"], a["prev_hash"], a["created_at"]) == a["hash"]


@pytest.mark.parametrize("example,schema,model", [
    ("evidence", "evidence", Evidence), ("incident", "incident", Incident), ("plan", "plan", Plan),
    ("decision", "decision", Decision), ("execution", "execution", Execution), ("diagnosis", "diagnosis", Diagnosis),
    ("audit_event", "audit_event", AuditEvent), ("verification", "verification", Verification),
])
def test_models_round_trip_frozen_examples(example, schema, model):
    data = load(f"{example}.example.json")
    validate_against_contract(data, schema)
    out = model.model_validate(data).to_contract()
    validate_against_contract(out, schema)
    assert model.model_validate(out) == model.model_validate(data)  # defaults may be made explicit on output


def test_timeline_event_round_trip():
    data = load("timeline_event.example.json")
    out = TimelineEvent.model_validate(data).to_contract()
    validate_against_contract(out, "incident", "#/$defs/timeline_event")
    assert out["event_time"] == data["event_time"]


def test_negative_cases_are_rejected_by_helper():
    neg = load("negative_cases.json")
    for name, obj in neg.items():
        schema = name.split("_")[0]
        with pytest.raises(ContractViolation):
            validate_against_contract(obj, schema)


def test_date_time_format_is_enforced():
    bad = load("incident.example.json")
    bad["opened_at"] = "yesterday"
    with pytest.raises(ContractViolation):
        validate_against_contract(bad, "incident")


def test_strip_nul_recursive():
    assert strip_nul({"a\x00": ["x\x00y", {"k": "\x00"}]}) == {"a": ["xy", {"k": ""}]}


def test_timestamps():
    assert iso(parse_ts("2026-11-02T09:00:12+00:00")) == "2026-11-02T09:00:12Z"
    with pytest.raises(ValueError):
        parse_ts("2026-11-02 09:00")
    c = FakeClock("2026-11-02T09:00:00Z")
    c.sleep(20)
    assert iso(c.now()) == "2026-11-02T09:00:20Z"


def test_catalog_topology():
    cat = Catalog.load()
    assert set(cat.names()) == {"loadgen", "api", "worker", "redis", "app-db"}
    assert cat.dependents("redis") == ["api", "worker"]
    assert cat.depth("redis") == 0 and cat.depth("api") == 1 and cat.depth("loadgen") == 2
    assert cat.transitive_dependents("redis") == {"api", "worker", "loadgen"}
    # the full graph is one component; induced subgraphs on affected nodes split
    assert len(cat.connected_components(set(cat.names()))) == 1
    assert len(cat.connected_components({"worker", "loadgen"})) == 2


def test_audit_chain_and_tamper_detection():
    repo, clock = MemoryRepository(), FakeClock()
    w = AuditWriter(repo, clock)
    e1 = w.write("detector", "incident.opened", {"services": ["redis"]}, "INC-0001")
    clock.sleep(1)
    e2 = w.write("rca", "diagnosis.created", {"top": "redis_unavailable\x00"})  # NUL stripped, no incident
    assert e1.prev_hash == ZERO_HASH and e2.prev_hash == e1.hash and e2.seq == 2
    assert "\x00" not in json.dumps(e2.detail)
    for e in repo.all_audit():
        validate_against_contract(e.to_contract(), "audit_event")
    assert w.chain_valid()
    tampered = [e.model_copy(update={"detail": {"services": ["x"]}}) for e in repo.all_audit()[:1]] + repo.all_audit()[1:]
    assert not verify_chain(tampered)


def test_audit_rejects_broken_chain():
    repo = MemoryRepository()
    w = AuditWriter(repo, FakeClock())
    w.write("api", "login.ok", {})
    bad = AuditEvent(seq=3, actor="api", event="login.ok", detail={}, prev_hash=ZERO_HASH, hash="sha256:" + "1" * 64,
                     created_at=parse_ts("2026-11-02T09:00:00Z"))
    with pytest.raises(RepositoryError):
        repo.append_audit(bad)


def test_memory_repo_evidence_is_immutable_and_nul_free():
    repo = MemoryRepository()
    d = load("evidence.example.json")
    ev = Evidence.model_validate(d)
    repo.add_evidence(ev)
    with pytest.raises(RepositoryError):
        repo.add_evidence(ev)
    bad = ev.model_copy(update={"evidence_id": "EV-002", "payload": {"line": "a\x00b"}})
    with pytest.raises(RepositoryError):
        repo.add_evidence(bad)
    assert repo.next_evidence_id("INC-0001") == "EV-001"
