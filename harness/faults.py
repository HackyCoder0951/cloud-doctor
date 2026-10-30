"""Fault specification shared by scenarios, injectors and the runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# Fault types the DockerInjector can apply. Others in scenario.json are declared but NOT implemented.
CONTAINER_FAULTS = ("container_stop", "container_kill")
IMPLEMENTED_FAULTS = (
    "container_stop", "container_kill", "cpu_hog", "memory_hog",
    "bad_deployment", "benign_deployment", "latency_toxic", "proxy_disable",
)
DEPLOYMENT_FAULTS = ("bad_deployment", "benign_deployment")


class FaultNotSupported(RuntimeError):
    """The fault type is declared in the schema but the injector cannot apply it."""


@dataclass(frozen=True)
class FaultSpec:
    type: str
    target: str | None
    params: Mapping[str, Any] = field(default_factory=dict)
    persistent: bool = False
    max_reapplications: int = 10

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "FaultSpec":
        return cls(
            type=d["type"],
            target=d.get("target"),
            params=dict(d.get("params", {})),
            persistent=bool(d.get("persistent", False)),
            max_reapplications=int(d.get("max_reapplications", 10)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "target": self.target, "params": dict(self.params),
                "persistent": self.persistent, "max_reapplications": self.max_reapplications}
