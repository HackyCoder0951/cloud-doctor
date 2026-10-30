"""Adapter to the `invariants` package (Stream C provides it; Stream B consumes it).

Backend code imports ONLY this module for hashing/signing helpers and Layer-1 validation. Two implementations:

  * the real package, used when `import invariants` succeeds (switch: CD_INVARIANTS=auto|real|stub, default auto);
  * ``_StubInvariants`` below: a LOCAL STUB written from the public API and rule table in docs/dev/streams.md.
    >>> THIS IS A STUB, NOT THE SECURITY BOUNDARY. <<< The authoritative Layer 1 lives in the `invariants` package and
    is re-run by the separate actuator process. Never rely on the stub for safety claims.

Fail closed: any exception while validating denies with rule I-08.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from backend.domain.canonical import canonical_json as _canon
from backend.domain.canonical import plan_hash as _plan_hash
from backend.domain.canonical import sha256_tag as _sha
from backend.domain.catalog import Catalog
from backend.domain.contracts import ContractViolation, validate_against_contract
from backend.remediation.catalogue import risk_for

STUB_VERSION = "inv-stub-0.1"
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class PolicyContext:
    catalog: Catalog
    now: datetime
    attempts_used: Callable[[str, str, str], int]
    last_attempt_at: Callable[[str, str, str], datetime | None]
    circuit_open: Callable[[str], bool]
    known_evidence_ids: set[str]
    diagnosis_validated: bool
    top_cause_service: str | None
    approval: dict | None = None
    container_labels: Callable[[str], dict] | None = None


@dataclass
class ValidationResult:
    ok: bool
    rule_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    requires_approval: bool = False


class _StubInvariants:
    """STUB of invariants.* (see module docstring). Implements I-01..I-08 from docs/dev/streams.md."""

    __version__ = STUB_VERSION
    MAX_ATTEMPTS, COOLDOWN_S = 2, 20

    canonical_json = staticmethod(_canon)
    sha256_tag = staticmethod(_sha)
    plan_hash = staticmethod(_plan_hash)

    @staticmethod
    def sign_envelope(envelope: dict, key: bytes) -> str:
        return hmac.new(key, _canon(envelope), hashlib.sha256).hexdigest()

    @staticmethod
    def verify_envelope(envelope: dict, key: bytes) -> bool:
        body = {k: v for k, v in envelope.items() if k != "signature"}
        return hmac.compare_digest(_StubInvariants.sign_envelope(body, key), str(envelope.get("signature", "")))

    @classmethod
    def validate_plan(cls, plan: dict, ctx: PolicyContext) -> ValidationResult:
        deny: dict[str, str] = {}
        needs_approval = False
        try:
            try:
                validate_against_contract(plan, "plan")
            except ContractViolation as exc:
                deny["I-01"] = f"plan does not match the typed schema: {exc.errors[0][:120]}"
            else:
                if plan["plan_hash"] != _plan_hash(plan):
                    deny["I-01"] = "plan_hash does not match the plan content"
            action, params = plan.get("action_id"), plan.get("params", {})
            svc = params.get("service")
            cat = ctx.catalog
            if action != "escalate" or svc:
                if svc is None or svc not in cat.services:
                    deny["I-06"] = "service must be an exact catalog name"
                else:
                    s = cat.get(svc)
                    if ctx.container_labels is not None and ctx.container_labels(s.container).get("cloud-doctor.sandbox") != "true":
                        deny["I-02"] = f"container of {svc} lacks the sandbox label"
                    if action not in s.allowed_actions:
                        deny["I-02"] = f"{action} is not in the allowed_actions of {svc}"
                    floor = risk_for(action, svc, cat)
                    if RISK_ORDER.get(plan.get("risk_class", "high"), 2) < RISK_ORDER[floor]:
                        deny["I-03"] = f"risk_class {plan.get('risk_class')} is lower than the catalogue rule ({floor})"
            floor_risk = plan.get("risk_class", "high")
            if floor_risk == "high":
                deny["I-03"] = "high risk actions are never executable"
            elif floor_risk == "medium" or (svc and svc in cat.services and risk_for(action, svc, cat) == "medium"):
                ap = ctx.approval
                if not ap or ap.get("plan_hash") != plan.get("plan_hash"):
                    needs_approval = True
            if action != "escalate":
                key = (plan["incident_id"], svc or "", action)
                if ctx.circuit_open(plan["incident_id"]):
                    deny["I-04"] = "circuit breaker is open"
                elif ctx.attempts_used(*key) >= cls.MAX_ATTEMPTS:
                    deny["I-04"] = f"attempt budget exhausted ({cls.MAX_ATTEMPTS})"
                else:
                    last = ctx.last_attempt_at(*key)
                    if last is not None and ctx.now - last < timedelta(seconds=cls.COOLDOWN_S):
                        deny["I-04"] = f"cooldown of {cls.COOLDOWN_S}s not elapsed"
            missing = [e for e in plan.get("evidence_refs", []) if e not in ctx.known_evidence_ids]
            if missing or not ctx.diagnosis_validated:
                deny["I-05"] = "evidence reference missing or diagnosis not validated"
            if action in ("restart_service", "rollback_service", "clear_cache", "scale_service") and ctx.top_cause_service \
                    and svc and svc != ctx.top_cause_service:
                deny["I-07"] = f"{svc} is a victim; the top cause is {ctx.top_cause_service}"
        except Exception as exc:  # I-08: fail closed
            return ValidationResult(False, ["I-08"], [f"internal error: {type(exc).__name__}"], False)
        ids = sorted(deny)
        return ValidationResult(not deny, ids, [deny[i] for i in ids], needs_approval and not deny)


def _load() -> tuple[Any, bool]:
    mode = os.environ.get("CD_INVARIANTS", "auto").lower()
    if mode != "stub":
        try:
            mod = importlib.import_module("invariants")
            # the repo has an `invariants/` directory that is a bare namespace package until Stream C lands: require the API
            if all(hasattr(mod, n) for n in ("validate_plan", "canonical_json", "plan_hash", "sign_envelope", "verify_envelope", "Catalog")):
                return mod, True
            raise ImportError("`invariants` is present but does not expose the public API yet")
        except ImportError:
            if mode == "real":
                raise
    return _StubInvariants, False


_impl, IS_REAL = _load()
VERSION: str = getattr(_impl, "__version__", "unknown")
canonical_json = _impl.canonical_json
sha256_tag = _impl.sha256_tag
plan_hash = _impl.plan_hash
sign_envelope = _impl.sign_envelope
verify_envelope = _impl.verify_envelope


def make_context(**kw) -> Any:
    """Build a PolicyContext for whichever implementation is active."""
    if IS_REAL:
        return _impl.PolicyContext(**kw)
    return PolicyContext(**kw)


@dataclass
class PolicyOutcome:
    l1_result: str  # pass | deny
    rule_ids: list[str]
    final: str  # allow | allow_with_approval | deny
    reasons: list[str]
    invariants_version: str


def evaluate(plan: dict, ctx: Any) -> PolicyOutcome:
    """Layer 1 evaluation -> decision.json fields. Layer 2 is not wired (Layer-2-less mode: the safe default)."""
    try:
        res = _impl.validate_plan(plan, ctx)
        ok, rules, reasons, needs = bool(res.ok), list(res.rule_ids), list(res.reasons), bool(res.requires_approval)
    except Exception as exc:  # I-08
        return PolicyOutcome("deny", ["I-08"], "deny", [f"invariant evaluation failed: {type(exc).__name__}"], VERSION)
    if not ok and needs and set(rules) <= {"I-03"} and not getattr(ctx, "approval", None):
        return PolicyOutcome("pass", rules, "allow_with_approval", reasons or ["approval required"], VERSION)  # real pkg may encode it as !ok
    if not ok:
        return PolicyOutcome("deny", rules or ["I-08"], "deny", reasons or ["denied"], VERSION)
    return PolicyOutcome("pass", rules, "allow_with_approval" if needs else "allow", reasons, VERSION)
