import copy

import pytest
import yaml

from harness.catalog import Catalog
from harness.paths import SCENARIO_DIR, catalog_path
from harness.scenario import ScenarioError, load_all, load_scenario, schema_errors, semantic_errors, warnings


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(catalog_path({}))


def test_twelve_scenarios_validate(catalog):
    scenarios = load_all(catalog)
    assert sorted(scenarios) == [f"EXP-{i:02d}" for i in range(1, 13)]
    assert [s.id for s in scenarios.values() if s.is_draft] == ["EXP-11", "EXP-12"]


def test_every_scenario_file_is_schema_and_semantically_valid(catalog):
    for p in sorted(SCENARIO_DIR.glob("exp-*.yaml")):
        raw = yaml.safe_load(p.read_text())
        assert schema_errors(raw) == [], p.name
        assert semantic_errors(raw, catalog, p.stem) == [], p.name


def test_equivalence_classes_and_actions_are_defined_for_fault_scenarios(catalog):
    for s in load_all(catalog).values():
        assert s.cause_class, s.id
        assert s.raw["recoverability"]["required_signals"], s.id
        assert s.raw["variants"]["llm"] and s.raw["repetitions"] >= 1


def test_exp10_is_persistent_and_exp09_has_a_decoy(catalog):
    s = load_all(catalog)
    assert s["EXP-10"].fault.persistent is True
    assert s["EXP-09"].decoy is not None and s["EXP-09"].decoy_causes
    assert s["EXP-01"].fault.persistent is False


def test_unimplemented_fault_types_are_flagged(catalog):
    s = load_all(catalog)
    assert warnings(s["EXP-05"].raw) and "not implemented" in warnings(s["EXP-05"].raw)[0]
    assert not [w for w in warnings(s["EXP-01"].raw) if "not implemented" in w]


@pytest.fixture
def raw01():
    return yaml.safe_load((SCENARIO_DIR / "exp-01.yaml").read_text())


def test_unknown_service_rejected(catalog, raw01):
    raw01["targets"] = ["nope"]
    assert any("not in the catalog" in e for e in semantic_errors(raw01, catalog))


def test_extra_property_rejected(raw01):
    raw01["surprise"] = 1
    assert schema_errors(raw01)


def test_action_not_allowed_by_catalog_rejected(catalog, raw01):
    raw01["accepted_remediation"]["actions"] = [{"action_id": "restart_service", "service": "app-db"}]
    assert any("allowed_actions" in e for e in semantic_errors(raw01, catalog))


def test_persistent_only_for_container_faults(catalog, raw01):
    raw01["fault"].update(type="cpu_hog", persistent=True, params={})
    assert any("persistent" in e for e in semantic_errors(raw01, catalog))


def test_decoy_in_equivalence_class_rejected(catalog, raw01):
    raw01["ground_truth"]["decoy_causes"] = ["redis_unavailable"]
    assert any("decoy" in e for e in semantic_errors(raw01, catalog))


def test_id_must_match_file_name(catalog, raw01):
    assert any("file name" in e for e in semantic_errors(raw01, catalog, "exp-02"))


def test_control_requires_fault_none(catalog, raw01):
    raw01["is_control"] = True
    assert any("is_control" in e for e in semantic_errors(raw01, catalog))


def test_load_scenario_raises_with_file_name(catalog, tmp_path, raw01):
    raw01["id"] = "EXP-1"
    p = tmp_path / "exp-01.yaml"
    p.write_text(yaml.safe_dump(raw01))
    with pytest.raises(ScenarioError, match="exp-01.yaml"):
        load_scenario(p, catalog)
