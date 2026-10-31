from __future__ import annotations

from dataclasses import dataclass

from harness.api_client import HttpApiClient
from harness.catalog import Catalog
from harness.command import CommandResult
from harness.injector import FakeInjector
from harness.metadata import MetadataCollector
from harness.paths import catalog_path
from harness.records import load_run
from harness.runner import Runner
from harness.scenario import Scenario, find_scenario
from harness.store import FileExperimentRunsSink, FileRunStore
from tests.harness.fake_api import FakeClock, FakeCloudDoctor, FakeOpener, Profile

CATALOG = Catalog.load(catalog_path({}))
COMMIT = "a" * 40


class MetaRunner:
    """CommandRunner stub for metadata collection only."""

    def run(self, argv, *, timeout, env=None):
        if argv[:2] == ["git", "rev-parse"]:
            return CommandResult(0, COMMIT + "\n")
        if argv[:2] == ["docker", "inspect"]:
            return CommandResult(0, "sha256:" + "b" * 64 + "\n")
        return CommandResult(1)


PROFILES = {
    "EXP-01": Profile(),
    "EXP-02": Profile(breach_services=("worker",), sli="queue", cause_ids=("worker_unavailable", "redis_unavailable"),
                      action=("restart_service", "worker")),
    "EXP-03": Profile(breach_services=("api",), sli="latency", cause_ids=("api_cpu_saturation", "downstream_slow"),
                      action=("restart_service", "api")),
    "EXP-04": Profile(breach_services=("api",), cause_ids=("api_memory_exhaustion", "api_bug"), action=("restart_service", "api")),
    "EXP-06": Profile(breach_services=("api",), sli="latency", cause_ids=("network_latency_app_db",), action=None),
    "EXP-07": Profile(breach_services=("api",), cause_ids=("bad_deployment", "load_change"), action=("rollback_service", "api"),
                      risk="medium", needs_approval=True),
    "EXP-08": Profile(breach_services=("app-db", "api", "worker"), cause_ids=("app_db_unavailable",), action=None),
    "EXP-09": Profile(breach_services=("api",), sli="latency", cause_ids=("api_cpu_saturation", "worker_bad_deployment"),
                      action=("restart_service", "api")),
    "EXP-10": Profile(),
}


@dataclass
class Env:
    runner: Runner
    clock: FakeClock
    injector: FakeInjector
    fake: FakeCloudDoctor
    scenario: Scenario
    store_root: object
    opener: FakeOpener | None = None


def make_env(tmp_path, scenario_id="EXP-01", profile: Profile | None = None, http=False, scenario: Scenario | None = None) -> Env:
    clock = FakeClock()
    injector = FakeInjector(CATALOG)
    fake = FakeCloudDoctor(clock, injector, profile or PROFILES.get(scenario_id, Profile()))
    opener = None
    api = fake
    if http:
        opener = FakeOpener(fake)
        api = HttpApiClient("http://127.0.0.1:8080/api/v1", token="secret-token-123", opener=opener)
    sink = FileExperimentRunsSink(tmp_path / "runs" / "experiment_runs.ndjson")
    runner = Runner(api=api, injector=injector, store=FileRunStore(tmp_path / "runs"), clock=clock,
                    collector=MetadataCollector(MetaRunner(), CATALOG, "http://user:pw@127.0.0.1:8080/api/v1"), sink=sink)
    sc = scenario or find_scenario(CATALOG, scenario_id)
    return Env(runner, clock, injector, fake, sc, tmp_path / "runs", opener)


def run_and_load(env: Env, **kw):
    summary = env.runner.run(env.scenario, **kw)
    return summary, load_run(env.store_root / summary.run_id)
