"""ActuatorClient protocol, an in-process fake (tests/demo) and the unix-socket HTTP client.

The real actuator (Stream C) is a separate process reached over the unix socket in CD_ACTUATOR_SOCKET, exactly as in
contracts/actuator.openapi.yaml. Any transport/response problem raises ActuatorUnavailable: callers fail closed.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from typing import Callable, Protocol

import httpx

from backend import policy_adapter as pa
from backend.domain.canonical import plan_hash
from backend.domain.catalog import Catalog
from backend.domain.clock import Clock, iso, parse_ts
from backend.domain.contracts import ContractViolation, validate_against_contract
from backend.domain.models import Execution


class ActuatorUnavailable(RuntimeError):
    pass


class ActuatorClient(Protocol):
    def validate(self, signed_plan: dict) -> dict: ...
    def execute(self, signed_plan: dict, idempotency_key: str) -> Execution: ...
    def health(self) -> dict: ...


class UnixSocketActuatorClient:
    """HTTP over a unix domain socket. Responses are validated against contracts/schemas/actuator.json."""

    def __init__(self, socket_path: str | None = None, timeout_s: float = 10.0, client: httpx.Client | None = None) -> None:
        path = socket_path or os.environ.get("CD_ACTUATOR_SOCKET")
        if not path and client is None:
            raise ActuatorUnavailable("CD_ACTUATOR_SOCKET is not set")
        self._c = client or httpx.Client(transport=httpx.HTTPTransport(uds=path), base_url="http://unix", timeout=timeout_s)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = self._c.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise ActuatorUnavailable(f"actuator unreachable: {type(exc).__name__}") from exc
        if r.status_code != 200:
            raise ActuatorUnavailable(f"actuator returned HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as exc:
            raise ActuatorUnavailable("actuator returned malformed JSON") from exc

    def validate(self, signed_plan: dict) -> dict:
        body = self._call("POST", "/v1/validate", {"signed_plan": signed_plan})
        try:
            validate_against_contract(body, "actuator", "#/$defs/validate_response")
        except ContractViolation as exc:
            raise ActuatorUnavailable("actuator validate response violates the contract") from exc
        return body

    def execute(self, signed_plan: dict, idempotency_key: str) -> Execution:
        body = self._call("POST", "/v1/execute", {"signed_plan": signed_plan, "idempotency_key": idempotency_key})
        try:
            validate_against_contract(body, "actuator", "#/$defs/execute_response")
        except ContractViolation as exc:
            raise ActuatorUnavailable("actuator execute response violates the contract") from exc
        return Execution.model_validate(body["execution"])

    def health(self) -> dict:
        return self._call("GET", "/healthz")


class InProcessFakeActuator:
    """Test/demo double that mimics the actuator contract: signature, expiry, nonce replay, plan_hash, Layer-1 re-check,
    idempotency on the key, fixed argv `docker restart <container>` through an injectable runner (no real Docker).
    """

    def __init__(self, catalog: Catalog, key: bytes, clock: Clock, runner: Callable[[list[str]], tuple[int, str]] | None = None,
                 on_execute: Callable[[dict], None] | None = None, available: bool = True) -> None:
        self.catalog, self.key, self.clock = catalog, key, clock
        self.runner = runner or (lambda argv: (0, "ok"))
        self.on_execute = on_execute
        self.available = available
        self.commands: list[list[str]] = []
        self._nonces: set[str] = set()
        self._by_key: dict[str, Execution] = {}
        self._attempts: dict[tuple, list[datetime]] = {}
        self._lock = threading.Lock()
        self._n = 0

    def _check(self, sp: dict, consume_nonce: bool) -> tuple[list[str], list[str]]:
        rules: list[str] = []
        reasons: list[str] = []
        try:
            validate_against_contract(sp, "signed_plan")
        except ContractViolation:
            return ["I-01"], ["signed plan does not match the schema"]
        if not pa.verify_envelope(sp, self.key):
            return ["I-08"], ["signature invalid"]
        now = self.clock.now()
        if not (parse_ts(sp["issued_at"]) - timedelta(seconds=5) <= now < parse_ts(sp["expires_at"])):
            return ["I-08"], ["signed plan expired or not yet valid"]
        if consume_nonce and sp["nonce"] in self._nonces:
            return ["I-08"], ["nonce replay"]
        plan = sp["plan"]
        if plan_hash(plan) != plan["plan_hash"]:
            return ["I-01"], ["plan_hash mismatch"]
        key = lambda inc, svc, act: (inc, svc, act)  # noqa: E731
        ctx = pa.make_context(
            catalog=self.catalog, now=now, attempts_used=lambda i, s, a: len(self._attempts.get(key(i, s, a), [])),
            last_attempt_at=lambda i, s, a: (self._attempts.get(key(i, s, a)) or [None])[-1], circuit_open=lambda i: False,
            known_evidence_ids=set(plan["evidence_refs"]), diagnosis_validated=True, top_cause_service=plan["params"].get("service"),
            approval=sp.get("approval"), container_labels=lambda c: {"cloud-doctor.sandbox": "true"})
        res = pa.evaluate(plan, ctx)
        if res.final == "deny":
            return res.rule_ids, res.reasons
        if res.final == "allow_with_approval":
            return ["I-03"], ["approval required"]
        return rules, reasons

    def validate(self, signed_plan: dict) -> dict:
        if not self.available:
            raise ActuatorUnavailable("actuator unavailable (fake)")
        rules, reasons = self._check(signed_plan, consume_nonce=False)
        return {"ok": not rules, "rule_ids": rules, "reasons": reasons, "invariants_version": pa.VERSION}

    def execute(self, signed_plan: dict, idempotency_key: str) -> Execution:
        if not self.available:
            raise ActuatorUnavailable("actuator unavailable (fake)")
        with self._lock:
            if idempotency_key in self._by_key:
                return self._by_key[idempotency_key]
            self._n += 1
            started = self.clock.now()
            eid = f"EX-{self._n:04d}"
            rules, reasons = self._check(signed_plan, consume_nonce=True)
            plan = signed_plan.get("plan", {})
            if rules:
                ex = Execution(execution_id=eid, plan_id=plan.get("plan_id", "PL-0000"), idempotency_key=idempotency_key, started_at=started,
                               ended_at=self.clock.now(), result="refused", refusal_rule_ids=rules, executed_argv=[], detail="; ".join(reasons)[:500])
            else:
                self._nonces.add(signed_plan["nonce"])
                svc = plan["params"]["service"]
                argv = ["docker", "restart", self.catalog.get(svc).container] if plan["action_id"] == "restart_service" else []
                code, out = (self.runner(argv) if argv else (0, "no executing action"))
                self.commands.append(argv)
                self._attempts.setdefault((plan["incident_id"], svc, plan["action_id"]), []).append(started)
                if code == 0 and self.on_execute:
                    self.on_execute(plan)
                ex = Execution(execution_id=eid, plan_id=plan["plan_id"], idempotency_key=idempotency_key, started_at=started,
                               ended_at=self.clock.now(), result="success" if code == 0 else "failed", refusal_rule_ids=[], executed_argv=argv,
                               detail=("restart issued" if code == 0 else f"command failed with exit code {code}"))
            self._by_key[idempotency_key] = ex
            return ex

    def health(self) -> dict:
        if not self.available:
            raise ActuatorUnavailable("actuator unavailable (fake)")
        return {"state": "ok", "invariants_version": pa.VERSION}
