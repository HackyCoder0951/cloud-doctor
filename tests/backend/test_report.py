from test_rca import diagnose

from backend.domain.clock import FakeClock
from backend.domain.contracts import validate_against_contract
from backend.report import NoDiagnosis, ReportGenerator
import pytest


def test_c0_report_valid_and_mitigated_separate_from_root_cause(world, catalog, cfg):
    d, inc, repo = diagnose(world, catalog, cfg, "redis_outage", 140)
    repo.save_diagnosis(d)
    gen = ReportGenerator(repo, FakeClock("2026-11-02T09:03:00Z"))
    rep = gen.build(inc.incident_id)
    validate_against_contract(rep, "report")
    assert rep["generator"]["mode"] == "deterministic"
    assert rep["outcome"] == {"mitigated": False, "root_cause_confirmed": False, "escalated": False}
    assert rep["evidence_ids"] and rep["timeline"]
    assert rep["limitations"]


def test_markdown_is_escaped_and_complete(world, catalog, cfg):
    d, inc, repo = diagnose(world, catalog, cfg, "redis_outage", 140)
    repo.save_diagnosis(d)
    gen = ReportGenerator(repo, FakeClock("2026-11-02T09:03:00Z"))
    rep = gen.build(inc.incident_id)
    rep["incident"]["symptoms"].append("<script>alert(1)</script> | x")
    md = gen.render_markdown(rep)
    assert "<script>" not in md and "&lt;script&gt;" in md
    for section in ("## Summary", "## Timeline", "## Diagnosis", "Contradicting evidence", "Unknowns", "## Remediation", "## Verification", "## Limitations"):
        assert section in md
    assert "**Mitigated:** no" in md and "Root cause confirmed:** no" in md
    assert "redis_unavailable" in md


def test_report_requires_diagnosis(world, catalog, cfg):
    d, inc, repo = diagnose(world, catalog, cfg, "redis_outage", 140)
    with pytest.raises(NoDiagnosis):
        ReportGenerator(repo, FakeClock("2026-11-02T09:03:00Z")).build(inc.incident_id)


def test_report_notes_failed_collection(world, catalog, cfg):
    d, inc, repo = diagnose(world, catalog, cfg, "redis_outage_telemetry_failure", 150, until=125)
    repo.save_diagnosis(d)
    rep = ReportGenerator(repo, FakeClock("2026-11-02T09:03:00Z")).build(inc.incident_id)
    validate_against_contract(rep, "report")
    assert any("evidence queries failed" in x for x in rep["limitations"])
