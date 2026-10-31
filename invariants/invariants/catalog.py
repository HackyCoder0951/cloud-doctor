"""Service catalog (topology as code) loader. JSON works without any third-party package."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import yaml_loader

ACTION_IDS = (
    "restart_service", "rollback_service", "scale_service",
    "clear_cache", "isolate_dependency", "escalate",
)
SERVICE_RE = re.compile(r"[a-z][a-z0-9-]{1,40}")
CONTAINER_RE = re.compile(r"cd-[a-z0-9-]{2,40}")
KINDS = ("app", "cache", "queue_worker", "database", "load_generator")
DEFAULT_SANDBOX_LABEL = "cloud-doctor.sandbox=true"


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    kind: str
    container: str
    depends_on: tuple[tuple[str, str], ...]
    allowed_actions: frozenset[str]
    labels: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Catalog:
    services: dict[str, Service]
    sandbox_label: str = DEFAULT_SANDBOX_LABEL
    environment: str = "sandbox"

    @classmethod
    def from_dict(cls, data: dict) -> "Catalog":
        if not isinstance(data, dict):
            raise CatalogError("catalog must be an object")
        if data.get("catalog_version") != 1:
            raise CatalogError("unsupported catalog_version")
        if data.get("environment") != "sandbox":
            raise CatalogError("environment must be 'sandbox'")
        label = data.get("sandbox_label", DEFAULT_SANDBOX_LABEL)
        if not isinstance(label, str) or label.count("=") != 1 or not all(label.split("=")):
            raise CatalogError("sandbox_label must look like key=value")
        raw = data.get("services")
        if not isinstance(raw, list) or not raw:
            raise CatalogError("services must be a non-empty list")
        services: dict[str, Service] = {}
        containers: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise CatalogError("service entry must be an object")
            name, kind, container = item.get("name"), item.get("kind"), item.get("container")
            if not (isinstance(name, str) and SERVICE_RE.fullmatch(name)):
                raise CatalogError(f"bad service name {name!r}")
            if kind not in KINDS:
                raise CatalogError(f"bad kind for {name}")
            if not (isinstance(container, str) and CONTAINER_RE.fullmatch(container)):
                raise CatalogError(f"bad container for {name}")
            if name in services or container in containers:
                raise CatalogError(f"duplicate service or container: {name}")
            actions = item.get("allowed_actions")
            if not isinstance(actions, list) or any(a not in ACTION_IDS for a in actions):
                raise CatalogError(f"bad allowed_actions for {name}")
            deps = []
            for d in item.get("depends_on", []):
                if not isinstance(d, dict) or d.get("kind") not in ("hard", "soft") or not isinstance(d.get("service"), str):
                    raise CatalogError(f"bad dependency for {name}")
                deps.append((d["service"], d["kind"]))
            labels = item.get("labels", {})
            if not isinstance(labels, dict):
                raise CatalogError(f"bad labels for {name}")
            services[name] = Service(name, kind, container, tuple(deps), frozenset(actions), dict(labels))
            containers.add(container)
        for svc in services.values():
            for dep, _ in svc.depends_on:
                if dep not in services:
                    raise CatalogError(f"{svc.name} depends on unknown service {dep}")
        return cls(services, label, "sandbox")

    @classmethod
    def load(cls, path) -> "Catalog":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        suffix = p.suffix.lower()
        if suffix == ".json":
            data = json.loads(text)
        elif suffix in (".yaml", ".yml"):
            data = yaml_loader.load_yaml(text)
        else:
            raise CatalogError(f"unsupported catalog file type: {suffix!r}")
        return cls.from_dict(data)

    # -- lookups ---------------------------------------------------------------------------
    def service(self, name) -> Service | None:
        return self.services.get(name) if isinstance(name, str) else None

    def by_container(self, container) -> Service | None:
        if not isinstance(container, str):
            return None
        for svc in self.services.values():
            if svc.container == container:
                return svc
        return None

    @property
    def sandbox_label_pair(self) -> tuple[str, str]:
        key, value = self.sandbox_label.split("=")
        return key, value

    def depends_transitively(self, service: str, on: str) -> bool:
        """True if `service` (transitively) depends on `on`."""
        seen: set[str] = set()
        stack = [service]
        while stack:
            cur = stack.pop()
            svc = self.services.get(cur)
            if svc is None:
                continue
            for dep, _ in svc.depends_on:
                if dep == on:
                    return True
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return False

    def declared_labels(self, container: str) -> dict:
        """Labels the CATALOG declares for a container (sandbox label + service labels).

        This is NOT a verification of the running container. The actuator checks the real labels
        with `docker inspect`; an in-process dry run may use this as a stand-in.
        """
        svc = self.by_container(container)
        if svc is None:
            return {}
        key, value = self.sandbox_label_pair
        return {**{str(k): str(v) for k, v in svc.labels.items()}, key: value}
