import io
import json

import pytest

from harness.cli import main
from harness.records import load_runs
from harness.recoverability import check_scenario
from harness.report import PENDING_SENTENCE, build_summary, write_reports
from harness.scenario import find_scenario, load_all
from tests.harness.helpers import CATALOG, make_env


def run_cli(argv, factory=None):
    out = io.StringIO()
    rc = main(argv, out=out, runner_factory=factory)
    return rc, out.getvalue()


def test_validate_scenarios_cli():
    rc, text = run_cli(["validate-scenarios"])
    assert rc == 0 and "all scenarios valid" in text and "exp-12.yaml (draft)" in text


def test_validate_scenarios_cli_fails_on_bad_file(tmp_path):
    (tmp_path / "exp-01.yaml").write_text("id: nope\n")
    rc, text = run_cli(["validate-scenarios", "--dir", str(tmp_path)])
    assert rc == 1 and "FAIL exp-01.yaml" in text


def test_check_recoverability_flags_scenarios_with_invisible_causes():
    rc, text = run_cli(["check-recoverability"])
    assert rc == 0 and "EXP-01: recoverable" in text and "EXP-03: not_recoverable" in text and "api_cpu_usage" in text
    assert run_cli(["check-recoverability", "--strict"])[0] == 1
    assert "pending" in text


def test_recoverability_logic():
    s = find_scenario(CATALOG, "EXP-01")
    assert check_scenario(s, CATALOG)["status"] == "recoverable"
    raw = json.loads(json.dumps(s.raw))
    raw["recoverability"]["required_signals"][0]["name"] = "made_up_metric"
    from harness.scenario import Scenario
    r = check_scenario(Scenario(raw), CATALOG)
    assert r["status"] == "not_recoverable" and r["missing_cause_signals"] == ["redis_target_down"]
    raw["recoverability"]["required_signals"][0].update(name="up", visibility="backend_internal")
    assert check_scenario(Scenario(raw), CATALOG)["status"] == "recoverable_unverified"
    raw["recoverability"]["required_signals"][3]["to"] = "app-db"  # api->app-db exists, api->redis edge replaced
    raw["recoverability"]["required_signals"][3]["service"] = "redis"
    assert check_scenario(Scenario(raw), CATALOG)["status"] == "not_recoverable"


def test_run_cli_executes_controls_then_experimental_runs(tmp_path):
    env = make_env(tmp_path)
    rc, text = run_cli(["run", "EXP-01", "--controls", "1", "--repeats", "1", "--seed", "10", "--llm", "on"], lambda cat: env.runner)
    assert rc == 0
    lines = text.strip().splitlines()
    assert len(lines) == 2 and "control completed" in lines[0] and "experimental completed" in lines[1]
    recs = load_runs(tmp_path / "runs")
    assert sorted(r.kind for r in recs) == ["control", "experimental"]
    assert all(r.metadata["variant"] == {"llm": "on", "log_noise": "off"} for r in recs)  # LLM flag is metadata only


def test_run_cli_refuses_unknown_scenario_and_bad_repeats(tmp_path):
    assert run_cli(["run", "EXP-99"], lambda c: None)[0] == 2
    assert run_cli(["run", "EXP-01", "--repeats", "0"], lambda c: None)[0] == 2


def test_run_cli_reports_aborted_runs_with_nonzero_exit(tmp_path):
    env = make_env(tmp_path, "EXP-07")
    rc, text = run_cli(["run", "EXP-07"], lambda cat: env.runner)
    assert rc == 1 and "aborted (duration_cap)" in text


def test_report_with_no_runs_is_all_pending(tmp_path):
    rc, text = run_cli(["report", "--runs-dir", str(tmp_path / "none"), "--out", str(tmp_path / "res")])
    assert rc == 0 and "0 run(s)" not in text and "from 0 run record(s)" in text
    day = next((tmp_path / "res").iterdir())
    summary = json.loads((day / "summary.json").read_text())
    assert summary["scenarios_with_runs"] == []
    for sid, g in summary["metrics"]["scenarios"].items():
        assert g["detection"]["mttd_seconds"] == {"n": 0, "status": "pending"}, sid
        assert g["runs"]["total"] == 0
    assert len(list(day.glob("exp-*.md"))) == 12
    md = (day / "exp-01.md").read_text()
    for heading in ("Objective", "Hypothesis", "Initial State", "Fault Injection", "Expected Telemetry", "Detection", "RCA",
                    "Remediation", "Verification", "Metrics", "Results", "Analysis", "Failure Cases", "Conclusion"):
        assert f"## {heading}" in md
    assert md.count(PENDING_SENTENCE) >= 3
    assert "N=" not in md and "median" not in md.split("## Results")[1].split("## Analysis")[0]
    assert "pending" in (day / "exp-03.md").read_text() and "not_recoverable" in (day / "exp-03.md").read_text()


def test_report_from_recorded_runs_only_contains_recorded_values(tmp_path):
    env = make_env(tmp_path)
    env.runner.run(env.scenario)
    records = load_runs(tmp_path / "runs")
    scenarios = load_all(CATALOG)
    day = write_reports(records, scenarios, CATALOG, tmp_path / "res")
    s = json.loads((day / "summary.json").read_text())
    assert s["scenarios_with_runs"] == ["EXP-01"]
    g = s["metrics"]["scenarios"]["EXP-01"]
    assert g["runs"]["experimental"] == 1 and g["detection"]["true_positives"] == 1
    assert g["detection"]["mttd_seconds"]["n"] == 1
    md1, md2 = (day / "exp-01.md").read_text(), (day / "exp-02.md").read_text()
    assert "N=1" in md1 and "1 run(s) recorded" in md1
    assert "| Detection recall | N=1 1/1 = 1.000 |" in md1
    assert "Items marked pending" in md1  # control-run FP rate and decoy rate have no data
    assert PENDING_SENTENCE in md2 and "N=" not in md2  # EXP-02 has no runs: nothing is stated about it
    assert "Conclusion\n\nNo conclusion is drawn by the harness" in md1


def test_cli_module_entrypoint_runs():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "harness", "validate-scenarios"], capture_output=True, text=True, shell=False)
    assert r.returncode == 0 and "all scenarios valid" in r.stdout
