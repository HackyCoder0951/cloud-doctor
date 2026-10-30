"""Fault injectors.

The injector is the harness's privileged component. It has its own configuration (HARNESS_* variables),
uses only fixed argv lists through an injectable CommandRunner, and is never reachable from Cloud Doctor
components. Every target is validated against the service catalog and must carry the sandbox label.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from harness.catalog import (CONTAINER_RE, SANDBOX_LABEL_KEY, SANDBOX_LABEL_VALUE, Catalog,
                             CatalogError)
from harness.command import CommandResult, CommandRunner
from harness.faults import (CONTAINER_FAULTS, DEPLOYMENT_FAULTS, IMPLEMENTED_FAULTS, FaultNotSupported,
                            FaultSpec)

DOCKER = "docker"
PROXY_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
TAG_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,40}$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
COMPOSE_FILE_RE = re.compile(r"^/?[A-Za-z0-9._/-]{1,200}$")
TOXIC_NAME = "cd_harness_latency"

# Fixed scripts executed inside a catalog container with `docker exec -d <container> python3 -c <SCRIPT> <args>`.
# Parameters travel as separate argv items and are read from sys.argv: nothing is interpolated.
CPU_HOG_SCRIPT = (
    "import sys,time\n"
    "end=time.time()+int(sys.argv[1])\n"
    "while time.time()<end:\n"
    "    sum(i*i for i in range(10000))\n"
)
MEMORY_HOG_SCRIPT = (
    "import sys,time\n"
    "step,cap,secs=int(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3])\n"
    "end=time.time()+secs\n"
    "held=[]\n"
    "while time.time()<end:\n"
    "    if len(held)*step<cap:\n"
    "        held.append(bytearray(step*1048576))\n"
    "    time.sleep(1)\n"
)


class InjectorError(RuntimeError):
    pass


class TargetError(InjectorError):
    """Target is not a validated, labelled catalog container."""


@dataclass(frozen=True)
class InjectionRecord:
    fault: FaultSpec
    commands: tuple[tuple[str, ...], ...] = ()
    http: tuple[tuple[str, str], ...] = ()


class Injector(Protocol):
    def apply(self, fault: FaultSpec) -> InjectionRecord: ...
    def revert(self, fault: FaultSpec) -> InjectionRecord: ...
    def container_running(self, service: str) -> bool: ...


@dataclass(frozen=True)
class InjectorConfig:
    """Injector-only configuration. Variables are HARNESS_*; none is shared with CD_* components."""
    timeout: float = 30.0
    compose_file: str | None = None
    compose_project: str | None = None
    image_tag_env: str = "CD_API_IMAGE_TAG"
    toxiproxy_url: str = "http://127.0.0.1:8474"
    toxiproxy_token_file: str | None = None
    allowed_proxies: tuple[str, ...] = ("api-app-db",)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "InjectorConfig":
        env = os.environ if env is None else env
        proxies = env.get("HARNESS_TOXIPROXY_PROXIES")
        return cls(
            timeout=float(env.get("HARNESS_DOCKER_TIMEOUT", "30")),
            compose_file=env.get("HARNESS_COMPOSE_FILE"),
            compose_project=env.get("HARNESS_COMPOSE_PROJECT"),
            image_tag_env=env.get("HARNESS_IMAGE_TAG_ENV", "CD_API_IMAGE_TAG"),
            toxiproxy_url=env.get("HARNESS_TOXIPROXY_URL", "http://127.0.0.1:8474"),
            toxiproxy_token_file=env.get("HARNESS_TOXIPROXY_TOKEN_FILE"),
            allowed_proxies=tuple(p for p in proxies.split(",") if p) if proxies else ("api-app-db",),
        )


# --------------------------------------------------------------------------- target validation

def resolve_container(catalog: Catalog, service: str | None) -> str:
    """Service name -> container; both the name and the container must come from the catalog."""
    if not service:
        raise TargetError("fault has no target service")
    try:
        container = catalog.container_of(service)
    except CatalogError as e:
        raise TargetError(str(e)) from None
    if not CONTAINER_RE.match(container) or container not in catalog.containers():
        raise TargetError(f"container {container!r} is not a valid catalog container")
    return container


def inspect_label_argv(container: str) -> list[str]:
    return [DOCKER, "inspect", "--format",
            '{{index .Config.Labels "' + SANDBOX_LABEL_KEY + '"}}', container]


def inspect_running_argv(container: str) -> list[str]:
    return [DOCKER, "inspect", "--format", "{{.State.Running}}", container]


# --------------------------------------------------------------------------- Toxiproxy HTTP

class HttpClient(Protocol):
    def request(self, method: str, url: str, body: bytes | None, headers: Mapping[str, str],
                timeout: float) -> tuple[int, bytes]: ...


class UrllibHttpClient:
    def request(self, method: str, url: str, body: bytes | None, headers: Mapping[str, str],
                timeout: float) -> tuple[int, bytes]:
        if not url.startswith(("http://", "https://")):
            raise InjectorError("toxiproxy url must be http(s)")
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError as e:
            raise InjectorError(f"toxiproxy unreachable: {e.reason}") from None


# --------------------------------------------------------------------------- Docker injector

def _bounded(params: Mapping[str, Any], key: str, lo: int, hi: int, default: int | None = None) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise InjectorError(f"param {key} must be an integer in [{lo}, {hi}]")
    return value


class DockerInjector:
    def __init__(self, catalog: Catalog, runner: CommandRunner, config: InjectorConfig | None = None,
                 http: HttpClient | None = None) -> None:
        self._catalog = catalog
        self._runner = runner
        self._cfg = config or InjectorConfig()
        self._http = http or UrllibHttpClient()

    # -- validation
    def _target(self, service: str | None) -> str:
        container = resolve_container(self._catalog, service)
        argv = inspect_label_argv(container)
        res = self._runner.run(argv, timeout=self._cfg.timeout)
        if res.returncode != 0:
            raise TargetError(f"cannot inspect {container}: rc={res.returncode}")
        if res.stdout.strip() != SANDBOX_LABEL_VALUE:
            raise TargetError(f"{container} does not carry {SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}")
        return container

    def _run(self, argv: Sequence[str], rec: list[tuple[str, ...]], env: Mapping[str, str] | None = None,
             ok_codes: tuple[int, ...] = (0,)) -> CommandResult:
        rec.append(tuple(argv))
        res = self._runner.run(argv, timeout=self._cfg.timeout, env=env)
        if res.returncode not in ok_codes:
            raise InjectorError(f"{argv[1] if len(argv) > 1 else argv[0]} failed rc={res.returncode}")
        return res

    # -- interface
    def container_running(self, service: str) -> bool:
        container = self._target(service)
        res = self._runner.run(inspect_running_argv(container), timeout=self._cfg.timeout)
        return res.returncode == 0 and res.stdout.strip() == "true"

    def apply(self, fault: FaultSpec) -> InjectionRecord:
        if fault.type not in IMPLEMENTED_FAULTS:
            raise FaultNotSupported(f"fault type {fault.type!r} is not implemented by DockerInjector")
        cmds: list[tuple[str, ...]] = []
        http: list[tuple[str, str]] = []
        if fault.type in ("latency_toxic", "proxy_disable"):
            self._target(fault.target)  # the catalog service whose link is degraded must still be a sandbox target
            self._toxiproxy_apply(fault, http)
        elif fault.type in DEPLOYMENT_FAULTS:
            self._deploy(fault, str(fault.params.get("new_tag")), cmds)
        else:
            container = self._target(fault.target)
            if fault.type == "container_stop":
                self._run([DOCKER, "stop", container], cmds)
            elif fault.type == "container_kill":
                self._run([DOCKER, "kill", container], cmds)
            elif fault.type == "cpu_hog":
                secs = _bounded(fault.params, "duration_seconds", 5, 3600, 300)
                self._run([DOCKER, "exec", "-d", container, "python3", "-c", CPU_HOG_SCRIPT, str(secs)], cmds)
            else:  # memory_hog
                step = _bounded(fault.params, "mb_per_second", 1, 64, 8)
                cap = _bounded(fault.params, "max_mb", 16, 4096, 1024)
                secs = _bounded(fault.params, "duration_seconds", 5, 3600, 600)
                self._run([DOCKER, "exec", "-d", container, "python3", "-c", MEMORY_HOG_SCRIPT,
                           str(step), str(cap), str(secs)], cmds)
        return InjectionRecord(fault, tuple(cmds), tuple(http))

    def revert(self, fault: FaultSpec) -> InjectionRecord:
        if fault.type not in IMPLEMENTED_FAULTS:
            raise FaultNotSupported(f"fault type {fault.type!r} is not implemented by DockerInjector")
        cmds: list[tuple[str, ...]] = []
        http: list[tuple[str, str]] = []
        if fault.type in ("latency_toxic", "proxy_disable"):
            self._toxiproxy_revert(fault, http)
        elif fault.type in DEPLOYMENT_FAULTS:
            self._deploy(fault, str(fault.params.get("previous_tag")), cmds)
        else:
            container = self._target(fault.target)
            if fault.type in CONTAINER_FAULTS:
                self._run([DOCKER, "start", container], cmds)
            else:  # hogs live in the container: stop and start removes them
                self._run([DOCKER, "stop", container], cmds)
                self._run([DOCKER, "start", container], cmds)
        return InjectionRecord(fault, tuple(cmds), tuple(http))

    # -- bad deployment: fixed docker compose argv, image tag from an environment variable
    def _deploy(self, fault: FaultSpec, tag: str, cmds: list[tuple[str, ...]]) -> None:
        cfg = self._cfg
        service = str(fault.params.get("service", ""))
        self._target(service)
        if not (cfg.compose_file and COMPOSE_FILE_RE.match(cfg.compose_file) and ".." not in cfg.compose_file):
            raise InjectorError("HARNESS_COMPOSE_FILE is missing or invalid")
        if not (cfg.compose_project and PROJECT_RE.match(cfg.compose_project)):
            raise InjectorError("HARNESS_COMPOSE_PROJECT is missing or invalid")
        if not ENV_NAME_RE.match(cfg.image_tag_env):
            raise InjectorError("image tag variable name is invalid")
        if not TAG_RE.match(tag):
            raise InjectorError("image tag is invalid")
        argv = [DOCKER, "compose", "-f", cfg.compose_file, "-p", cfg.compose_project,
                "up", "-d", "--no-deps", "--force-recreate", service]
        self._run(argv, cmds, env={cfg.image_tag_env: tag})

    # -- Toxiproxy
    def _toxi(self, method: str, path: str, payload: dict[str, Any] | None, http: list[tuple[str, str]],
              ok: tuple[int, ...]) -> None:
        headers = {"Content-Type": "application/json"}
        if self._cfg.toxiproxy_token_file:
            token = Path(self._cfg.toxiproxy_token_file).read_text(encoding="utf-8").strip()
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload).encode() if payload is not None else None
        http.append((method, path))
        status, _ = self._http.request(method, self._cfg.toxiproxy_url.rstrip("/") + path, body, headers,
                                       self._cfg.timeout)
        if status not in ok:
            raise InjectorError(f"toxiproxy {method} {path} returned {status}")

    def _proxy(self, fault: FaultSpec) -> str:
        proxy = str(fault.params.get("proxy", ""))
        if not PROXY_RE.match(proxy) or proxy not in self._cfg.allowed_proxies:
            raise InjectorError(f"proxy {proxy!r} is not in the allowed proxy list")
        return proxy

    def _toxiproxy_apply(self, fault: FaultSpec, http: list[tuple[str, str]]) -> None:
        proxy = self._proxy(fault)
        if fault.type == "proxy_disable":
            self._toxi("POST", f"/proxies/{proxy}", {"enabled": False}, http, (200,))
            return
        payload = {
            "name": TOXIC_NAME, "type": "latency", "stream": "downstream", "toxicity": 1.0,
            "attributes": {"latency": _bounded(fault.params, "latency_ms", 1, 60000, 300),
                           "jitter": _bounded(fault.params, "jitter_ms", 0, 60000, 0)},
        }
        self._toxi("POST", f"/proxies/{proxy}/toxics", payload, http, (200, 201))

    def _toxiproxy_revert(self, fault: FaultSpec, http: list[tuple[str, str]]) -> None:
        proxy = self._proxy(fault)
        if fault.type == "proxy_disable":
            self._toxi("POST", f"/proxies/{proxy}", {"enabled": True}, http, (200,))
        else:
            self._toxi("DELETE", f"/proxies/{proxy}/toxics/{TOXIC_NAME}", None, http, (200, 204, 404))


# --------------------------------------------------------------------------- Fake injector (tests)

class FakeInjector:
    """In-memory injector with the same validation as DockerInjector.

    `labels` maps container -> sandbox label value (default: every catalog container is labelled).
    Faults are tracked so a fake API can model what Cloud Doctor's actions change.
    """

    def __init__(self, catalog: Catalog, labels: Mapping[str, str] | None = None) -> None:
        self._catalog = catalog
        self.labels = dict(labels) if labels is not None else {c: SANDBOX_LABEL_VALUE for c in catalog.containers()}
        self.running = {c: True for c in catalog.containers()}
        self.active: list[FaultSpec] = []
        self.calls: list[tuple[str, FaultSpec]] = []

    def _target(self, service: str | None) -> str:
        container = resolve_container(self._catalog, service)
        if self.labels.get(container) != SANDBOX_LABEL_VALUE:
            raise TargetError(f"{container} does not carry {SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}")
        return container

    def container_running(self, service: str) -> bool:
        return self.running[self._target(service)]

    def apply(self, fault: FaultSpec) -> InjectionRecord:
        if fault.type not in IMPLEMENTED_FAULTS:
            raise FaultNotSupported(f"fault type {fault.type!r} is not implemented")
        container = self._target(fault.target)
        self.calls.append(("apply", fault))
        if fault.type in CONTAINER_FAULTS:
            self.running[container] = False
        if fault not in self.active:
            self.active.append(fault)
        return InjectionRecord(fault)

    def revert(self, fault: FaultSpec) -> InjectionRecord:
        container = self._target(fault.target)
        self.calls.append(("revert", fault))
        if fault.type in CONTAINER_FAULTS or fault.type in ("cpu_hog", "memory_hog"):
            self.running[container] = True
        self.active = [f for f in self.active if f != fault]
        return InjectionRecord(fault)

    # -- what Cloud Doctor's actuator does to the sandbox (used by fake APIs in tests)
    def external_action(self, action_id: str, service: str) -> None:
        container = resolve_container(self._catalog, service)
        if action_id == "restart_service":
            self.running[container] = True
            self.active = [f for f in self.active
                           if not (f.target == service and f.type in ("cpu_hog", "memory_hog", *CONTAINER_FAULTS))
                           or (f.persistent and f.type in CONTAINER_FAULTS)]
        elif action_id == "rollback_service":
            self.active = [f for f in self.active if not (f.type == "bad_deployment" and f.target == service)]

    def fault_effective(self) -> bool:
        return any(f.type != "benign_deployment" for f in self.active)


class PersistentFaultWatcher:
    """Re-applies a container fault after Cloud Doctor restarts the container.

    `step()` is one watcher iteration; the runner calls it every poll tick, so it is deterministic and needs
    no thread. If the container is running again it is stopped (or killed) again, at most
    `max_reapplications` times. This is how EXP-10 (failed remediation) is produced.
    """

    def __init__(self, injector: Injector, fault: FaultSpec) -> None:
        if fault.type not in CONTAINER_FAULTS or not fault.persistent:
            raise InjectorError("watcher needs a persistent container_stop/container_kill fault")
        self._injector = injector
        self._fault = fault
        self.reapplications = 0
        self.gave_up = False

    def step(self) -> InjectionRecord | None:
        if self.reapplications >= self._fault.max_reapplications:
            self.gave_up = True
            return None
        assert self._fault.target is not None
        if not self._injector.container_running(self._fault.target):
            return None
        self.reapplications += 1
        return self._injector.apply(self._fault)
