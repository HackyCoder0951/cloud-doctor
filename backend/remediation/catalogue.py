"""Catalogue mapping: hypothesis -> typed action (docs/06-self-healing/remediation-patterns.md).

Pure and deterministic. 'escalate' and 'no action' are valid outputs. Risk classes follow the catalogue table:
restart of a stateless service is low; restart of a cache/queue holder is medium (state loss); rollback is medium
(needs approval); anything else the catalog does not allow becomes an escalation.
"""
from __future__ import annotations

from backend.domain.catalog import Catalog

STATEFUL_KINDS = {"cache", "queue_worker"}  # queue_worker restarts are low per EXP-02 (worker holds no state); see risk_for


def risk_for(action_id: str, service: str | None, catalog: Catalog) -> str:
    if action_id == "escalate":
        return "low"
    if action_id == "rollback_service":
        return "medium"
    if action_id in ("scale_service", "isolate_dependency"):
        return "medium"
    kind = catalog.kind(service) if service else ""
    if action_id == "clear_cache":
        return "medium"
    if action_id == "restart_service":
        if kind == "database":
            return "high"
        if kind == "cache":
            return "medium"  # redis restart may lose queued jobs (remediation-patterns.md)
        return "low"
    return "high"


def recommend(cause_id: str, service: str | None, catalog: Catalog, context: dict | None = None) -> dict:
    """Return {"action_id", "params"} for a cause. ``context`` may carry rollback version, restart count, etc."""
    ctx = context or {}

    def escalate(reason: str) -> dict:
        return {"action_id": "escalate", "params": {"reason": reason[:300]}}

    if service is None or service not in catalog.services:
        return escalate(f"no catalogue action for {cause_id}")
    allowed = catalog.get(service).allowed_actions
    if cause_id.endswith("_unavailable"):
        if "restart_service" in allowed:
            return {"action_id": "restart_service", "params": {"service": service}}
        return escalate(f"{service} is unavailable and restart is not allowed for it")
    if cause_id.endswith("_bad_deployment"):
        version = ctx.get("previous_version")
        if "rollback_service" in allowed and version:
            return {"action_id": "rollback_service", "params": {"service": service, "version": version}}
        return escalate(f"bad deployment of {service} but no previous version or rollback not allowed")
    if cause_id.endswith("_memory_exhaustion"):
        if ctx.get("restarts", 0) >= 2:
            return escalate(f"{service} memory exhaustion recurs after restart; a fix or rollback is needed (human)")
        if "restart_service" in allowed:
            return {"action_id": "restart_service", "params": {"service": service}}
    return escalate(f"no safe catalogue action for {cause_id}")
