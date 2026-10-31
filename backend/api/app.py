"""FastAPI application implementing contracts/openapi.yaml (served under /api/v1).

Security rules: cookie session (HttpOnly, Secure, SameSite=Lax) from the shared MVP token read from the file named by
CD_SESSION_TOKEN_FILE; every mutating route requires an Idempotency-Key; approve/reject are bound to plan_hash; planning and
execution are system-initiated (a human can only approve or reject an existing plan); error bodies never leak internals;
log/evidence text is returned as data only (the dashboard renders it as escaped text).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import policy_adapter as pa
from backend.domain.clock import iso
from backend.remediation.actuator import ActuatorUnavailable
from backend.remediation.engine import NotFound, RemediationConflict, RemediationDenied
from backend.report import NoDiagnosis
from backend.services import Orchestrator, Services

log = logging.getLogger("cloud_doctor.api")
COOKIE = "cd_session"
STREAM_TYPES = {"service.health", "incident.opened", "incident.updated", "timeline.event", "plan.created", "decision.recorded",
                "execution.finished", "verification.finished", "status.changed"}
INC_RE = re.compile(r"^INC-[0-9]{4,}$")
PLAN_RE = re.compile(r"^PL-[0-9]{4,}$")
SVC_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
IDEM_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
METRICS = {"error_ratio": "error_ratio", "latency_p95_seconds": "latency_p95", "throughput_rps": "request_rate", "queue_depth": "queue_depth", "up": "up"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, rule_ids: list[str] | None = None) -> None:
        self.status, self.code, self.message, self.rule_ids = status, code, message, rule_ids


def _err(status: int, code: str, message: str, rule_ids: list[str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if rule_ids:
        body["rule_ids"] = rule_ids
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Annotated[str, StringConstraints(min_length=8, max_length=256)]


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_hash: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
    reason: Annotated[str, StringConstraints(min_length=3, max_length=300)]


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, StringConstraints(min_length=3, max_length=300)]


class EventBus:
    """Ring buffer of StreamEvents with monotonically increasing ids (Last-Event-ID reconnect)."""

    def __init__(self, size: int = 1000) -> None:
        self._lock = threading.Lock()
        self._buf: deque[tuple[int, dict]] = deque(maxlen=size)
        self._n = 0

    def publish(self, typ: str, incident_id: str | None = None, service: str | None = None, data: dict | None = None, at: datetime | None = None) -> None:
        if typ not in STREAM_TYPES:
            return
        ev: dict[str, Any] = {"type": typ, "at": iso(at or datetime.now(UTC))}
        if incident_id:
            ev["incident_id"] = incident_id
        if service:
            ev["service"] = service
        if data:
            ev["data"] = data
        with self._lock:
            self._n += 1
            self._buf.append((self._n, ev))

    def since(self, last_id: int) -> list[tuple[int, dict]]:
        with self._lock:
            return [(i, e) for i, e in self._buf if i > last_id]


class Settings(BaseModel):
    session_ttl_seconds: int = 8 * 3600
    login_max_failures: int = 5
    login_window_seconds: int = 60
    sse_max_idle_seconds: float | None = None  # None = stream forever; tests set a small value
    cookie_secure: bool = True


def create_app(svc: Services, settings: Settings | None = None, start_background: bool = False, remediate: bool = False) -> FastAPI:
    st = settings or Settings()
    bus = EventBus()
    sessions: dict[str, float] = {}
    fails: deque[float] = deque()
    idem: dict[tuple[str, str, str], tuple[str, int, Any]] = {}
    lock = threading.Lock()
    orch = Orchestrator(svc, remediate=remediate)

    def on_event(typ: str, incident_id: str | None, data: dict) -> None:
        service = data.get("service") if isinstance(data.get("service"), str) else None
        bus.publish(typ, incident_id, service, {k: v for k, v in data.items() if k != "service" and isinstance(v, (str, int, float, bool))} or None)

    svc.mgr.listeners.append(on_event)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_background:
            threading.Thread(target=orch.run_forever, daemon=True, name="orchestrator").start()
        yield
        orch.stop()

    app = FastAPI(title="Cloud Doctor API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc, app.state.bus, app.state.orchestrator = svc, bus, orch

    # ------------------------------------------------------------------ errors: never leak internals
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _err(exc.status, exc.code, exc.message, exc.rule_ids)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: ("not_found", "resource not found"), 405: ("method_not_allowed", "method not allowed"), 401: ("unauthorized", "authentication required")}
        code, msg = codes.get(exc.status_code, ("error", "request failed"))
        return _err(exc.status_code, code, msg)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return _err(422, "invalid_request", "request validation failed")  # no field values or schema echoed back

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return _err(500, "internal_error", "internal error")

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    # ------------------------------------------------------------------ auth + idempotency dependencies
    def require_session(request: Request) -> None:
        tok = request.cookies.get(COOKIE)
        exp = sessions.get(tok or "")
        if not tok or exp is None or exp < time.time():
            sessions.pop(tok or "", None)
            raise ApiError(401, "unauthorized", "authentication required")

    def idem_key(idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
        if not idempotency_key or not IDEM_RE.match(idempotency_key):
            raise ApiError(400, "idempotency_key_required", "a valid Idempotency-Key header is required")
        return idempotency_key

    auth = [Depends(require_session)]

    def replay(request: Request, key: str, body: Any, produce) -> Any:
        """Execute ``produce`` once per (key, route, body); identical replays return the stored result, different bodies conflict."""
        ident = (key, request.method, request.url.path)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        with lock:
            if ident in idem:
                d, status, payload = idem[ident]
                if d != digest:
                    raise ApiError(409, "idempotency_key_reused", "this Idempotency-Key was used with a different request")
                return JSONResponse(payload, status_code=status)
        resp = produce()
        status, payload = resp
        with lock:
            idem[ident] = (digest, status, payload)
        return JSONResponse(payload, status_code=status)

    def incident_or_404(iid: str):
        if not INC_RE.match(iid):
            raise ApiError(404, "not_found", "incident not found")
        inc = svc.repo.get_incident(iid)
        if inc is None:
            raise ApiError(404, "not_found", "incident not found")
        return inc

    def service_or_404(name: str) -> str:
        if name not in svc.catalog.services:
            raise ApiError(404, "not_found", "service not found")
        return name

    # ------------------------------------------------------------------ auth routes
    r = "/api/v1"

    @app.post(f"{r}/auth/login", status_code=204)
    def login(body: LoginBody, request: Request):
        now = time.time()
        while fails and fails[0] < now - st.login_window_seconds:
            fails.popleft()
        if len(fails) >= st.login_max_failures:
            raise ApiError(429, "too_many_attempts", "too many failed attempts, try later")
        path = os.environ.get("CD_SESSION_TOKEN_FILE")
        try:
            secret = open(path, "rb").read().strip() if path else b""
        except OSError:
            secret = b""
        if len(secret) < 8:
            raise ApiError(503, "login_unavailable", "login is not configured (fail closed)")
        if not hmac.compare_digest(body.token.encode(), secret):
            fails.append(now)
            svc.audit.write("api", "login.failed", {})
            raise ApiError(401, "unauthorized", "invalid credentials")
        tok = secrets.token_urlsafe(32)
        sessions[tok] = now + st.session_ttl_seconds
        svc.audit.write("api", "login.ok", {})
        out = Response(status_code=204)
        out.set_cookie(COOKIE, tok, max_age=st.session_ttl_seconds, httponly=True, secure=True, samesite="lax", path="/api")
        return out

    @app.post(f"{r}/auth/logout", status_code=204)
    def logout(request: Request):
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        out = Response(status_code=204)
        out.delete_cookie(COOKIE, path="/api", httponly=True, secure=True, samesite="lax")
        return out

    # ------------------------------------------------------------------ services
    def health_of(name: str) -> dict:
        s = svc.detector.statuses[name]
        deps = [{"service": d, "state": svc.detector.statuses[d].state} for d in svc.catalog.dependencies(name)]
        open_ids = [i.incident_id for i in svc.repo.list_incidents(limit=200) if name in i.services and i.state not in ("recovered", "closed")]
        out = {"name": name, "kind": s.kind, "state": s.state, "missing_signal_state": s.missing_signal_state,
               "updated_at": iso(s.updated_at or datetime.now(UTC)), "open_incident_ids": open_ids, "dependencies": deps}
        slis = {k: v for k, v in s.slis.items() if k in ("availability", "error_ratio", "latency_p95_seconds", "throughput_rps", "queue_depth")}
        if slis:
            out["slis"] = slis
        return out

    @app.get(f"{r}/services", dependencies=auth)
    def list_services():
        return [health_of(n) for n in svc.catalog.names()]

    @app.get(f"{r}/services/{{service}}/health", dependencies=auth)
    def service_health(service: str):
        return health_of(service_or_404(service))

    @app.get(f"{r}/services/{{service}}/metrics", dependencies=auth)
    def service_metric(service: str, name: Annotated[str, Query()], since_seconds: Annotated[int, Query(ge=30, le=3600)] = 600):
        service_or_404(service)
        if name not in METRICS:
            raise ApiError(422, "invalid_request", "unknown metric name")
        now = svc.clock.now()
        step = max(5, since_seconds // 120)
        res = svc.prom.query_range(svc.cfg.query(METRICS[name], service), now - timedelta(seconds=since_seconds), now, step)
        pts = [{"t": iso(t), "v": v} for s in res.series for t, v in s.points][:2000]
        return {"service": service, "name": name, "status": res.status, "points": pts}

    @app.get(f"{r}/services/{{service}}/logs", dependencies=auth)
    def service_logs(service: str, since_seconds: Annotated[int, Query(ge=30, le=3600)] = 300, limit: Annotated[int, Query(ge=1, le=500)] = 100):
        service_or_404(service)
        now = svc.clock.now()
        res = svc.logs.query_range(f'{{service="{service}"}}', now - timedelta(seconds=since_seconds), now, limit)
        lines = [{"t": iso(l.t), "line": l.line.replace("\x00", "")[:2000], "level": l.level} for l in res.lines[:limit]]  # UNTRUSTED text
        return {"service": service, "status": res.status, "lines": lines}

    @app.get(f"{r}/topology", dependencies=auth)
    def topology():
        return {"nodes": [{"name": n, "kind": svc.catalog.kind(n), "state": svc.detector.statuses[n].state} for n in svc.catalog.names()],
                "edges": [{"from": a, "to": b, "kind": k} for a, b, k in svc.catalog.edges()]}

    # ------------------------------------------------------------------ incidents
    @app.get(f"{r}/incidents", dependencies=auth)
    def list_incidents(state: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50):
        if state and state not in ("detected", "investigating", "diagnosed", "remediating", "verifying", "recovered", "escalated", "closed"):
            raise ApiError(422, "invalid_request", "unknown state")
        return [i.to_contract() for i in svc.repo.list_incidents(state, limit)]

    @app.get(f"{r}/incidents/{{incident}}", dependencies=auth)
    def get_incident(incident: str):
        return incident_or_404(incident).to_contract()

    @app.get(f"{r}/incidents/{{incident}}/timeline", dependencies=auth)
    def get_timeline(incident: str):
        incident_or_404(incident)
        return [e.to_contract() for e in svc.repo.list_events(incident)]

    @app.get(f"{r}/incidents/{{incident}}/evidence", dependencies=auth)
    def get_evidence(incident: str):
        incident_or_404(incident)
        return [e.to_contract() for e in svc.repo.list_evidence(incident)]

    @app.get(f"{r}/incidents/{{incident}}/diagnosis", dependencies=auth)
    def get_diagnosis(incident: str):
        incident_or_404(incident)
        d = svc.repo.latest_diagnosis(incident)
        if d is None:
            raise ApiError(404, "not_found", "no diagnosis yet")
        return d.to_contract()

    @app.post(f"{r}/incidents/{{incident}}/diagnose", status_code=202, dependencies=auth)
    def rediagnose(incident: str, request: Request, background: BackgroundTasks, key: str = Depends(idem_key)):
        incident_or_404(incident)

        def produce():
            def work():
                try:
                    if svc.engine:
                        svc.engine.diagnose(incident)
                    else:
                        orch._diagnose_only(incident)
                except Exception:
                    log.exception("rediagnose failed")

            background.add_task(work)
            svc.audit.write("api", "diagnose.requested", {}, incident)
            return 202, {"status": "accepted"}

        return replay(request, key, {"incident": incident}, produce)

    @app.get(f"{r}/incidents/{{incident}}/remediation", dependencies=auth)
    def get_remediation(incident: str):
        incident_or_404(incident)
        if svc.engine:
            return svc.engine.view(incident)
        return {"plans": [], "decisions": [], "executions": []}

    def need_engine():
        if svc.engine is None:
            raise ApiError(503, "remediation_unavailable", "remediation is not available (no actuator configured): failing closed")
        return svc.engine

    @app.post(f"{r}/incidents/{{incident}}/remediation/plans/{{plan}}/approve", dependencies=auth)
    def approve_plan(incident: str, plan: str, body: ApproveBody, request: Request, background: BackgroundTasks, key: str = Depends(idem_key)):
        incident_or_404(incident)
        if not PLAN_RE.match(plan):
            raise ApiError(404, "not_found", "plan not found")
        eng = need_engine()

        def produce():
            try:
                dec = eng.approve(incident, plan, body.plan_hash, "operator", body.reason)
            except NotFound:
                raise ApiError(404, "not_found", "plan not found")
            except RemediationConflict:
                raise ApiError(409, "conflict", "the plan is not awaiting approval, or plan_hash does not match")
            except RemediationDenied as exc:
                raise ApiError(403, "policy_denied", "policy refused the approval", exc.rule_ids)
            background.add_task(lambda: eng.run(incident))  # queued: execution happens after the response
            return 200, dec.to_contract()

        return replay(request, key, {"incident": incident, "plan": plan, **body.model_dump()}, produce)

    @app.post(f"{r}/incidents/{{incident}}/remediation/plans/{{plan}}/reject", dependencies=auth)
    def reject_plan(incident: str, plan: str, body: RejectBody, request: Request, key: str = Depends(idem_key)):
        incident_or_404(incident)
        if not PLAN_RE.match(plan):
            raise ApiError(404, "not_found", "plan not found")
        eng = need_engine()

        def produce():
            try:
                eng.reject(incident, plan, "operator", body.reason)
            except NotFound:
                raise ApiError(404, "not_found", "plan not found")
            except RemediationConflict:
                raise ApiError(409, "conflict", "the plan is not awaiting approval")
            return 200, {"status": "rejected"}

        return replay(request, key, {"incident": incident, "plan": plan, **body.model_dump()}, produce)

    @app.get(f"{r}/incidents/{{incident}}/verification", dependencies=auth)
    def get_verification(incident: str):
        incident_or_404(incident)
        return [v.to_contract() for v in svc.repo.list_verifications(incident)]

    @app.get(f"{r}/incidents/{{incident}}/report", dependencies=auth)
    def get_report(incident: str, request: Request):
        incident_or_404(incident)
        try:
            rep = svc.reports.build(incident)
        except NoDiagnosis:
            raise ApiError(404, "not_found", "no diagnosis yet, so no report")
        if "text/markdown" in request.headers.get("accept", "") and "application/json" not in request.headers.get("accept", "").split(",")[0]:
            return PlainTextResponse(svc.reports.render_markdown(rep), media_type="text/markdown")
        return rep

    # ------------------------------------------------------------------ audit
    @app.get(f"{r}/audit", dependencies=auth)
    def list_audit(incident: Annotated[str | None, Query(pattern=r"^INC-[0-9]{4,}$")] = None, after_seq: Annotated[int, Query(ge=0)] = 0,
                   limit: Annotated[int, Query(ge=1, le=500)] = 100):
        return {"chain_valid": svc.audit.chain_valid(), "events": [e.to_contract() for e in svc.repo.list_audit(incident, after_seq, limit)]}

    # ------------------------------------------------------------------ SSE
    @app.get(f"{r}/stream", response_class=EventSourceResponse, dependencies=auth)
    async def stream(request: Request, last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None):
        try:
            cursor = int(last_event_id) if last_event_id else 0
        except ValueError:
            cursor = 0
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return
            batch = bus.since(cursor)
            for i, ev in batch:
                cursor = i
                idle = 0.0
                yield ServerSentEvent(data=ev, id=str(i))
            if st.sse_max_idle_seconds is not None and idle >= st.sse_max_idle_seconds:
                return
            await asyncio.sleep(0.05 if st.sse_max_idle_seconds is not None else 0.5)
            idle += 0.05 if st.sse_max_idle_seconds is not None else 0.5

    # ------------------------------------------------------------------ status (no auth)
    @app.get(f"{r}/status")
    def status():
        deps: list[dict] = []

        def dep(name: str, state: str, detail: str = "") -> None:
            deps.append({"name": name, "state": state, **({"detail": detail} if detail else {})})

        dep("prometheus", "unknown" if svc.prom.last_ok is None else "up" if svc.prom.last_ok else "down", svc.prom.last_detail)
        dep("logs", "unknown" if svc.logs.last_ok is None else "up" if svc.logs.last_ok else "down", svc.logs.last_detail)
        try:
            svc.repo.last_audit()
            dep("database", "up" if os.environ.get("CD_DATABASE_URL") else "disabled", "" if os.environ.get("CD_DATABASE_URL") else "in-memory repositories")
        except Exception:
            dep("database", "down")
        if svc.actuator is None:
            dep("actuator", "disabled", "no actuator configured: recommendation only")
        else:
            try:
                svc.actuator.health()
                dep("actuator", "up")
            except ActuatorUnavailable:
                dep("actuator", "down")
        dep("policy_layer2", "disabled", f"Layer-2-less mode; Layer 1 = {pa.VERSION}" + ("" if pa.IS_REAL else " (LOCAL STUB)"))
        dep("llm", "disabled" if svc.llm_state == "disabled" else svc.llm_state, "C0: deterministic only")
        states = {d["name"]: d["state"] for d in deps}
        if states["database"] == "down" or states["actuator"] == "down":
            state = "fail_closed"  # cannot act safely: no remediation, detection and read APIs continue
        elif states["prometheus"] in ("down", "unknown") or states["logs"] == "down":
            state = "degraded"
        else:
            state = "ok"
        return {"state": state, "dependencies": deps}

    return app
