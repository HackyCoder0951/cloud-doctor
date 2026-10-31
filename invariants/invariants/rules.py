"""Layer 1 invariants I-01..I-08. Deny by default; any internal error denies (I-08)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .canonical import plan_hash as compute_plan_hash
from .catalog import ACTION_IDS, CONTAINER_RE, SERVICE_RE
from .context import PolicyContext, ValidationResult

RULE_IDS = ("I-01", "I-02", "I-03", "I-04", "I-05", "I-06", "I-07", "I-08")

_PLAN_ID = re.compile(r"PL-[0-9]{4,}")
_INCIDENT_ID = re.compile(r"INC-[0-9]{4,}")
_EVIDENCE_ID = re.compile(r"EV-[0-9]{3,}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_VERSION = re.compile(r"[A-Za-z0-9._-]{1,64}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_TOP_KEYS = {"plan_id", "incident_id", "action_id", "params", "risk_class", "origin",
             "evidence_refs", "rationale", "created_at", "plan_hash"}
_ACTION_PARAMS = {  # exact (required, optional) parameter names per action; stricter than plan.json
    "restart_service": ({"service"}, set()),
    "rollback_service": ({"service", "version"}, set()),
    "scale_service": ({"service", "replicas"}, set()),
    "clear_cache": ({"service"}, set()),
    "isolate_dependency": ({"service", "dependency"}, set()),
    "escalate": ({"reason"}, {"service"}),
}
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_PASS_TEXT = {
    "I-01": "catalogue action with typed parameters",
    "I-02": "sandbox-labelled catalogue target",
    "I-03": "risk class within ceiling",
    "I-04": "within attempt budget",
    "I-05": "evidence precondition met",
    "I-06": "parameters match their patterns",
    "I-07": "dependency-aware rule satisfied",
    "I-08": "no internal error",
}


def parse_timestamp(value) -> datetime:
    if not isinstance(value, str) or not _TS.fullmatch(value):
        raise ValueError("bad timestamp")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return dt


def _safe(value, limit: int = 60) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def catalogue_risk(catalog, action: str, service) -> str:
    """Minimum risk the catalogue assigns to (action, service). Service labels may override
    via the key 'risk.<action>' (the catalogue 'says otherwise')."""
    svc = catalog.service(service) if service else None
    if svc is not None:
        override = svc.labels.get(f"risk.{action}")
        if override in _RISK_ORDER:
            return override
    if action == "restart_service":
        kind = svc.kind if svc else None
        if kind == "database":
            return "high"
        if kind == "cache":
            return "medium"
        return "low"
    if action == "escalate":
        return "low"
    return "medium"


def approval_valid(approval, plan: dict, now: datetime) -> tuple[bool, str]:
    """An approval is valid when it is bound to THIS plan_hash and well formed."""
    if not isinstance(approval, dict):
        return False, "no approval supplied"
    if set(approval) - {"approver", "approved_at", "reason", "plan_hash"}:
        return False, "approval has unknown fields"
    approver = approval.get("approver")
    if not isinstance(approver, str) or not approver.strip() or len(approver) > 80:
        return False, "approval has no valid approver"
    ph = approval.get("plan_hash")
    if not isinstance(ph, str) or not _SHA256.fullmatch(ph):
        return False, "approval plan_hash malformed"
    if ph != plan.get("plan_hash"):
        return False, "approval is bound to a different plan_hash"
    try:
        approved_at = parse_timestamp(approval.get("approved_at"))
    except ValueError:
        return False, "approval timestamp invalid"
    if approved_at > now + timedelta(seconds=5):
        return False, "approval is dated in the future"
    return True, "ok"


class _Run:
    def __init__(self):
        self.violations: dict[str, list[str]] = {}
        self.errored = False
        self.pending_approval_only = True  # cleared by any non-approval violation

    def fail(self, rule: str, reason: str, approval_gap: bool = False):
        self.violations.setdefault(rule, []).append(f"{rule}: {reason}"[:300])
        if not approval_gap:
            self.pending_approval_only = False


def _check_i01(plan: dict, ctx: PolicyContext, run: _Run) -> None:
    extra = set(plan) - _TOP_KEYS
    missing = _TOP_KEYS - set(plan)
    if extra:
        run.fail("I-01", f"unknown plan fields {sorted(map(str, extra))[:5]}")
    if missing:
        run.fail("I-01", f"missing plan fields {sorted(missing)}")
    for key, rx in (("plan_id", _PLAN_ID), ("incident_id", _INCIDENT_ID), ("plan_hash", _SHA256)):
        v = plan.get(key)
        if key in plan and not (isinstance(v, str) and rx.fullmatch(v)):
            run.fail("I-01", f"{key} malformed")
    action = plan.get("action_id")
    if action not in ACTION_IDS or not isinstance(action, str):
        run.fail("I-01", f"action {_safe(action)} is not in the catalogue")
    if plan.get("risk_class") not in _RISK_ORDER:
        run.fail("I-01", "risk_class invalid")
    if plan.get("origin") not in ("rule", "llm"):
        run.fail("I-01", "origin invalid")
    refs = plan.get("evidence_refs")
    if not (isinstance(refs, list) and refs and all(isinstance(r, str) and _EVIDENCE_ID.fullmatch(r) for r in refs)):
        run.fail("I-01", "evidence_refs must be a non-empty list of EV ids")
    if not (isinstance(plan.get("rationale"), str) and len(plan["rationale"]) <= 500):
        run.fail("I-01", "rationale must be a string of at most 500 characters")
    try:
        parse_timestamp(plan.get("created_at"))
    except ValueError:
        run.fail("I-01", "created_at invalid")
    params = plan.get("params")
    if not isinstance(params, dict):
        run.fail("I-01", "params must be an object")
        return
    if isinstance(action, str) and action in _ACTION_PARAMS:
        required, optional = _ACTION_PARAMS[action]
        unknown = set(params) - required - optional
        if unknown:
            run.fail("I-01", f"parameters not allowed for {action}: {sorted(map(str, unknown))[:5]}")
        absent = required - set(params)
        if absent:
            run.fail("I-01", f"missing parameters for {action}: {sorted(absent)}")
    replicas = params.get("replicas")
    if "replicas" in params and not (type(replicas) is int and 1 <= replicas <= 5):
        run.fail("I-01", "replicas must be an integer within 1..5")
    for key in ("service", "dependency", "version", "reason"):
        if key in params and not isinstance(params[key], str):
            run.fail("I-01", f"{key} must be a string")
    if isinstance(plan.get("plan_hash"), str) and _SHA256.fullmatch(plan["plan_hash"]):
        if compute_plan_hash(plan) != plan["plan_hash"]:
            run.fail("I-01", "plan_hash does not match the plan content")


def _check_i06(plan: dict, ctx: PolicyContext, run: _Run) -> None:
    params = plan.get("params")
    if not isinstance(params, dict):
        return
    for key in ("service", "dependency"):
        if key in params:
            v = params[key]
            if not (isinstance(v, str) and SERVICE_RE.fullmatch(v)):
                run.fail("I-06", f"{key} {_safe(v)} does not match the service pattern")
            elif ctx.catalog.service(v) is None:
                run.fail("I-06", f"{key} {_safe(v)} is not an exact catalogue service name")
    if "version" in params:
        v = params["version"]
        if not (isinstance(v, str) and _VERSION.fullmatch(v)):
            run.fail("I-06", "version does not match its pattern")
    if "reason" in params:
        v = params["reason"]
        # 'reason' exists only on the non-executing escalate action; it is inert text.
        if not (isinstance(v, str) and len(v) <= 300 and not _CONTROL.search(v)):
            run.fail("I-06", "reason must be at most 300 characters without control characters")
        if plan.get("action_id") != "escalate":
            run.fail("I-06", "free-text reason is only allowed on escalate")


def _check_i02(plan: dict, ctx: PolicyContext, run: _Run) -> None:
    params = plan.get("params")
    if not isinstance(params, dict):
        return
    action = plan.get("action_id")
    if "service" not in params and action == "escalate":
        return
    names = [params.get("service")]
    if plan.get("action_id") == "isolate_dependency":
        names.append(params.get("dependency"))
    for idx, name in enumerate(names):
        svc = ctx.catalog.service(name)
        if svc is None:
            run.fail("I-02", f"target {_safe(name)} is not in the catalogue")
            continue
        if not CONTAINER_RE.fullmatch(svc.container):
            run.fail("I-02", "container name is not a sandbox container name")
            continue
        if idx == 0 and isinstance(action, str) and action not in svc.allowed_actions:
            run.fail("I-02", f"{action} is not allowed for service {svc.name}")
        if ctx.container_labels is None:
            run.fail("I-02", "container label check unavailable")
            continue
        try:
            labels = ctx.container_labels(svc.container)
        except Exception:
            run.fail("I-02", f"could not verify labels of {svc.container}")
            continue
        key, value = ctx.catalog.sandbox_label_pair
        if not isinstance(labels, dict) or labels.get(key) != value:
            run.fail("I-02", f"container {svc.container} lacks label {ctx.catalog.sandbox_label}")


def _check_i03(plan: dict, ctx: PolicyContext, run: _Run) -> tuple[str | None, bool]:
    action = plan.get("action_id")
    declared = plan.get("risk_class")
    params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    if declared not in _RISK_ORDER or action not in ACTION_IDS:
        return None, False  # I-01 already failed
    floor = catalogue_risk(ctx.catalog, action, params.get("service"))
    if _RISK_ORDER[declared] < _RISK_ORDER[floor]:
        run.fail("I-03", f"declared risk {declared} is lower than the catalogue risk {floor}")
    effective = max(declared, floor, key=_RISK_ORDER.__getitem__)
    if effective == "high":
        run.fail("I-03", "high risk is never executable")
    elif effective == "medium":
        valid, why = approval_valid(ctx.approval, plan, ctx.now)
        if not valid:
            # Only a MISSING approval is a pending gap; a supplied approval that is wrong is a hard deny.
            run.fail("I-03", f"medium risk requires an approval bound to plan_hash ({why})",
                     approval_gap=ctx.approval is None)
    elif ctx.approval is not None:
        # An approval that is present but bound to another plan is never ignored silently.
        valid, why = approval_valid(ctx.approval, plan, ctx.now)
        if not valid:
            run.fail("I-03", f"approval supplied but invalid ({why})")
    return effective, effective == "medium"


def _check_i04(plan: dict, ctx: PolicyContext, run: _Run) -> None:
    if plan.get("action_id") == "escalate":
        return  # escalation is the terminal state; it must stay possible when the budget is spent
    params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    incident, service, action = plan.get("incident_id"), params.get("service"), plan.get("action_id")
    if not (isinstance(incident, str) and isinstance(service, str) and isinstance(action, str)):
        run.fail("I-04", "cannot identify incident/service/action")
        return
    if ctx.attempts_used is None or ctx.last_attempt_at is None or ctx.circuit_open is None:
        run.fail("I-04", "attempt, cooldown or circuit-breaker state unavailable")
        return
    if ctx.circuit_open(incident):
        run.fail("I-04", "circuit breaker is open for this incident")
    used = ctx.attempts_used(incident, service, action)
    if type(used) is not int or used < 0:
        run.fail("I-04", "attempt counter invalid")
    elif used >= ctx.max_attempts:
        run.fail("I-04", f"attempt budget exhausted ({used}/{ctx.max_attempts})")
    last = ctx.last_attempt_at(incident, service, action)
    if last is not None:
        if not isinstance(last, datetime) or last.tzinfo is None:
            run.fail("I-04", "last attempt time invalid")
        elif ctx.now - last < timedelta(seconds=ctx.cooldown_seconds):
            run.fail("I-04", f"cooldown of {ctx.cooldown_seconds:g}s has not elapsed")


def _check_i05(plan: dict, ctx: PolicyContext, run: _Run) -> None:
    known = ctx.known_evidence_ids
    refs = plan.get("evidence_refs")
    if known is None or not isinstance(refs, list) or not refs:
        run.fail("I-05", "evidence set unavailable")
    else:
        unknown = [r for r in refs if r not in known]
        if unknown:
            run.fail("I-05", f"unknown evidence ids {unknown[:5]}")
    if ctx.diagnosis_validated is not True:
        run.fail("I-05", "diagnosis did not pass validation")


def _check_i07(plan: dict, ctx: PolicyContext, run: _Run) -> None:
    if plan.get("action_id") != "restart_service":
        return
    cause = ctx.top_cause_service
    if cause is None:
        return
    params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    target = params.get("service")
    if target == cause or params.get("dependency") == cause:
        return
    if ctx.down_services is not None and cause not in ctx.down_services:
        return
    run.fail("I-07", f"{_safe(target)} is a victim; the confirmed cause {_safe(cause)} is down and not addressed")


def validate_plan(plan: dict, ctx: PolicyContext) -> ValidationResult:
    """Run I-01..I-08. Never raises; any internal error yields a deny with I-08."""
    run = _Run()
    plan_id = plan_hash_val = None
    requires_approval = False
    try:
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        if not isinstance(ctx, PolicyContext) or not isinstance(ctx.now, datetime) or ctx.now.tzinfo is None:
            raise ValueError("invalid policy context")
        pid, ph = plan.get("plan_id"), plan.get("plan_hash")
        plan_id = pid if isinstance(pid, str) and _PLAN_ID.fullmatch(pid) else None
        plan_hash_val = ph if isinstance(ph, str) and _SHA256.fullmatch(ph) else None
        for rule, fn in (("I-01", _check_i01), ("I-06", _check_i06), ("I-02", _check_i02),
                         ("I-04", _check_i04), ("I-05", _check_i05), ("I-07", _check_i07)):
            try:
                fn(plan, ctx, run)
            except Exception:
                run.errored = True
                run.fail("I-08", f"internal error while evaluating {rule}")
        try:
            _, requires_approval = _check_i03(plan, ctx, run)
        except Exception:
            run.errored = True
            run.fail("I-08", "internal error while evaluating I-03")
    except Exception as exc:
        run.errored = True
        run.fail("I-08", f"internal error: {type(exc).__name__}")
    violated = [r for r in RULE_IDS if r in run.violations]
    ok = not violated
    passed = [r for r in RULE_IDS if r not in run.violations]
    reasons = [text for r in violated for text in run.violations[r]] if not ok else [f"{r}: {_PASS_TEXT[r]}" for r in passed]
    return ValidationResult(
        ok=ok, rule_ids=violated, reasons=reasons[:50], requires_approval=requires_approval,
        passed_rule_ids=passed, pending_approval=(not ok and violated == ["I-03"] and run.pending_approval_only),
        plan_id=plan_id, plan_hash=plan_hash_val,
    )
