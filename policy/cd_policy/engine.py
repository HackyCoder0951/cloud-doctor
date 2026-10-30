"""Glue: minimised input -> OPA -> composition with Layer 1."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from invariants import ValidationResult, compose_decision

from .opa_client import Layer2Client, _problem
from .opa_input import InputError, build_opa_input


class Layer2Policy:
    def __init__(self, client: Layer2Client):
        self._client = client

    def evaluate(self, plan: dict, *, target_kind: Optional[str], confidence: float, counters: dict,
                 tenant: str, channel: str, now: datetime) -> dict:
        try:
            opa_input = build_opa_input(plan, target_kind=target_kind, confidence=confidence, counters=counters,
                                        tenant=tenant, channel=channel, now=now)
        except InputError as exc:
            return _problem("L2-INPUT", f"cannot build a minimised input: {exc}")
        return self._client.evaluate(opa_input)


def decide(plan: dict, l1: ValidationResult, policy: Optional[Layer2Policy], *, target_kind=None, confidence: float = 1.0,
           counters: Optional[dict] = None, tenant: str = "default", channel: str = "C0", now: datetime,
           decision_id: Optional[str] = None) -> dict:
    """`l1` is the Layer 1 result. Layer 2 is consulted only when configured (policy is not None; None
    is Layer-1-only mode) and is recorded even when Layer 1 already denies. The final result can only
    be as permissive as the stricter layer."""
    l2 = None
    if policy is not None:
        l2 = policy.evaluate(plan, target_kind=target_kind, confidence=confidence, counters=counters or {},
                             tenant=tenant, channel=channel, now=now)
    return compose_decision(l1, l2, plan=plan, decision_id=decision_id, now=now)
