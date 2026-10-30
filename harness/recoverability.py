"""Per-scenario recoverability check (evaluation-framework.md).

Design-time consistency check: for every telemetry signal a scenario says is needed to recover its ground-truth cause,
is that signal something Cloud Doctor can see? It checks the scenario's declarations against the catalog, the public
API surface and contracts/telemetry.md. It does NOT prove the signal appears in a run; that needs recorded runs and
is reported as pending.
"""
from __future__ import annotations

from typing import Any

from harness.catalog import Catalog
from harness.scenario import API_METRICS, STATUS_NAMES, TIMELINE_EVENT_NAMES, Scenario


def _signal(sig: dict, catalog: Catalog) -> tuple[str, str]:
    """Returns (verdict, reason); verdict in visible | unverified | missing."""
    vis, src = sig["visibility"], sig["source"]
    svc = sig.get("service")
    if vis == "unavailable_in_mvp":
        return "missing", "declared not collected in the MVP"
    if src != "status" and svc not in catalog.services:
        return "missing", f"service {svc!r} is not in the catalog"
    if src == "metric":
        if vis == "api":
            return ("visible", "API metric") if sig.get("name") in API_METRICS else ("missing", f"{sig.get('name')!r} is not an API metric name")
        return (("unverified", "backend-internal metric; scrape target exists but the name cannot be verified through the API")
                if catalog.services[svc].has_metrics else ("missing", "service has no scrape target"))
    if src == "log":
        return "visible", "logs endpoint exists for every catalog service"
    if src == "event":
        return (("visible", "timeline event kind") if sig.get("name") in TIMELINE_EVENT_NAMES
                else ("missing", f"{sig.get('name')!r} is not a timeline event kind"))
    if src == "topology":
        return (("visible", "dependency edge in the catalog") if catalog.has_edge(svc, sig.get("to"))
                else ("missing", f"no dependency edge {svc}->{sig.get('to')}"))
    if src == "status":
        return (("visible", "GET /status or ServiceHealth field") if sig.get("name") in STATUS_NAMES
                else ("missing", f"{sig.get('name')!r} is not a status field"))
    return "missing", "unknown source"


def check_scenario(scenario: Scenario, catalog: Catalog) -> dict[str, Any]:
    results, missing_cause, unverified, action_missing = [], [], [], []
    for sig in scenario.raw["recoverability"]["required_signals"]:
        verdict, reason = _signal(sig, catalog)
        results.append({"id": sig["id"], "supports": sig["supports"], "required": sig["required"], "verdict": verdict, "reason": reason})
        if sig["required"] and sig["supports"] == "cause":
            (missing_cause if verdict == "missing" else unverified if verdict == "unverified" else []).append(sig["id"])
        if sig["required"] and sig["supports"] == "action" and verdict == "missing":
            action_missing.append(sig["id"])
    status = "not_recoverable" if missing_cause else "recoverable_unverified" if unverified else "recoverable"
    return {"scenario_id": scenario.id, "status": status, "missing_cause_signals": missing_cause,
            "unverified_cause_signals": unverified, "missing_action_signals": action_missing, "signals": results,
            "observed_in_runs": "pending"}


def check_all(scenarios: dict[str, Scenario], catalog: Catalog) -> dict[str, dict[str, Any]]:
    return {sid: check_scenario(s, catalog) for sid, s in scenarios.items()}
