"""Scenario loading and validation (JSON Schema plus catalog/semantic checks)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from harness.catalog import Catalog
from harness.faults import CONTAINER_FAULTS, IMPLEMENTED_FAULTS, FaultSpec
from harness.paths import SCENARIO_DIR, SCENARIO_SCHEMA

API_METRICS = ("error_ratio", "latency_p95_seconds", "throughput_rps", "queue_depth", "up")
TIMELINE_EVENT_NAMES = ("container_event", "deploy_event")
STATUS_NAMES = ("prometheus", "logs", "database", "actuator", "policy_layer2", "llm", "missing_signal_state")
ACTION_IDS = ("restart_service", "rollback_service", "scale_service", "clear_cache", "isolate_dependency", "escalate")
NON_CATALOG_FAULTS = ("none", "telemetry_outage")


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Scenario:
    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def is_draft(self) -> bool:
        return self.raw["status"] == "draft"

    @property
    def fault(self) -> FaultSpec:
        return FaultSpec.from_dict(self.raw["fault"])

    @property
    def decoy(self) -> tuple[FaultSpec, int] | None:
        d = self.raw.get("decoy")
        return (FaultSpec.from_dict(d["fault"]), int(d["lead_seconds"])) if d else None

    @property
    def timing(self) -> dict[str, Any]:
        return self.raw["timing"]

    @property
    def abort(self) -> dict[str, Any]:
        return self.raw["abort"]

    @property
    def affected_services(self) -> list[str]:
        return list(self.raw["affected_services"])

    @property
    def cause_class(self) -> list[str]:
        return list(self.raw["ground_truth"]["cause_equivalence_class"])

    @property
    def decoy_causes(self) -> list[str]:
        return list(self.raw["ground_truth"]["decoy_causes"])

    @property
    def max_attempts(self) -> int:
        return int(self.raw["max_attempts"])


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(SCENARIO_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(raw: Any) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in sorted(_schema_validator().iter_errors(raw), key=lambda e: list(map(str, e.absolute_path)))]


def semantic_errors(raw: dict[str, Any], catalog: Catalog, file_stem: str | None = None) -> list[str]:
    """Checks that JSON Schema cannot express. Returns human-readable errors."""
    errs: list[str] = []
    svc = catalog.services

    def need_service(name: str | None, where: str) -> None:
        if name is not None and name not in svc:
            errs.append(f"{where}: service {name!r} is not in the catalog")

    if file_stem and file_stem.lower() != raw["id"].lower():
        errs.append(f"id {raw['id']} does not match file name {file_stem}")
    for t in raw["targets"]:
        need_service(t, "targets")
    for s in raw["affected_services"]:
        need_service(s, "affected_services")
    faults = [("fault", raw["fault"])] + ([("decoy.fault", raw["decoy"]["fault"])] if "decoy" in raw else [])
    for where, f in faults:
        ftype = f["type"]
        if ftype in NON_CATALOG_FAULTS:
            if f["target"] is not None and ftype == "telemetry_outage":
                errs.append(f"{where}: telemetry_outage target must be null (telemetry is not a catalog service)")
        else:
            if f["target"] is None:
                errs.append(f"{where}: target is required for {ftype}")
            need_service(f["target"], f"{where}.target")
            if f["target"] is not None and f["target"] not in raw["targets"]:
                errs.append(f"{where}.target {f['target']!r} must be listed in targets")
        if f["persistent"] and ftype not in CONTAINER_FAULTS:
            errs.append(f"{where}: persistent mode is only supported for {CONTAINER_FAULTS}")
        if where == "fault" and raw["is_control"] != (ftype == "none"):
            errs.append("is_control must be true exactly when fault.type is none")
        if ftype in ("bad_deployment", "benign_deployment"):
            for k in ("service", "new_tag", "previous_tag"):
                if k not in f["params"]:
                    errs.append(f"{where}.params.{k} is required for {ftype}")
            if f["params"].get("service") not in raw["targets"]:
                errs.append(f"{where}.params.service must be listed in targets")
        if ftype in ("latency_toxic", "proxy_disable") and "proxy" not in f["params"]:
            errs.append(f"{where}.params.proxy is required for {ftype}")
    for item in raw["steady_state"]:
        need_service(item["service"], "steady_state")
    gt = raw["ground_truth"]
    need_service(gt["cause_service"], "ground_truth.cause_service")
    if not raw["is_control"] and not gt["cause_equivalence_class"]:
        errs.append("ground_truth.cause_equivalence_class must not be empty for a fault scenario")
    if set(gt["cause_equivalence_class"]) & set(gt["decoy_causes"]):
        errs.append("a decoy cause is also in the equivalence class")
    acc = raw["accepted_remediation"]
    for a in acc["actions"]:
        need_service(a["service"], "accepted_remediation")
        s = svc.get(a["service"])
        if s and a["action_id"] not in s.allowed_actions:
            errs.append(f"accepted action {a['action_id']} is not in the catalog allowed_actions of {a['service']}")
    if acc["outcome"] == "no_action" and acc["actions"]:
        errs.append("outcome no_action must not list actions")
    if acc["outcome"] in ("mitigated", "either") and not acc["actions"]:
        errs.append(f"outcome {acc['outcome']} needs at least one accepted action")
    tm = raw["timing"]
    if tm["baseline_timeout_seconds"] < tm["baseline_seconds"]:
        errs.append("baseline_timeout_seconds must be >= baseline_seconds")
    if tm["max_duration_seconds"] < tm["detection_deadline_seconds"]:
        errs.append("max_duration_seconds must be >= detection_deadline_seconds")
    if raw["status"] == "draft" and "draft_note" not in raw:
        errs.append("a draft scenario needs a draft_note")
    seen: set[str] = set()
    for sig in raw["recoverability"]["required_signals"]:
        if sig["id"] in seen:
            errs.append(f"duplicate signal id {sig['id']}")
        seen.add(sig["id"])
        if sig["source"] != "status":
            need_service(sig.get("service"), f"signal {sig['id']}")
        if sig["source"] == "topology" and not (sig.get("service") and sig.get("to")):
            errs.append(f"signal {sig['id']}: topology needs service and to")
    return errs


def warnings(raw: dict[str, Any]) -> list[str]:
    out = []
    for where, f in [("fault", raw["fault"])] + ([("decoy.fault", raw["decoy"]["fault"])] if "decoy" in raw else []):
        if f["type"] != "none" and f["type"] not in IMPLEMENTED_FAULTS:
            out.append(f"{where}.type {f['type']} is not implemented by DockerInjector")
    if raw["status"] == "draft":
        out.append("draft scenario: refused by the runner unless --allow-draft")
    return out


def load_scenario(path: str | Path, catalog: Catalog) -> Scenario:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    errs = schema_errors(raw)
    if errs:
        raise ScenarioError(f"{path.name}: " + "; ".join(errs))
    errs = semantic_errors(raw, catalog, path.stem)
    if errs:
        raise ScenarioError(f"{path.name}: " + "; ".join(errs))
    return Scenario(raw)


def load_all(catalog: Catalog, directory: str | Path = SCENARIO_DIR) -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    for p in sorted(Path(directory).glob("exp-*.yaml")):
        s = load_scenario(p, catalog)
        out[s.id] = s
    return out


def find_scenario(catalog: Catalog, name: str, directory: str | Path = SCENARIO_DIR) -> Scenario:
    """Accepts EXP-01, exp-01 or a path."""
    if re.fullmatch(r"(?i)exp-\d{2}", name):
        return load_scenario(Path(directory) / f"{name.lower()}.yaml", catalog)
    return load_scenario(name, catalog)
