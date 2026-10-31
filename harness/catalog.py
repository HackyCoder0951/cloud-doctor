"""Read-only view of the service catalog (infra/catalog/services.yaml)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CONTAINER_RE = re.compile(r"^cd-[a-z0-9-]{2,40}$")
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
# The sandbox label is a fixed constant in every docker argv the harness builds.
SANDBOX_LABEL_KEY = "cloud-doctor.sandbox"
SANDBOX_LABEL_VALUE = "true"


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    kind: str
    container: str
    depends_on: tuple[tuple[str, str], ...]
    allowed_actions: tuple[str, ...]
    has_metrics: bool


@dataclass(frozen=True)
class Catalog:
    services: dict[str, Service]
    sandbox_label: str

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("services"), list):
            raise CatalogError("catalog has no services list")
        label = data.get("sandbox_label", f"{SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}")
        if label != f"{SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}":
            raise CatalogError(f"unexpected sandbox_label {label!r}")
        services: dict[str, Service] = {}
        for item in data["services"]:
            name, container = item.get("name"), item.get("container")
            if not isinstance(name, str) or not SERVICE_RE.match(name):
                raise CatalogError(f"bad service name {name!r}")
            if not isinstance(container, str) or not CONTAINER_RE.match(container):
                raise CatalogError(f"bad container name {container!r} for {name}")
            services[name] = Service(
                name=name,
                kind=item.get("kind", ""),
                container=container,
                depends_on=tuple((d["service"], d["kind"]) for d in item.get("depends_on", [])),
                allowed_actions=tuple(item.get("allowed_actions", [])),
                has_metrics="metrics" in item,
            )
        return cls(services=services, sandbox_label=label)

    def container_of(self, service: str) -> str:
        try:
            return self.services[service].container
        except KeyError:
            raise CatalogError(f"service {service!r} is not in the catalog") from None

    def containers(self) -> set[str]:
        return {s.container for s in self.services.values()}

    def has_edge(self, source: str, target: str) -> bool:
        svc = self.services.get(source)
        return bool(svc) and any(dep == target for dep, _ in svc.depends_on)
