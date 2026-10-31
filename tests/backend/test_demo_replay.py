import json
import subprocess
import sys
from pathlib import Path

from backend.demo_replay import main, replay
from backend.domain.contracts import validate_against_contract

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/backend/fixtures"


def test_committed_json_fixtures_match_the_generator():
    """Drift guard: fixture JSON files are generated from scenarios.py."""
    from fixtures import scenarios

    for name, fn in scenarios.ALL.items():
        on_disk = json.loads((FIX / f"{name}.json").read_text())
        assert on_disk == json.loads(json.dumps(fn())), f"{name}.json is stale: run python tests/backend/fixtures/scenarios.py"


def test_demo_replay_module_runs_without_docker_network_or_llm():
    out = subprocess.run([sys.executable, "-m", "backend.demo_replay"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "# Incident report INC-0001" in out.stdout and "redis_unavailable" in out.stdout
    assert "Mitigated:** no" in out.stdout and "nothing executed" in out.stdout


def test_demo_replay_json_is_contract_valid(capsys):
    assert main(["--json"]) == 0
    rep = json.loads(capsys.readouterr().out.split("-->", 1)[1])
    validate_against_contract(rep, "report")
    assert rep["diagnosis"]["hypotheses"][0]["cause_id"] == "redis_unavailable"
    assert rep["plans"] == [] and rep["executions"] == []  # read-only loop


def test_demo_replay_control_has_no_incident(capsys):
    assert main(["--scenario", "control", "--until", "290"]) == 0
    assert "no incident opened" in capsys.readouterr().out


def test_demo_replay_all_fault_scenarios_produce_valid_reports():
    for name, until in [("worker_crash", 140), ("memory_exhaustion", 130), ("bad_deployment", 140), ("false_correlation", 150), ("db_saturation", 150)]:
        svc, sc = replay(FIX / f"{name}.json", until)
        incs = svc.repo.list_incidents()
        assert incs, name
        for inc in incs:
            if svc.repo.latest_diagnosis(inc.incident_id):
                validate_against_contract(svc.reports.build(inc.incident_id), "report")
