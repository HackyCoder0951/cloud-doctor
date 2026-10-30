"""Service container + orchestrator: wires every component; used by the API app and the demo replay."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime

from backend.audit import AuditWriter
from backend.detector.config import DetectorConfig
from backend.detector.engine import Detector
from backend.detector.expected import ExpectedStateRegistry
from backend.domain.catalog import Catalog
from backend.domain.clock import Clock, SystemClock
from backend.evidence import EvidenceCollector
from backend.incidents.manager import IncidentManager
from backend.rca.engine import RcaEngine
from backend.remediation.actuator import ActuatorClient, UnixSocketActuatorClient
from backend.remediation.engine import EngineConfig, RemediationEngine
from backend.remediation.planner import Planner
from backend.remediation.signing import load_key
from backend.report import ReportGenerator
from backend.repositories import make_repository
from backend.repositories.base import Repository
from backend.telemetry.base import LogClient, PromClient
from backend.telemetry.http import HttpProber, LokiHttpClient, PromHttpClient
from backend.verifier import Verifier, VerifierConfig


class Tracked:
    """Wraps a telemetry client and remembers whether the last call worked (for GET /status)."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.last_ok: bool | None = None
        self.last_detail = ""

    def __getattr__(self, name):
        fn = getattr(self._inner, name)
        if not callable(fn):
            return fn

        def call(*a, **kw):
            res = fn(*a, **kw)
            st = getattr(res, "status", "ok")
            self.last_ok = st not in ("error", "timeout")
            self.last_detail = "" if self.last_ok else str(getattr(res, "error", st))[:80]
            return res

        return call


@dataclass
class Services:
    repo: Repository
    catalog: Catalog
    cfg: DetectorConfig
    clock: Clock
    audit: AuditWriter
    registry: ExpectedStateRegistry
    prom: Tracked
    logs: Tracked
    detector: Detector
    mgr: IncidentManager
    collector: EvidenceCollector
    rca: RcaEngine
    reports: ReportGenerator
    engine: RemediationEngine | None
    actuator: ActuatorClient | None
    llm_state: str = "disabled"


def build_services(repo: Repository, catalog: Catalog, cfg: DetectorConfig, clock: Clock, prom: PromClient, logs: LogClient, feed, prober,
                   actuator: ActuatorClient | None, key_loader=load_key, vcfg: VerifierConfig | None = None,
                   engine_cfg: EngineConfig | None = None) -> Services:
    repo.sync_catalog(catalog)
    audit = AuditWriter(repo, clock)
    reg = ExpectedStateRegistry()
    tprom, tlogs = Tracked(prom), Tracked(logs)
    det = Detector(tprom, catalog, cfg, reg)
    mgr = IncidentManager(repo, catalog, cfg, audit, clock)
    col = EvidenceCollector(repo, catalog, cfg, tprom, tlogs, feed, prober, reg, audit, clock, mgr.timeline)
    rca = RcaEngine(catalog, clock)
    engine = None
    if actuator is not None:
        ver = Verifier(repo, catalog, cfg, tprom, prober, col, audit, clock, vcfg)
        engine = RemediationEngine(repo, mgr, Planner(repo, catalog), col, rca, ver, actuator, audit, clock, engine_cfg, key_loader=key_loader)
    return Services(repo, catalog, cfg, clock, audit, reg, tprom, tlogs, det, mgr, col, rca, ReportGenerator(repo, clock), engine, actuator)


def services_from_env() -> Services:
    """Real wiring: PostgreSQL if CD_DATABASE_URL, Prometheus/Loki over HTTP, actuator over CD_ACTUATOR_SOCKET."""
    catalog = Catalog.load()
    cfg = DetectorConfig.load()
    actuator = UnixSocketActuatorClient() if os.environ.get("CD_ACTUATOR_SOCKET") else None
    urls = {s.name: s.probe_url for s in catalog.services.values() if s.probe_url}
    return build_services(make_repository(), catalog, cfg, SystemClock(), PromHttpClient(), LokiHttpClient(), _NoFeed(), HttpProber(urls), actuator)


class _NoFeed:
    """No change feed is wired in the real deployment yet (known gap): reports an explicit collection failure."""

    def events(self, start: datetime, end: datetime):
        from backend.telemetry.base import ERROR, ChangeResult

        return ChangeResult(ERROR, [], "no change feed configured")


class Orchestrator:
    """One tick = poll the detector, ingest alerts, diagnose newly opened incidents, advance remediation."""

    def __init__(self, svc: Services, remediate: bool = False) -> None:
        self.svc, self.remediate = svc, remediate
        self._diag: dict[str, tuple[set[str], datetime]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    DIAGNOSE_AFTER_S = 10  # let the first symptoms build evidence before the first diagnosis
    REDIAGNOSE_MIN_GAP_S = 10

    def step(self) -> list[str]:
        s = self.svc
        with self._lock:
            now = s.clock.now()
            res = s.detector.poll(now)
            touched = s.mgr.ingest(res)
            s.mgr.sweep(now)
            for inc in s.repo.list_incidents(limit=200):
                if inc.state not in ("detected", "investigating", "diagnosed"):
                    continue
                last = self._diag.get(inc.incident_id)
                age = (now - inc.opened_at).total_seconds()
                if last is None and age < self.DIAGNOSE_AFTER_S:
                    continue
                if last is not None and (set(inc.services) == last[0] or (now - last[1]).total_seconds() < self.REDIAGNOSE_MIN_GAP_S):
                    continue
                self._diag[inc.incident_id] = (set(inc.services), now)
                if s.engine:
                    s.engine.diagnose(inc.incident_id)
                    if self.remediate and inc.state != "closed":
                        s.engine.run(inc.incident_id)
                else:
                    self._diagnose_only(inc.incident_id)
            if s.engine and self.remediate:
                s.engine.tick()
            return touched

    def _diagnose_only(self, iid: str) -> None:
        s = self.svc
        inc = s.repo.get_incident(iid)
        if inc.state == "detected":
            s.mgr.transition(iid, "investigating", "rca", "collecting evidence")
        s.collector.collect(iid, s.clock.now())
        inc = s.repo.get_incident(iid)
        d = s.rca.diagnose(iid, s.repo.list_evidence(iid), inc.services)
        s.repo.save_diagnosis(d)
        top = d.hypotheses[0]
        s.audit.write("rca", "diagnosis.created", {"top": top.cause_id, "confidence": top.confidence}, iid)
        s.mgr.timeline.add(iid, d.generated_at, "diagnosis", f"diagnosis: top cause {top.cause_id} (confidence {top.confidence:.2f}, {top.status})", top.service)
        if s.repo.get_incident(iid).state == "investigating":
            s.mgr.transition(iid, "diagnosed", "rca", f"top cause {top.cause_id}")

    def run_forever(self) -> None:  # pragma: no cover - thread body
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:
                import logging

                logging.getLogger("cloud_doctor").exception("orchestrator step failed")
            self._stop.wait(self.svc.cfg.poll_interval_seconds)

    def stop(self) -> None:
        self._stop.set()
