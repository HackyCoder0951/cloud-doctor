"""Optional PostgreSQL repository tests: skipped unless CD_DATABASE_URL is set (needs a PostgreSQL 18-like server).

The schema is loaded verbatim from contracts/db/schema.sql into a throw-away schema-less database, so point
CD_DATABASE_URL at an EMPTY scratch database only.
"""
import json
import os
from pathlib import Path

import pytest

from backend.audit import AuditWriter
from backend.domain.canonical import payload_hash
from backend.domain.catalog import Catalog
from backend.domain.clock import FakeClock, parse_ts
from backend.domain.models import Evidence, Incident

pytestmark = pytest.mark.skipif(not os.environ.get("CD_DATABASE_URL"), reason="CD_DATABASE_URL not set")


@pytest.fixture()
def repo():
    import sqlalchemy as sa

    from backend.repositories.sql import SqlRepository, apply_contract_schema

    r = SqlRepository(os.environ["CD_DATABASE_URL"])
    with r.engine.begin() as c:
        c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    apply_contract_schema(r.engine)
    r.sync_catalog(Catalog.load())
    yield r
    r.engine.dispose()


def _incident(repo):
    inc = Incident(incident_id=repo.next_incident_id(), state="detected", severity="high", opened_at=parse_ts("2026-11-02T09:00:18Z"),
                   services=["redis", "api"], symptoms=["x"])
    repo.save_incident(inc)
    return inc


def test_incident_evidence_roundtrip(repo):
    inc = _incident(repo)
    assert repo.get_incident(inc.incident_id) == inc
    payload = {"series": [{"t": "2026-11-02T09:00:05Z", "v": 1}], "metric": "up"}
    ev = Evidence(evidence_id=repo.next_evidence_id(inc.incident_id), incident_id=inc.incident_id, source="prometheus", type="metric",
                  service="redis", observed_at=parse_ts("2026-11-02T09:00:12Z"), collected_at=parse_ts("2026-11-02T09:00:20Z"),
                  query="up", status="ok", payload=payload, payload_hash=payload_hash(payload), untrusted=False)
    repo.add_evidence(ev)
    got = repo.get_evidence(inc.incident_id, ev.evidence_id)
    assert got.payload == payload and got.payload_hash == payload_hash(got.payload)
    assert repo.next_evidence_id(inc.incident_id) == "EV-002"


def test_audit_chain_enforced_by_database(repo):
    w = AuditWriter(repo, FakeClock())
    w.write("detector", "incident.opened", {"a": 1})
    w.write("rca", "diagnosis.created", {"b": 2})
    assert w.chain_valid()
    import sqlalchemy as sa

    with pytest.raises(Exception):
        with repo.engine.begin() as c:
            c.execute(sa.text("UPDATE audit_log SET actor='api' WHERE seq=1"))
    with pytest.raises(Exception):
        with repo.engine.begin() as c:
            c.execute(sa.text("DELETE FROM audit_log"))
