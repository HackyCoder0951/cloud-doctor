"""A fake Cloud Doctor API that simulates one scenario, driven by a fake clock and a FakeInjector.

It is a test double for the PUBLIC API only. It never sees scenario ground truth; the profile is written by the
test. Shapes follow contracts/schemas/*.json.
"""
from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from harness.clock import iso
from harness.injector import FakeInjector


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        from datetime import UTC
        self._t = start or datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._t += timedelta(seconds=seconds)


@dataclass
class Profile:
    breach_services: tuple[str, ...] = ("redis", "api", "worker")
    sli: str = "error_ratio"  # which SLI breaches on api: error_ratio | latency | queue (worker)
    detects: bool = True
    impact_delay: float = 6
    detect_delay: float = 10
    diagnose_delay: float = 8
    plan_delay: float = 4
    action_delay: float = 3
    verify_delay: float = 20
    cause_ids: tuple[str, ...] = ("redis_unavailable", "api_bug")
    action: tuple[str, str] | None = ("restart_service", "redis")  # None: escalate only
    risk: str = "low"
    needs_approval: bool = False
    max_attempts: int = 2
    cooldown: float = 20
    unauthorized: bool = False  # execute although the policy decision is deny
    extra_unhealthy: tuple[str, ...] = ()
    false_positive_at: float | None = None  # open an unrelated incident this many seconds after start (control runs)


SERVICES = {"loadgen": "load_generator", "api": "app", "worker": "queue_worker", "redis": "cache", "app-db": "database"}


class FakeCloudDoctor:
    def __init__(self, clock: FakeClock, injector: FakeInjector, profile: Profile) -> None:
        self.clock, self.injector, self.p = clock, injector, profile
        self.t0 = clock.now()
        self.calls: list[tuple[str, tuple]] = []
        self.incident: dict | None = None
        self.t_fault: datetime | None = None
        self.stage = "none"
        self.next_at: datetime | None = None
        self.attempts = 0
        self.plans: list[dict] = []
        self.decisions: list[dict] = []
        self.executions: list[dict] = []
        self.verifications: list[dict] = []
        self.timeline: list[dict] = []
        self.diagnosis: dict | None = None
        self.approved: set[str] = set()
        self.fp_done = False
        self.fail_calls = False

    # ------------------------------------------------------------------ simulation
    def _breach(self) -> bool:
        return self.t_fault is not None and (self.clock.now() - self.t_fault).total_seconds() >= self.p.impact_delay

    def _advance(self) -> None:
        now, p = self.clock.now(), self.p
        effective = self.injector.fault_effective()
        if effective and self.t_fault is None:
            self.t_fault = now
        if not effective:
            self.t_fault = None
        if p.false_positive_at is not None and not self.fp_done and (now - self.t0).total_seconds() >= p.false_positive_at:
            self.fp_done = True
            self._open(now, ["api"], "synthetic false positive")
            self.stage = "closed_fp"
            self.incident["state"] = "closed"
        if self.incident is None and self._breach() and p.detects and self.t_fault is not None:
            if (now - self.t_fault).total_seconds() >= p.impact_delay + p.detect_delay:
                self._open(self.t_fault + timedelta(seconds=p.impact_delay + p.detect_delay), list(p.breach_services), "SLI breach")
                self.stage, self.next_at = "opened", self.incident_opened + timedelta(seconds=p.diagnose_delay)
        while self.next_at is not None and now >= self.next_at and self.incident is not None:
            self._step(self.next_at)

    def _open(self, at: datetime, services: list[str], symptom: str) -> None:
        self.incident_opened = at
        self.incident = {"incident_id": "INC-0001", "state": "detected", "opened_at": iso(at), "severity": "high",
                         "services": services, "symptoms": [symptom]}

    def _event(self, at: datetime, kind: str, summary: str) -> None:
        n = len(self.timeline) + 1
        self.timeline.append({"event_id": f"TL-{n:04d}", "incident_id": "INC-0001", "event_time": iso(at),
                              "collected_at": iso(at), "kind": kind, "summary": summary})

    def _step(self, at: datetime) -> None:
        p, inc = self.p, self.incident
        if self.stage == "opened":
            inc["state"] = "diagnosed"
            self.diagnosis = {"incident_id": "INC-0001", "generated_at": iso(at), "origin": "rule", "hypotheses": [
                {"rank": i + 1, "cause_id": c, "description": c, "confidence": 0.5, "status": "candidate",
                 "claims": [{"text": "claim", "type": "observation", "evidence": ["EV-001"]}],
                 "contradicting": [], "alternatives": [], "unknowns": []} for i, c in enumerate(p.cause_ids)]}
            self._event(at, "diagnosis", "diagnosis ranked")
            self.stage, self.next_at = "diagnosed", at + timedelta(seconds=p.plan_delay)
        elif self.stage == "diagnosed":
            if p.action is None:
                inc["state"], inc["outcome"], self.stage, self.next_at = "escalated", "escalated", "done", None
                return
            self._plan(at)
        elif self.stage == "planned":
            if p.needs_approval and self.plans[-1]["plan_id"] not in self.approved:
                self.next_at = None  # wait for approve_plan
                return
            self._execute(at)
        elif self.stage == "executed":
            ok = not self.injector.fault_effective()
            plan = self.plans[-1]
            self.verifications.append({"incident_id": "INC-0001", "execution_id": self.executions[-1]["execution_id"],
                                       "verdict": "recovered" if ok else "failed", "window_start": self.executions[-1]["started_at"],
                                       "window_end": iso(at), "checks": [{"name": "readiness", "passed": ok}]})
            if ok:
                inc["state"], inc["outcome"], inc["closed_at"], self.stage, self.next_at = "recovered", "mitigated", iso(at), "done", None
            elif self.attempts >= p.max_attempts:
                inc["state"], inc["outcome"], self.stage, self.next_at = "escalated", "escalated", "done", None
            else:
                inc["state"] = "diagnosed"
                self.stage, self.next_at = "diagnosed", at + timedelta(seconds=p.cooldown)

    def _plan(self, at: datetime) -> None:
        p = self.p
        n = len(self.plans) + 1
        action, service = p.action
        plan = {"plan_id": f"PL-{n:04d}", "incident_id": "INC-0001", "action_id": action, "params": {"service": service},
                "risk_class": p.risk, "origin": "rule", "evidence_refs": ["EV-001"], "rationale": "r", "created_at": iso(at),
                "plan_hash": "sha256:" + f"{n:064x}"}
        final = "deny" if p.unauthorized else ("allow_with_approval" if p.needs_approval else "allow")
        self.plans.append(plan)
        self.decisions.append({"decision_id": f"DEC-{n:04d}", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
                               "l1": {"result": "deny" if p.unauthorized else "pass", "rule_ids": []}, "final": final,
                               "reasons": [], "invariants_version": "inv-0.1", "decided_at": iso(at)})
        self.incident["state"] = "remediating"
        self.stage, self.next_at = "planned", at + timedelta(seconds=p.action_delay)

    def _execute(self, at: datetime) -> None:
        self.attempts += 1
        n = len(self.executions) + 1
        action, service = self.p.action
        self.injector.external_action(action, service)
        self.executions.append({"execution_id": f"EX-{n:04d}", "plan_id": self.plans[-1]["plan_id"],
                                "idempotency_key": f"key-{n:08d}", "started_at": iso(at), "ended_at": iso(at),
                                "result": "success", "executed_argv": ["docker", "restart", "cd-" + service]})
        self.incident["state"] = "verifying"
        self.stage, self.next_at = "executed", at + timedelta(seconds=self.p.verify_delay)

    # ------------------------------------------------------------------ API surface
    def _enter(self, name: str, *args) -> None:
        self.calls.append((name, args))
        if self.fail_calls:
            from harness.api_client import ApiError
            raise ApiError(name, 503, "down")
        self._advance()

    def list_services(self) -> list[dict]:
        self._enter("list_services")
        breach = self._breach()
        out = []
        open_ids = ["INC-0001"] if self.incident and self.incident["state"] not in ("recovered", "escalated", "closed") else []
        for name, kind in SERVICES.items():
            bad = breach and (name in self.p.breach_services or name in self.p.extra_unhealthy)
            s = {"name": name, "kind": kind, "state": "UNHEALTHY" if bad else "HEALTHY", "missing_signal_state": "none",
                 "updated_at": iso(self.clock.now()), "open_incident_ids": open_ids if name in self.p.breach_services else []}
            if name == "api":
                s["slis"] = {"error_ratio": 0.0, "latency_p95_seconds": 0.2, "throughput_rps": 10.0}
                if breach and self.p.sli == "error_ratio":
                    s["slis"]["error_ratio"] = 0.9
                if breach and self.p.sli == "latency":
                    s["slis"]["latency_p95_seconds"] = 2.0
            if name == "worker":
                s["slis"] = {"queue_depth": 500.0 if breach and self.p.sli == "queue" else 3.0}
            out.append(s)
        return out

    def list_incidents(self, limit: int = 200) -> list[dict]:
        self._enter("list_incidents", limit)
        return [dict(self.incident)] if self.incident else []

    def get_incident(self, iid: str) -> dict:
        self._enter("get_incident", iid)
        return dict(self.incident)

    def get_timeline(self, iid: str) -> list[dict]:
        self._enter("get_timeline", iid)
        return list(self.timeline)

    def get_evidence(self, iid: str) -> list[dict]:
        self._enter("get_evidence", iid)
        return [{"evidence_id": "EV-001"}]

    def get_diagnosis(self, iid: str):
        self._enter("get_diagnosis", iid)
        return self.diagnosis

    def get_remediation(self, iid: str) -> dict:
        self._enter("get_remediation", iid)
        return {"plans": list(self.plans), "decisions": list(self.decisions), "executions": list(self.executions)}

    def get_verification(self, iid: str) -> list[dict]:
        self._enter("get_verification", iid)
        return list(self.verifications)

    def get_report(self, iid: str):
        self._enter("get_report", iid)
        return None

    def list_audit(self, incident_id=None, after_seq: int = 0, limit: int = 500) -> dict:
        self._enter("list_audit", incident_id, after_seq)
        return {"chain_valid": True, "events": []}

    def approve_plan(self, iid: str, plan_id: str, plan_hash: str, reason: str) -> dict:
        self._enter("approve_plan", iid, plan_id, plan_hash, reason)
        self.approved.add(plan_id)
        if self.stage == "planned":
            self.next_at = self.clock.now()
        return {"decision_id": "DEC-9999", "final": "allow"}


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._b = body

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Routes urllib requests to a FakeCloudDoctor and records every request exactly as sent."""

    def __init__(self, fake: FakeCloudDoctor) -> None:
        self.fake, self.requests = fake, []

    def open(self, req, timeout=None):
        url = urlsplit(req.full_url)
        body = req.data.decode() if req.data else None
        self.requests.append({"method": req.get_method(), "url": req.full_url, "body": body,
                              "headers": dict(req.header_items())})
        path, q, f = url.path, parse_qs(url.query), self.fake
        parts = path.removeprefix("/api/v1").strip("/").split("/")
        try:
            if parts == ["auth", "login"]:
                return _Resp(b"")
            if parts == ["services"]:
                data = f.list_services()
            elif parts == ["incidents"]:
                data = f.list_incidents(int(q.get("limit", ["50"])[0]))
            elif parts == ["audit"]:
                data = f.list_audit(q.get("incident", [None])[0], int(q.get("after_seq", ["0"])[0]))
            elif parts[0] == "incidents" and len(parts) == 2:
                data = f.get_incident(parts[1])
            elif parts[0] == "incidents" and parts[2] == "diagnosis":
                data = f.get_diagnosis(parts[1])
            elif parts[0] == "incidents" and parts[2] == "report":
                data = f.get_report(parts[1])
            elif parts[0] == "incidents" and parts[2] in ("timeline", "evidence", "remediation", "verification"):
                data = getattr(f, "get_" + parts[2])(parts[1])
            elif parts[0] == "incidents" and parts[-1] == "approve":
                payload = json.loads(body)
                data = f.approve_plan(parts[1], parts[4], payload["plan_hash"], payload["reason"])
            else:
                data = None
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ == "ApiError":
                raise urllib.error.HTTPError(req.full_url, e.status or 500, "err", {}, None) from None
            raise
        if data is None:
            raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)
        return _Resp(json.dumps(data).encode())
