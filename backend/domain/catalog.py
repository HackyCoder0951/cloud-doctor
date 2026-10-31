"""Service catalog (topology as code): loads infra/catalog/services.yaml; the single source of topology."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .contracts import REPO_ROOT


@dataclass(frozen=True)
class Service:
    name: str
    kind: str
    container: str
    depends_on: tuple[tuple[str, str], ...]  # (service, hard|soft)
    metrics_port: int | None
    probe_url: str | None
    allowed_actions: tuple[str, ...]
    slo_availability: float | None = None
    slo_latency_p95: float | None = None


@dataclass
class Catalog:
    services: dict[str, Service] = field(default_factory=dict)
    sandbox_label: str = "cloud-doctor.sandbox=true"

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> Catalog:
        p = Path(path or os.environ.get("CD_CATALOG_PATH") or REPO_ROOT / "infra/catalog/services.yaml")
        if not p.is_absolute() and not p.exists():
            p = REPO_ROOT / p
        doc = yaml.safe_load(p.read_text())
        cat = cls(sandbox_label=doc.get("sandbox_label", "cloud-doctor.sandbox=true"))
        for s in doc["services"]:
            slo = s.get("slo") or {}
            cat.services[s["name"]] = Service(
                name=s["name"], kind=s["kind"], container=s["container"],
                depends_on=tuple((d["service"], d["kind"]) for d in s.get("depends_on", [])),
                metrics_port=(s.get("metrics") or {}).get("port"),
                probe_url=(s.get("health") or {}).get("published_probe_url"),
                allowed_actions=tuple(s.get("allowed_actions", [])),
                slo_availability=slo.get("availability"), slo_latency_p95=slo.get("latency_p95_seconds"),
            )
        for s in cat.services.values():
            for dep, _ in s.depends_on:
                if dep not in cat.services:
                    raise ValueError(f"{s.name} depends on unknown service {dep}")
        return cat

    def names(self) -> list[str]:
        return list(self.services)

    def get(self, name: str) -> Service:
        return self.services[name]

    def kind(self, name: str) -> str:
        return self.services[name].kind

    def dependencies(self, name: str) -> list[str]:
        return [d for d, _ in self.services[name].depends_on]

    def dependents(self, name: str) -> list[str]:
        return [s.name for s in self.services.values() if any(d == name for d, _ in s.depends_on)]

    def neighbours(self, name: str) -> set[str]:
        return set(self.dependencies(name)) | set(self.dependents(name))

    def edges(self) -> list[tuple[str, str, str]]:
        return [(s.name, d, k) for s in self.services.values() for d, k in s.depends_on]

    def depth(self, name: str) -> int:
        """Dependency depth: 0 for leaves (no dependencies); used to order upstream causes before victims."""
        seen: set[str] = set()

        def rec(n: str) -> int:
            if n in seen:
                return 0
            seen.add(n)
            deps = self.dependencies(n)
            return 0 if not deps else 1 + max(rec(d) for d in deps)

        return rec(name)

    def transitive_dependents(self, name: str) -> set[str]:
        out: set[str] = set()
        stack = [name]
        while stack:
            for dep in self.dependents(stack.pop()):
                if dep not in out:
                    out.add(dep)
                    stack.append(dep)
        return out

    def connected_components(self, nodes: set[str]) -> list[set[str]]:
        """Connected components of the dependency graph induced on ``nodes`` (edges undirected).

        The full catalog graph is a single component (everything depends on redis/app-db), so incident
        grouping uses the subgraph induced on the *affected* services, not the whole graph.
        """
        remaining, comps = set(nodes), []
        while remaining:
            seed = remaining.pop()
            comp, stack = {seed}, [seed]
            while stack:
                for n in self.neighbours(stack.pop()) & remaining:
                    remaining.discard(n)
                    comp.add(n)
                    stack.append(n)
            comps.append(comp)
        return comps
