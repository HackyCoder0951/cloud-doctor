import json

import pytest

from harness.catalog import Catalog
from harness.command import ArgvError, SubprocessRunner, check_argv
from harness.faults import FaultNotSupported, FaultSpec
from harness.injector import (CPU_HOG_SCRIPT, MEMORY_HOG_SCRIPT, DockerInjector, FakeInjector, InjectorConfig,
                              InjectorError, PersistentFaultWatcher, TargetError)
from harness.paths import catalog_path
from tests.harness.fakes import FakeRunner

LABEL_ARGV = ["docker", "inspect", "--format", '{{index .Config.Labels "cloud-doctor.sandbox"}}']


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(catalog_path({}))


class FakeHttp:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def request(self, method, url, body, headers, timeout):
        self.calls.append((method, url, json.loads(body) if body else None, dict(headers)))
        return self.status, b"{}"


def make(catalog, runner=None, http=None, **cfg):
    runner = runner or FakeRunner()
    return DockerInjector(catalog, runner, InjectorConfig(**cfg), http or FakeHttp()), runner


def test_stop_start_kill_argv_exact(catalog):
    inj, r = make(catalog)
    inj.apply(FaultSpec("container_stop", "redis"))
    inj.revert(FaultSpec("container_stop", "redis"))
    inj.apply(FaultSpec("container_kill", "worker"))
    assert r.mutating() == [["docker", "stop", "cd-redis"], ["docker", "start", "cd-redis"], ["docker", "kill", "cd-worker"]]
    # every mutation is preceded by the fixed label inspection of the same container
    inspects = [a for a in r.argvs if a[:2] == ["docker", "inspect"]]
    assert inspects[0] == LABEL_ARGV + ["cd-redis"]


def test_cpu_hog_uses_docker_exec_with_fixed_script(catalog):
    inj, r = make(catalog)
    inj.apply(FaultSpec("cpu_hog", "api", {"duration_seconds": 120}))
    assert r.mutating() == [["docker", "exec", "-d", "cd-api", "python3", "-c", CPU_HOG_SCRIPT, "120"]]
    inj.revert(FaultSpec("cpu_hog", "api"))
    assert r.mutating()[1:] == [["docker", "stop", "cd-api"], ["docker", "start", "cd-api"]]


def test_memory_hog_argv(catalog):
    inj, r = make(catalog)
    inj.apply(FaultSpec("memory_hog", "api", {"mb_per_second": 8, "max_mb": 512, "duration_seconds": 60}))
    assert r.mutating() == [["docker", "exec", "-d", "cd-api", "python3", "-c", MEMORY_HOG_SCRIPT, "8", "512", "60"]]


@pytest.mark.parametrize("params", [{"duration_seconds": "5; rm -rf /"}, {"duration_seconds": 0}, {"duration_seconds": True},
                                    {"duration_seconds": 10**9}])
def test_hog_params_are_bounded_integers(catalog, params):
    inj, r = make(catalog)
    with pytest.raises(InjectorError):
        inj.apply(FaultSpec("cpu_hog", "api", params))
    assert r.mutating() == []


def test_bad_deployment_is_fixed_compose_argv_with_env_tag(catalog):
    inj, r = make(catalog, compose_file="/opt/sandbox/compose.yaml", compose_project="cdsandbox")
    f = FaultSpec("bad_deployment", "api", {"service": "api", "new_tag": "v2-bad", "previous_tag": "v1"})
    inj.apply(f)
    inj.revert(f)
    argv = ["docker", "compose", "-f", "/opt/sandbox/compose.yaml", "-p", "cdsandbox", "up", "-d", "--no-deps", "--force-recreate", "api"]
    assert r.mutating() == [argv, argv]
    envs = [env for a, env in r.calls if a[:2] == ["docker", "compose"]]
    assert envs == [{"CD_API_IMAGE_TAG": "v2-bad"}, {"CD_API_IMAGE_TAG": "v1"}]


@pytest.mark.parametrize("tag", ["bad tag", "v1;id", "$(x)", "", "a" * 65])
def test_bad_deployment_rejects_unsafe_tags(catalog, tag):
    inj, r = make(catalog, compose_file="/opt/c.yaml", compose_project="cdsandbox")
    with pytest.raises(InjectorError):
        inj.apply(FaultSpec("bad_deployment", "api", {"service": "api", "new_tag": tag, "previous_tag": "v1"}))
    assert r.mutating() == []


def test_bad_deployment_requires_compose_config(catalog):
    inj, _ = make(catalog)
    with pytest.raises(InjectorError, match="COMPOSE_FILE"):
        inj.apply(FaultSpec("bad_deployment", "api", {"service": "api", "new_tag": "v2", "previous_tag": "v1"}))


def test_latency_toxic_http_api(catalog):
    http = FakeHttp(200)
    inj, r = make(catalog, http=http)
    f = FaultSpec("latency_toxic", "app-db", {"proxy": "api-app-db", "latency_ms": 300, "jitter_ms": 50})
    inj.apply(f)
    inj.revert(f)
    (m1, u1, b1, h1), (m2, u2, b2, _) = http.calls
    assert (m1, u1) == ("POST", "http://127.0.0.1:8474/proxies/api-app-db/toxics")
    assert b1 == {"name": "cd_harness_latency", "type": "latency", "stream": "downstream", "toxicity": 1.0,
                  "attributes": {"latency": 300, "jitter": 50}}
    assert (m2, u2, b2) == ("DELETE", "http://127.0.0.1:8474/proxies/api-app-db/toxics/cd_harness_latency", None)
    assert r.mutating() == []


def test_proxy_must_be_allowlisted_and_well_formed(catalog):
    inj, _ = make(catalog)
    for proxy in ("other", "../x", "a b", ""):
        with pytest.raises(InjectorError):
            inj.apply(FaultSpec("latency_toxic", "app-db", {"proxy": proxy}))


def test_toxiproxy_error_status_raises(catalog):
    inj, _ = make(catalog, http=FakeHttp(500))
    with pytest.raises(InjectorError, match="500"):
        inj.apply(FaultSpec("latency_toxic", "app-db", {"proxy": "api-app-db"}))


@pytest.mark.parametrize("target", ["nope", "cd-redis", "../redis", "redis; id", "", None, "REDIS"])
def test_invalid_targets_rejected_without_any_command(catalog, target):
    inj, r = make(catalog)
    with pytest.raises(TargetError):
        inj.apply(FaultSpec("container_stop", target))
    assert r.calls == []


def test_unlabeled_target_rejected_after_inspect_only(catalog):
    inj, r = make(catalog, runner=FakeRunner(unlabeled={"cd-redis"}))
    with pytest.raises(TargetError, match="cloud-doctor.sandbox"):
        inj.apply(FaultSpec("container_stop", "redis"))
    assert r.mutating() == []
    assert len(r.argvs) == 1


def test_inspect_failure_rejects(catalog):
    inj, r = make(catalog, runner=FakeRunner(failing={"cd-redis"}))
    with pytest.raises(TargetError):
        inj.apply(FaultSpec("container_stop", "redis"))
    assert r.mutating() == []


@pytest.mark.parametrize("ftype", ["connection_hog", "disk_fill", "telemetry_outage", "none"])
def test_unimplemented_fault_types_raise(catalog, ftype):
    inj, r = make(catalog)
    with pytest.raises(FaultNotSupported):
        inj.apply(FaultSpec(ftype, "redis"))
    assert r.calls == []


def test_container_running_uses_fixed_inspect(catalog):
    inj, r = make(catalog, runner=FakeRunner(running={"cd-redis": False}))
    assert inj.container_running("redis") is False
    assert r.argvs[-1] == ["docker", "inspect", "--format", "{{.State.Running}}", "cd-redis"]


def test_check_argv_rejects_shell_strings():
    for bad in ("docker stop cd-redis", ["rm", "-rf", "/"], [], ["docker", 1], b"docker", ["docker", "a\x00b"]):
        with pytest.raises(ArgvError):
            check_argv(bad)


def test_subprocess_runner_uses_shell_false(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen.update(args=args, **kw)

        class P:
            returncode, stdout, stderr = 0, "ok", ""
        return P()

    monkeypatch.setattr("harness.command.subprocess.run", fake_run)
    SubprocessRunner().run(["docker", "stop", "cd-redis"], timeout=5, env={"X": "1"})
    assert seen["shell"] is False and seen["timeout"] == 5 and seen["args"] == ["docker", "stop", "cd-redis"]
    assert seen["env"]["X"] == "1"


def test_persistent_watcher_restops_container(catalog):
    runner = FakeRunner(running={"cd-redis": True})
    inj, _ = make(catalog, runner=runner)
    f = FaultSpec("container_stop", "redis", persistent=True, max_reapplications=2)
    inj.apply(f)
    w = PersistentFaultWatcher(inj, f)
    assert w.step() is None  # still stopped: nothing to do
    runner.running["cd-redis"] = True  # Cloud Doctor restarted it
    assert w.step() is not None and runner.running["cd-redis"] is False
    runner.running["cd-redis"] = True
    w.step()
    runner.running["cd-redis"] = True
    assert w.step() is None and w.gave_up and w.reapplications == 2
    stops = [a for a in runner.mutating() if a == ["docker", "stop", "cd-redis"]]
    assert len(stops) == 3  # initial + 2 re-applications


def test_watcher_requires_persistent_container_fault(catalog):
    inj, _ = make(catalog)
    with pytest.raises(InjectorError):
        PersistentFaultWatcher(inj, FaultSpec("container_stop", "redis", persistent=False))
    with pytest.raises(InjectorError):
        PersistentFaultWatcher(inj, FaultSpec("cpu_hog", "api", persistent=True))


def test_fake_injector_validates_like_docker(catalog):
    labels = {c: "true" for c in catalog.containers()}
    labels["cd-redis"] = "false"
    fake = FakeInjector(catalog, labels)
    with pytest.raises(TargetError):
        fake.apply(FaultSpec("container_stop", "redis"))
    with pytest.raises(TargetError):
        fake.apply(FaultSpec("container_stop", "ghost"))
    fake.apply(FaultSpec("container_stop", "worker"))
    assert fake.container_running("worker") is False
    fake.external_action("restart_service", "worker")
    assert fake.container_running("worker") is True and not fake.active


def test_injector_config_from_env_is_harness_prefixed():
    cfg = InjectorConfig.from_env({"HARNESS_COMPOSE_FILE": "/c.yaml", "HARNESS_TOXIPROXY_PROXIES": "a-b,c", "CD_ACTUATOR_SOCKET": "/x"})
    assert cfg.compose_file == "/c.yaml" and cfg.allowed_proxies == ("a-b", "c")
