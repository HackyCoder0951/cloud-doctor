"""Test helper: wires the whole read-write loop over a fixture scenario in virtual time."""
import os
import stat
from dataclasses import dataclass

from backend.audit import AuditWriter
from backend.detector.config import DetectorConfig
from backend.detector.engine import Detector
from backend.detector.expected import ExpectedStateRegistry
from backend.domain.clock import FakeClock
from backend.evidence import EvidenceCollector
from backend.incidents.manager import IncidentManager
from backend.rca.engine import RcaEngine
from backend.remediation.actuator import InProcessFakeActuator
from backend.remediation.engine import EngineConfig, RemediationEngine
from backend.remediation.planner import Planner
from backend.repositories import MemoryRepository
from backend.verifier import Verifier, VerifierConfig

KEY = b"unit-test-signing-key-0123456789"


@dataclass
class Stack:
    world: object
    repo: object
    clock: object
    audit: object
    mgr: object
    det: object
    col: object
    rca: object
    ver: object
    act: object
    eng: object

    def poll_until(self, t_end, start=5):
        t = start
        while t <= t_end:
            self.clock.set(self.world.scenario.at(t))
            self.mgr.ingest(self.det.poll(self.clock.now()))
            t += self.world.scenario.step

    def incident(self):
        return sorted(self.repo.list_incidents(), key=lambda i: i.opened_at)[0]


def build(world, catalog, cfg, name_or_data, tmp_path=None, engine_cfg=None, vcfg=None, key=KEY, actuator=None, key_loader=None):
    w = world(name_or_data)
    repo, clock = MemoryRepository(), FakeClock(w.scenario.at(5))
    audit = AuditWriter(repo, clock)
    mgr = IncidentManager(repo, catalog, cfg, audit, clock)
    reg = ExpectedStateRegistry()
    det = Detector(w.prom, catalog, cfg, reg)
    col = EvidenceCollector(repo, catalog, cfg, w.prom, w.logs, w.feed, w.prober, reg, audit, clock, mgr.timeline)
    rca = RcaEngine(catalog, clock)
    ver = Verifier(repo, catalog, cfg, w.prom, w.prober, col, audit, clock, vcfg or VerifierConfig(settle_seconds=10, stability_window_seconds=30, sample_interval_seconds=5))
    act = actuator or InProcessFakeActuator(catalog, key, clock)
    loader = key_loader or (lambda: key)
    eng = RemediationEngine(repo, mgr, Planner(repo, catalog), col, rca, ver, act, audit, clock, engine_cfg, key_loader=loader)
    return Stack(w, repo, clock, audit, mgr, det, col, rca, ver, act, eng)


def key_file(tmp_path, content=KEY, mode=0o600):
    p = tmp_path / "signing.key"
    p.write_bytes(content)
    os.chmod(p, mode)
    return str(p)
