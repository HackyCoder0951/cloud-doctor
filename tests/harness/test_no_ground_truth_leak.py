"""Every byte the harness sends to the API (URL, headers, body) is inspected for ground truth."""
import json

import pytest

from harness.scenario import Scenario
from tests.harness.helpers import make_env, run_and_load

CANARY = "canary9137"


def canary_scenario(env):
    raw = json.loads(json.dumps(env.scenario.raw))
    raw["title"] = f"Title {CANARY}"
    raw["objective"] = f"Objective {CANARY} for the leak test"
    raw["ground_truth"]["cause_equivalence_class"] = [f"{CANARY}_cause", "redis_unavailable"] if raw["id"] != "EXP-07" else [f"{CANARY}_cause", "bad_deployment"]
    raw["fault"]["params"] = {**raw["fault"]["params"], "note": CANARY}
    return Scenario(raw)


@pytest.mark.parametrize("sid", ["EXP-01", "EXP-07", "EXP-10", "EXP-09"])
def test_nothing_from_ground_truth_reaches_the_api(tmp_path, sid):
    env = make_env(tmp_path, sid, http=True)
    env.scenario = canary_scenario(env)
    summary, rec = run_and_load(env, auto_approve=(sid == "EXP-07"))
    assert env.opener.requests, "the run must have used the HTTP client"
    wire = json.dumps(env.opener.requests).lower()
    forbidden = {summary.run_id, env.scenario.id, CANARY, "ground_truth", "cause_equivalence", "t_inject", "container_stop",
                 "cpu_hog", "bad_deployment", "benign_deployment", "persistent", "accepted_remediation", "decoy",
                 "redis_unavailable", "harness"}
    for needle in forbidden:
        assert needle.lower() not in wire, f"{needle!r} leaked to the API"
    # the only request bodies are the login token and (EXP-07) the approval with a fixed reason
    bodies = [json.loads(r["body"]) for r in env.opener.requests if r["body"]]
    assert {"token"} in [set(b) for b in bodies]
    assert all(set(b) in ({"token"}, {"plan_hash", "reason"}) for b in bodies)
    assert all(r["method"] == "GET" or r["url"].endswith(("/auth/login", "/approve")) for r in env.opener.requests)


def test_ground_truth_is_recorded_locally(tmp_path):
    env = make_env(tmp_path, "EXP-01", http=True)
    _, rec = run_and_load(env)
    assert rec.event("inject")["fault"]["type"] == "container_stop"
    assert rec.metadata["scenario"]["ground_truth"]["cause_equivalence_class"]


def test_http_client_logs_in_once_and_sends_idempotency_key_on_mutation(tmp_path):
    env = make_env(tmp_path, "EXP-07", http=True)
    run_and_load(env, auto_approve=True)
    logins = [r for r in env.opener.requests if r["url"].endswith("/auth/login")]
    assert len(logins) == 1
    approve = [r for r in env.opener.requests if r["url"].endswith("/approve")]
    assert len(approve) == 1 and len(approve[0]["headers"]["Idempotency-key"]) >= 8
