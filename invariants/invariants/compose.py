"""Hybrid composition of Layer 1 and Layer 2: a conjunction in which Layer 2 can only tighten."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .context import ValidationResult
from .rules import RULE_IDS

INVARIANTS_VERSION = "inv-0.1"
_SEVERITY = {"allow": 0, "allow_with_approval": 1, "deny": 2}
_BY_SEVERITY = {v: k for k, v in _SEVERITY.items()}
_RULE = re.compile(r"I-[0-9]{2}")
_PLAN_ID = re.compile(r"PL-[0-9]{4,}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_PLACEHOLDER_ID = "PL-0000"
_PLACEHOLDER_HASH = "sha256:" + "0" * 64


def _clip(text) -> str:
    return str(text)[:300]


def _normalise_l1(l1):
    """-> (severity, rule_ids, reasons, plan_id, plan_hash). Anything unreadable is a deny."""
    if isinstance(l1, ValidationResult):
        if not l1.ok and not l1.pending_approval:
            return 2, list(l1.rule_ids), list(l1.reasons), l1.plan_id, l1.plan_hash
        if l1.pending_approval:
            ids = sorted(set(l1.passed_rule_ids) | {"I-03"})
            return 1, ids, ["Layer 1 passes; a human approval bound to plan_hash is required"], l1.plan_id, l1.plan_hash
        return (1 if l1.requires_approval else 0), list(l1.passed_rule_ids), list(l1.reasons), l1.plan_id, l1.plan_hash
    if isinstance(l1, dict):
        result = l1.get("result")
        ids = l1.get("rule_ids")
        if result in ("pass", "deny") and isinstance(ids, list) and all(isinstance(i, str) and _RULE.fullmatch(i) for i in ids):
            if result == "deny":
                return 2, ids, [], l1.get("plan_id"), l1.get("plan_hash")
            return (1 if l1.get("requires_approval") is True else 0), ids, [], l1.get("plan_id"), l1.get("plan_hash")
    return 2, ["I-08"], ["Layer 1 result missing or malformed"], None, None


def _normalise_l2(l2):
    """-> (severity, l2_record, reasons). Any Layer 2 problem is a deny."""
    def deny(rule, why, **extra):
        record = {"result": "deny", "rule_ids": [rule], "bundle_signed": False}
        record.update(extra)
        return 2, record, [why]

    if not isinstance(l2, dict):
        return deny("L2-MALFORMED", "Layer 2 result missing or malformed")
    result, ids = l2.get("result"), l2.get("rule_ids")
    if result not in _SEVERITY or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return deny("L2-MALFORMED", "Layer 2 result missing or malformed")
    revision = l2.get("bundle_revision")
    extra = {"bundle_revision": revision} if isinstance(revision, str) else {}
    if l2.get("stale") is True or l2.get("problem"):
        return deny("L2-UNHEALTHY", "Layer 2 bundle stale or Layer 2 unavailable", **extra)
    if l2.get("bundle_signed") is not True:
        return deny("L2-UNSIGNED-BUNDLE", "Layer 2 bundle is unsigned or its signature state is unknown", **extra)
    record = {"result": result, "rule_ids": [_clip(i) for i in ids], "bundle_signed": True, **extra}
    return _SEVERITY[result], record, [f"Layer 2: {result}"]


def compose_decision(l1, l2=None, *, plan: dict | None = None, decision_id: str | None = None,
                     now: datetime | None = None) -> dict:
    """Build a decision.json-conformant dict. Never raises: any failure yields final=deny.

    final = deny if either layer denies or Layer 2 has any problem; allow_with_approval if either
    layer requires approval; allow otherwise. `l2=None` means Layer 2 is not configured
    (Layer-1-only mode); a Layer 2 that is configured but broken must be passed as a problem/deny.
    """
    try:
        sev1, ids1, reasons1, pid, phash = _normalise_l1(l1)
        record2 = None
        sev2, reasons2 = 0, []
        if l2 is not None:
            sev2, record2, reasons2 = _normalise_l2(l2)
        if isinstance(plan, dict):
            pid = plan.get("plan_id", pid)
            phash = plan.get("plan_hash", phash)
        pid = pid if isinstance(pid, str) and _PLAN_ID.fullmatch(pid) else _PLACEHOLDER_ID
        phash = phash if isinstance(phash, str) and _SHA256.fullmatch(phash) else _PLACEHOLDER_HASH
        final = _BY_SEVERITY[max(sev1, sev2)]
        if decision_id is None:
            digits = int(hashlib.sha256(f"{pid}{phash}".encode()).hexdigest()[:8], 16) % 10**8
            decision_id = f"DEC-{digits:08d}"
        when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = {
            "decision_id": decision_id, "plan_id": pid, "plan_hash": phash,
            "l1": {"result": "deny" if sev1 == 2 else "pass", "rule_ids": ids1},
            "final": final,
            "reasons": [_clip(r) for r in (reasons1 + reasons2)[:50]],
            "invariants_version": INVARIANTS_VERSION, "decided_at": when,
        }
        if record2 is not None:
            out["l2"] = record2
        return out
    except Exception:
        return {
            "decision_id": decision_id if isinstance(decision_id, str) and re.fullmatch(r"DEC-[0-9]{4,}", decision_id) else "DEC-0000",
            "plan_id": _PLACEHOLDER_ID, "plan_hash": _PLACEHOLDER_HASH,
            "l1": {"result": "deny", "rule_ids": ["I-08"]}, "final": "deny",
            "reasons": ["internal error while composing the decision"],
            "invariants_version": INVARIANTS_VERSION,
            "decided_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
