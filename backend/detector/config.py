"""Detector configuration loaded from backend/config/detector.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "detector.yaml"


@dataclass
class RuleConfig:
    name: str
    layer: str
    severity: str
    health: str
    kinds: list[str]
    enter_after: int
    leave_after: int
    params: dict = field(default_factory=dict)


@dataclass
class DetectorConfig:
    poll_interval_seconds: int
    low_traffic_floor_rps: float
    incident_window_seconds: int
    restart_event_ttl_polls: int
    metrics: dict[str, str]
    rules: dict[str, RuleConfig]

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> DetectorConfig:
        doc = yaml.safe_load(Path(path or os.environ.get("CD_DETECTOR_CONFIG") or DEFAULT_PATH).read_text())
        hyst = doc.get("hysteresis", {})
        rules = {}
        for name, r in doc["rules"].items():
            params = {k: v for k, v in r.items() if k not in ("layer", "severity", "health", "kinds", "enter_after", "leave_after")}
            rules[name] = RuleConfig(name, r["layer"], r["severity"], r["health"], r["kinds"],
                                     r.get("enter_after", hyst.get("enter_after", 3)), r.get("leave_after", hyst.get("leave_after", 3)), params)
        return cls(doc["poll_interval_seconds"], float(doc["low_traffic_floor_rps"]), doc["incident_window_seconds"],
                   doc.get("restart_event_ttl_polls", 6), doc["metrics"], rules)

    def query(self, metric: str, service: str, dependency: str = "") -> str:
        return Template(self.metrics[metric]).safe_substitute(service=service, dependency=dependency)
