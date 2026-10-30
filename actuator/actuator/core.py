"""Actuator core: verify, re-run Layer 1, execute, audit. Every unexpected error fails closed."""
from __future__ import annotations

import logging
import os
import re
import stat
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

import invariants as inv

from .audit import AuditError, FileAuditSink, fmt, utc_now
from .executor import DockerExecutor, ExecutorError
from .runner import CommandError

log = logging.getLogger("actuator")

_ENVELOPE_KEYS = {"plan", "key_id", "issued_at", "expires_at", "nonce", "approval", "signature"}
_REQUIRED = {"plan", "key_id", "issued_at", "expires_at", "nonce", "signature"}
_KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,40}")
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")
_SIG = re.compile(r"[0-9a-f]{64}")
_IDEM = re.compile(r"[A-Za-z0-9_-]{8,64}")
_PLAN_ID = re.compile(r"PL-[0-9]{4,}")
_INCIDENT = re.compile(r"INC-[0-9]{4,}")
MIN_KEY_BYTES = 16


class BadRequest(Exception):
    """The request is not a well-formed API call (HTTP 400)."""


class KeyFile:
    """HMAC key read from the file named by CD_SIGNING_KEY_FILE; never inline, never logged."""

    def __init__(self, path: str):
        self.path = path

    def get(self) -> bytes:
        st = os.stat(self.path)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise PermissionError("signing key file must be a regular file with mode 0600")
        with open(self.path, "rb") as fh:
            key = fh.read(4096).rstrip(b"\r\n")
        if len(key) < MIN_KEY_BYTES:
            raise ValueError("signing key too short")
        return key


@dataclass
class Assessment:
    refusals: list[str] = field(default_factory=list)   # A-* and I-* ids
    reasons: list[str] = field(default_factory=list)
    plan: dict | None = None
    envelope: dict | None = None
    verified: bool = False
    l1: inv.ValidationResult | None = None

    @property
    def ok(self) -> bool:
        return not self.refusals


def _ts(value):
    try:
        return inv.parse_timestamp(value)
    except Exception:
        return None


class Actuator:
    def __init__(self, *, catalog: inv.Catalog, key_file, key_id: str, audit: FileAuditSink,
                 executor: DockerExecutor, clock: Callable[[], datetime] = utc_now,
                 max_attempts: int = 2, cooldown_seconds: float = 20.0,
                 max_lifetime_seconds: float = 900.0, skew_seconds: float = 2.0):
        self.catalog, self.key_file, self.key_id = catalog, key_file, key_id
        self.audit, self.executor, self.clock = audit, executor, clock
        self.max_attempts, self.cooldown = max_attempts, cooldown_seconds
        self.max_lifetime, self.skew = timedelta(seconds=max_lifetime_seconds), timedelta(seconds=skew_seconds)
        self._lock = threading.RLock()
        self._nonces: dict[str, datetime] = {}
        self._idem: dict[str, dict] = {}                       # key -> {"fp": str, "execution": dict}
        self._attempts: dict[tuple, list[datetime]] = defaultdict(list)
        self._failed: dict[str, int] = defaultdict(int)       # incident -> failed executions
        self._counter = 0
        self._degraded: str | None = None
        self._replay()

    # -- state recovery from the audit trail ---------------------------------------------------
    def _replay(self) -> None:
        pending: dict[str, dict] = {}
        for ev in self.audit.events():
            self._counter = max(self._counter, ev["seq"])
            d = ev.get("detail", {})
            if ev["actor"] != "actuator":
                continue
            if ev["event"] == "execution.started":
                at = _ts(ev["created_at"])
                self._nonces[d["nonce"]] = _ts(d["expires_at"])
                self._attempts[(d["incident_id"], d["service"], d["action_id"])].append(at)
                pending[d["idempotency_key"]] = d
            elif ev["event"] == "execution.finished":
                pending.pop(d["idempotency_key"], None)
                self._idem[d["idempotency_key"]] = {"fp": d["fingerprint"], "execution": d["execution"]}
                if d["execution"]["result"] == "failed":
                    self._failed[d["incident_id"]] += 1
        for key, d in pending.items():  # started but never finished: outcome unknown, never re-run
            self._failed[d["incident_id"]] += 1
            self._idem[key] = {"fp": d["fingerprint"], "execution": {
                "execution_id": d["execution_id"], "plan_id": d["plan_id"], "idempotency_key": key,
                "started_at": d["started_at"], "result": "failed", "executed_argv": d["argv"],
                "detail": "interrupted before completion; outcome unknown; not re-executed"}}

    @property
    def degraded_reason(self) -> str | None:
        if self._degraded:
            return self._degraded
        try:
            self.key_file.get()
        except Exception:
            return "signing key unavailable"
        return None

    # -- checks ---------------------------------------------------------------------------------
    def _context(self, plan: dict, envelope: dict, now: datetime) -> inv.PolicyContext:
        # I-05 evidence existence/diagnosis validation and I-07 (top cause) live in the control
        # plane; the actuator cannot see them. Only a holder of the signing key could produce this
        # envelope, so the signature is the attestation: the plan's own evidence ids are accepted
        # and the diagnosis is taken as validated. Documented in docs/dev/policy/STATUS.md.
        return inv.PolicyContext(
            catalog=self.catalog, now=now,
            attempts_used=lambda i, s, a: len(self._attempts.get((i, s, a), [])),
            last_attempt_at=lambda i, s, a: max(self._attempts[(i, s, a)]) if self._attempts.get((i, s, a)) else None,
            circuit_open=lambda i: self._failed.get(i, 0) >= self.max_attempts,
            known_evidence_ids=set(plan.get("evidence_refs", [])) if isinstance(plan.get("evidence_refs"), list) else set(),
            diagnosis_validated=True, top_cause_service=None, approval=envelope.get("approval"),
            container_labels=self.executor.labels, max_attempts=self.max_attempts,
            cooldown_seconds=self.cooldown,
        )

    def _assess(self, signed: object) -> Assessment:
        a = Assessment()

        def refuse(rule: str, reason: str) -> None:
            a.refusals.append(rule)
            a.reasons.append(f"{rule}: {reason}"[:300])

        if self._degraded:
            refuse("A-DEGRADED", self._degraded)
            return a
        if not isinstance(signed, dict) or set(signed) - _ENVELOPE_KEYS or _REQUIRED - set(signed):
            refuse("A-ENVELOPE", "signed plan envelope malformed")
            return a
        issued, expires = _ts(signed["issued_at"]), _ts(signed["expires_at"])
        if (not isinstance(signed["plan"], dict) or issued is None or expires is None
                or not (isinstance(signed["key_id"], str) and _KEY_ID.fullmatch(signed["key_id"]))
                or not (isinstance(signed["nonce"], str) and _NONCE.fullmatch(signed["nonce"]))
                or not (isinstance(signed["signature"], str) and _SIG.fullmatch(signed["signature"]))
                or ("approval" in signed and not isinstance(signed["approval"], dict))):
            refuse("A-ENVELOPE", "signed plan envelope fields malformed")
            return a
        if signed["key_id"] != self.key_id:
            refuse("A-KEY", "unknown key_id")
            return a
        try:
            key = self.key_file.get()
        except Exception:
            refuse("A-KEY", "signing key unavailable")
            return a
        if not inv.verify_envelope(signed, key):
            refuse("A-SIGNATURE", "signature verification failed")
            return a
        a.verified, a.envelope, a.plan = True, signed, signed["plan"]
        plan, now = a.plan, self.clock()
        if issued > now + self.skew:
            refuse("A-NOT-YET-VALID", "plan is not yet valid")
        if expires <= now:
            refuse("A-EXPIRED", "plan has expired")
        if expires <= issued or expires - issued > self.max_lifetime:
            refuse("A-LIFETIME", "validity window is empty or longer than allowed")
        if inv.plan_hash(plan) != plan.get("plan_hash"):
            refuse("A-HASH", "plan_hash does not match the plan content")
        self._prune(now)
        if signed["nonce"] in self._nonces:
            refuse("A-REPLAY", "nonce already used")
        approval = signed.get("approval")
        if approval is not None and approval.get("plan_hash") != plan.get("plan_hash"):
            refuse("A-APPROVAL", "approval is bound to a different plan_hash")
        a.l1 = inv.validate_plan(plan, self._context(plan, signed, now))
        if not a.l1.ok:
            a.refusals.extend(a.l1.rule_ids)
            a.reasons.extend(a.l1.reasons)
        if plan.get("action_id") != "restart_service":
            refuse("A-UNSUPPORTED", "only restart_service is executable in the MVP")
        return a

    def _prune(self, now: datetime) -> None:
        for nonce in [n for n, exp in self._nonces.items() if exp is None or exp <= now]:
            del self._nonces[nonce]

    # -- API -------------------------------------------------------------------------------------
    def validate(self, request: object) -> dict:
        if not isinstance(request, dict) or set(request) != {"signed_plan"}:
            raise BadRequest("request must be {signed_plan}")
        with self._lock:
            try:
                a = self._assess(request["signed_plan"])
            except Exception:
                log.exception("validate failed closed")
                return self._validate_response(False, ["I-08"], ["I-08: internal error"])
        rules = sorted({r if r.startswith("I-") else "I-08" for r in a.refusals})
        return self._validate_response(a.ok, rules, a.reasons or ["all checks passed"])

    @staticmethod
    def _validate_response(ok: bool, rules: list, reasons: list) -> dict:
        return {"ok": ok, "rule_ids": rules, "reasons": [str(r)[:300] for r in reasons][:50],
                "invariants_version": inv.__version__}

    def execute(self, request: object) -> dict:
        if (not isinstance(request, dict) or set(request) != {"signed_plan", "idempotency_key"}
                or not (isinstance(request["idempotency_key"], str) and _IDEM.fullmatch(request["idempotency_key"]))
                or not isinstance(request["signed_plan"], dict)
                or not isinstance(request["signed_plan"].get("plan"), dict)
                or not (isinstance(request["signed_plan"]["plan"].get("plan_id"), str)
                        and _PLAN_ID.fullmatch(request["signed_plan"]["plan"]["plan_id"]))):
            raise BadRequest("request must be {signed_plan, idempotency_key} with a plan_id")
        key, signed = request["idempotency_key"], request["signed_plan"]
        plan_id = signed["plan"]["plan_id"]
        with self._lock:
            try:
                return {"execution": self._execute(signed, key, plan_id)}
            except Exception:
                log.exception("execute failed closed")
                return {"execution": self._refused(plan_id, key, ["I-08"], "internal error; nothing was executed")}

    def _next_id(self) -> str:
        self._counter += 1
        return f"EX-{self._counter:04d}"

    def _refused(self, plan_id: str, key: str, rules: list, detail: str) -> dict:
        now = fmt(self.clock())
        return {"execution_id": self._next_id(), "plan_id": plan_id, "idempotency_key": key,
                "started_at": now, "ended_at": now, "result": "refused",
                "refusal_rule_ids": sorted(set(rules)), "executed_argv": [], "detail": detail[:500]}

    def _execute(self, signed: dict, key: str, plan_id: str) -> dict:
        fp = inv.sha256_tag(inv.canonical_json(signed))
        prior = self._idem.get(key)
        if prior is not None:
            if prior["fp"] == fp:
                return prior["execution"]           # idempotent: never re-executes
            return self._refused(plan_id, key, ["A-IDEMPOTENCY"], "idempotency_key already used for a different request")
        a = self._assess(signed)
        incident = a.plan.get("incident_id") if a.verified and isinstance(a.plan.get("incident_id"), str) \
            and _INCIDENT.fullmatch(a.plan["incident_id"]) else None
        if not a.ok:
            detail = "; ".join(a.reasons)
            try:
                self.audit.append("policy", "plan.refused", {
                    "plan_id": plan_id, "idempotency_key": key, "rule_ids": a.refusals, "reasons": a.reasons[:10]}, incident)
            except AuditError:
                log.error("audit write failed while recording a refusal")
            return self._refused(plan_id, key, a.refusals, detail)

        plan, env = a.plan, a.envelope
        service = plan["params"]["service"]
        container = self.catalog.service(service).container
        exec_id, started = self._next_id(), self.clock()
        argv = ["docker", "restart", container]
        try:
            self.audit.append("policy", "plan.accepted", {
                "plan_id": plan_id, "plan_hash": plan["plan_hash"], "rule_ids": a.l1.passed_rule_ids,
                "approval": env.get("approval", {}).get("approver") if env.get("approval") else None,
            }, incident)
            self.audit.append("actuator", "execution.started", {
                "execution_id": exec_id, "plan_id": plan_id, "plan_hash": plan["plan_hash"],
                "idempotency_key": key, "fingerprint": fp, "nonce": env["nonce"], "expires_at": env["expires_at"],
                "incident_id": incident, "service": service, "action_id": plan["action_id"],
                "argv": argv, "started_at": fmt(started)}, incident)
        except AuditError:
            return self._refused(plan_id, key, ["A-AUDIT"], "audit write failed; refusing an unauditable action")

        # State is committed BEFORE the command runs so a crash can never allow a second run.
        self._nonces[env["nonce"]] = _ts(env["expires_at"])
        self._attempts[(incident, service, plan["action_id"])].append(started)
        result, detail, executed = "failed", "", argv
        try:
            executed, res = self.executor.restart(container)
            if res.returncode == 0:
                result, detail = "success", "container restarted"
            else:
                detail = f"docker restart exited with status {res.returncode}"
        except (ExecutorError, CommandError) as exc:
            detail = f"restart not completed: {exc}"
        if result == "failed":
            self._failed[incident] += 1
        execution = {"execution_id": exec_id, "plan_id": plan_id, "idempotency_key": key,
                     "started_at": fmt(started), "ended_at": fmt(self.clock()), "result": result,
                     "executed_argv": executed, "detail": detail[:500]}
        self._idem[key] = {"fp": fp, "execution": execution}
        try:
            self.audit.append("actuator", "execution.finished", {
                "execution": execution, "idempotency_key": key, "fingerprint": fp, "incident_id": incident}, incident)
        except AuditError:
            self._degraded = "audit write failed after an execution; refusing further actions"
            execution["detail"] = (execution["detail"] + "; audit write of the result failed")[:500]
        return execution
