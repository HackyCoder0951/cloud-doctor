"""Planner: top cause -> typed catalogue plan (contracts/schemas/plan.json) with plan_hash from the local helper.

'Escalate' and 'no action' are valid outputs. Strategy change rule (remediation-loops.md): after a failed attempt the
same action on the same target is not proposed again unless the diagnosis changed; the planner escalates instead.
"""
from __future__ import annotations

from datetime import datetime

from backend import policy_adapter as pa
from backend.domain.catalog import Catalog
from backend.domain.contracts import validate_against_contract
from backend.domain.models import Diagnosis, Plan
from backend.repositories.base import Repository

from .catalogue import risk_for


class Planner:
    def __init__(self, repo: Repository, catalog: Catalog) -> None:
        self.repo, self.catalog = repo, catalog

    def plan(self, incident_id: str, diagnosis: Diagnosis, now: datetime, failed_before: set[tuple[str, str, str]] | None = None) -> Plan:
        top = diagnosis.hypotheses[0]
        rec = diagnosis.recommended_action
        action, params = (rec.action_id, dict(rec.params)) if rec else ("escalate", {"reason": "no recommended action"})
        rationale = f"Top-ranked cause {top.cause_id} (confidence {top.confidence:.2f}, status {top.status}); catalogue remedy {action}."
        failed_before = failed_before or set()
        if action != "escalate" and (top.cause_id, action, params.get("service", "")) in failed_before:
            action, params = "escalate", {"reason": f"{action} on {params.get('service')} already failed and the diagnosis has not changed"}
            rationale = f"Strategy change required: the previous attempt failed for cause {top.cause_id}; escalating instead of repeating."
        refs: list[str] = []
        for c in top.claims:
            for e in c.evidence:
                if e not in refs:
                    refs.append(e)
        refs = refs[:12]
        service = params.get("service")
        plan = {"plan_id": self.repo.next_plan_id(), "incident_id": incident_id, "action_id": action, "params": params,
                "risk_class": risk_for(action, service, self.catalog), "origin": "rule", "evidence_refs": refs,
                "rationale": rationale[:500], "created_at": now.isoformat().replace("+00:00", "Z")}
        plan["plan_hash"] = pa.plan_hash(plan)
        validate_against_contract(plan, "plan")
        model = Plan.model_validate(plan)
        self.repo.save_plan(model)
        return model
