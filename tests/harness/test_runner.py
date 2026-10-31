import json
from dataclasses import replace

import pytest

from harness.clock import parse_ts
from harness.faults import FaultNotSupported, FaultSpec
from harness.records import classify_run, derive_timestamps, executions_of, tp_incident
from harness.scenario import Scenario, find_scenario
from tests.harness.fake_api import Profile
from tests.harness.helpers import CATALOG, COMMIT, PROFILES, make_env, run_and_load

SCENARIOS = ["EXP-01", "EXP-02", "EXP-03", "EXP-04", "EXP-06", "EXP-07", "EXP-08", "EXP-09", "EXP-10"]


def events(rec, name):
    return [e for e in rec.events if e["event"] == name]


def phases(rec):
    return [e["phase"] for e in events(rec, "phase")]


def edit(env, fn):
    raw = json.loads(json.dumps(env.scenario.raw))
    fn(raw)
    env.scenario = Scenario(raw)


def test_exp01_full_protocol_and_timestamps(tmp_path):
    env = make_env(tmp_path)
    summary, rec = run_and_load(env)
    assert (summary.status, summary.abort_reason) == ("completed", None)
    assert phases(rec) == ["baseline", "inject", "observe", "teardown", "done"]
    ts = {k: parse_ts(v) for k, v in derive_timestamps(rec).items()}
    assert ts["t_inject"] < ts["t_impact"] < ts["t_detect"] < ts["t_diagnose"] < ts["t_action"] < ts["t_recover"]
    lines = (env.store_root / summary.run_id / "ground_truth.ndjson").read_text().splitlines()
    stamped = [json.loads(l) for l in lines if '"event":"timestamps"' in l]
    assert stamped and stamped[0]["t_recover"] is not None
    assert tp_incident(rec).incident["state"] == "recovered"
    assert [e["result"] for e in executions_of(tp_incident(rec))] == ["success"]
    assert env.injector.active == [] and env.injector.running["cd-redis"] is True
    assert events(rec, "revert")


@pytest.mark.parametrize("sid", SCENARIOS)
def test_each_scenario_runs_against_its_simulation(tmp_path, sid):
    env = make_env(tmp_path, sid)
    summary, rec = run_and_load(env, auto_approve=(sid == "EXP-07"))
    inc = tp_incident(rec)
    assert inc is not None, sid
    expected_end = {"EXP-06": "escalated", "EXP-08": "escalated", "EXP-10": "escalated"}.get(sid, "recovered")
    assert inc.incident["state"] == expected_end, sid
    assert summary.status == "completed", (sid, summary)
    assert rec.t_inject is not None
    assert env.injector.active == []  # teardown reverted everything
    assert inc.first_diagnosis["hypotheses"][0]["cause_id"] in env.scenario.cause_class or sid in ("EXP-08",), sid


def test_exp07_without_operator_approval_hits_duration_cap(tmp_path):
    env = make_env(tmp_path, "EXP-07")
    summary, rec = run_and_load(env, auto_approve=False)
    assert (summary.status, summary.abort_reason) == ("aborted", "duration_cap")
    assert not events(rec, "operator_approval")
    assert executions_of(tp_incident(rec)) == []


def test_exp07_simulated_approval_is_recorded_as_ground_truth(tmp_path):
    env = make_env(tmp_path, "EXP-07")
    _, rec = run_and_load(env, auto_approve=True)
    assert len(events(rec, "operator_approval")) == 1
    assert "approve_plan" in [c[0] for c in env.fake.calls]


def test_exp09_decoy_applied_before_fault(tmp_path):
    env = make_env(tmp_path, "EXP-09")
    _, rec = run_and_load(env)
    (decoy,), (inject,) = events(rec, "decoy_injected"), events(rec, "inject")
    assert decoy["fault"]["type"] == "benign_deployment" and decoy["fault"]["target"] == "worker"
    assert (parse_ts(inject["t"]) - parse_ts(decoy["t"])).total_seconds() == 20
    assert env.injector.calls[0][1].type == "benign_deployment"


def test_exp10_persistent_fault_defeats_restart_and_escalates(tmp_path):
    env = make_env(tmp_path, "EXP-10")
    summary, rec = run_and_load(env)
    inc = tp_incident(rec)
    assert summary.status == "completed" and inc.incident["state"] == "escalated"
    assert len(executions_of(inc)) == 2  # attempt budget, not more
    assert [v["verdict"] for v in inc.verifications] == ["failed", "failed"]
    assert len(events(rec, "fault_reapplied")) >= 2
    assert derive_timestamps(rec)["t_recover"] is None


def test_exp10_watcher_gives_up_after_max_reapplications(tmp_path):
    env = make_env(tmp_path, "EXP-10")
    edit(env, lambda r: r["fault"].update(max_reapplications=1))
    _, rec = run_and_load(env)
    assert len(events(rec, "fault_reapplied")) == 1


def test_abort_blast_radius_exceeded_reverts_fault(tmp_path):
    env = make_env(tmp_path, "EXP-02", profile=replace(PROFILES["EXP-02"], extra_unhealthy=("api", "redis", "app-db")))
    summary, rec = run_and_load(env)
    assert (summary.status, summary.abort_reason) == ("aborted", "blast_radius_exceeded")
    assert phases(rec)[-3:] == ["abort", "teardown", "done"]
    assert env.injector.active == [] and env.injector.running["cd-worker"] is True
    assert events(rec, "run_end")[0]["abort_reason"] == "blast_radius_exceeded"


def test_abort_max_executions(tmp_path):
    env = make_env(tmp_path, "EXP-10", profile=replace(PROFILES["EXP-10"], max_attempts=50, cooldown=1, verify_delay=2))
    summary, _ = run_and_load(env)
    assert (summary.status, summary.abort_reason) == ("aborted", "max_executions_exceeded")
    assert env.injector.active == []


def test_abort_action_blast_radius(tmp_path):
    env = make_env(tmp_path, "EXP-01")
    edit(env, lambda r: r["abort"].update(max_action_services=0))
    summary, _ = run_and_load(env)
    assert summary.abort_reason == "action_blast_radius_exceeded"


def test_steady_state_not_reached_means_no_injection(tmp_path):
    env = make_env(tmp_path, "EXP-01")
    env.injector.apply(FaultSpec("container_stop", "worker"))  # already degraded before the run
    env.injector.calls.clear()
    env.fake.p.impact_delay = 0
    summary, rec = run_and_load(env)
    assert (summary.status, summary.abort_reason) == ("aborted", "steady_state_not_reached")
    assert not events(rec, "inject") and [c for c in env.injector.calls if c[0] == "apply"] == []


def test_api_outage_aborts_with_harness_error(tmp_path):
    env = make_env(tmp_path, "EXP-01")
    env.fake.fail_calls = True
    summary, rec = run_and_load(env)
    assert (summary.status, summary.abort_reason) == ("aborted", "harness_error")
    assert rec.api_errors >= 5


def test_missed_detection_is_recorded_not_hidden(tmp_path):
    env = make_env(tmp_path, "EXP-01", profile=replace(PROFILES["EXP-01"], detects=False))
    summary, rec = run_and_load(env)
    assert summary.status == "completed" and events(rec, "detection_missed")
    assert rec.incidents == {} and derive_timestamps(rec)["t_detect"] is None
    assert derive_timestamps(rec)["t_impact"] is not None  # the SLI breach was still seen in API data


def test_control_run_injects_nothing_and_records_false_positive(tmp_path):
    env = make_env(tmp_path, "EXP-01", profile=replace(PROFILES["EXP-01"], false_positive_at=100))
    summary, rec = run_and_load(env, kind="control")
    assert summary.kind == "control" and summary.status == "completed"
    assert env.injector.calls == [] and rec.t_inject is None
    assert phases(rec) == ["baseline", "control", "teardown", "done"]
    assert len(classify_run(rec).fp) == 1
    assert rec.observe_seconds >= env.scenario.timing["max_duration_seconds"]


def test_draft_scenarios_are_refused_unless_allowed(tmp_path):
    env = make_env(tmp_path, "EXP-01", scenario=find_scenario(CATALOG, "EXP-11"))
    with pytest.raises(FaultNotSupported, match="draft"):
        env.runner.run(env.scenario)
    summary, rec = run_and_load(env, allow_draft=True)
    assert summary.abort_reason == "harness_error"  # disk_fill is not implemented
    assert "not supported" in events(rec, "abort")[0]["detail"]


def test_unsupported_designed_fault_aborts_cleanly(tmp_path):
    env = make_env(tmp_path, "EXP-05")
    summary, rec = run_and_load(env)
    assert summary.abort_reason == "harness_error" and not events(rec, "inject")


def test_metadata_and_sink(tmp_path):
    env = make_env(tmp_path)
    summary, rec = run_and_load(env, seed=42, repeat_index=3, variant={"llm": "on", "log_noise": "off"})
    m = rec.metadata
    assert m["git_commit"] == COMMIT and m["scenario_id"] == "EXP-01" and m["seed"] == 42 and m["repeat_index"] == 3
    assert m["variant"] == {"llm": "on", "log_noise": "off"}
    assert m["image_digests"]["cd-redis"].startswith("sha256:")
    assert m["python"] and m["libraries"]["pyyaml"] and m["started_at"]
    assert m["api_endpoint"] == "http://127.0.0.1:8080"  # credentials/path stripped
    assert "pw" not in json.dumps(m) and "secret" not in json.dumps(m)
    rows = [json.loads(l) for l in (tmp_path / "runs" / "experiment_runs.ndjson").read_text().splitlines()]
    assert len(rows) == 2 and rows[0]["injected_at"] is None
    assert rows[1]["injected_at"] and rows[1]["ground_truth"]["expected_cause_class"] == env.scenario.cause_class
    assert rows[1]["run_id"] == summary.run_id


def test_seed_makes_jitter_reproducible(tmp_path):
    stamps = []
    for i in range(2):
        env = make_env(tmp_path / str(i))
        edit(env, lambda r: r["timing"].update(inject_jitter_seconds=10))
        _, rec = run_and_load(env, seed=7)
        stamps.append((parse_ts(rec.event("inject")["t"]) - rec.started_at).total_seconds())
    assert stamps[0] == stamps[1]


def test_run_ids_are_unique_per_directory(tmp_path):
    env = make_env(tmp_path)
    env.runner.run(env.scenario)
    env.clock._t = env.clock._t.replace(microsecond=0)
    from datetime import timedelta
    env.clock._t -= timedelta(seconds=(env.clock._t - env.fake.t0).total_seconds())  # same instant -> same id
    with pytest.raises(FileExistsError):
        env.runner.run(env.scenario)
