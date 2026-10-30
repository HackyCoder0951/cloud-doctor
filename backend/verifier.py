"""Recovery verifier: seven checks over a stability window; fail closed.

Recovered(t_end) = readiness AND dependencies AND error SLI AND latency SLI AND synthetic transaction AND no regression
AND telemetry fresh (docs/08-recovery/recovery-verification.md). A check that cannot be established is passed=null and
forces verdict 'unverifiable' (not recovered). Pre-action values come from the pre-action evidence snapshot, post-action
from the window, baseline from the history before the first symptom.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.audit import AuditWriter
from backend.detector.config import DetectorConfig
from backend.domain.catalog import Catalog
from backend.domain.clock import Clock, iso
from backend.domain.models import Check, Verification
from backend.evidence import EvidenceCollector
from backend.rca.facts import Facts
from backend.repositories.base import Repository
from backend.telemetry.base import Prober, PromClient


@dataclass
class VerifierConfig:
    settle_seconds: float = 10
    stability_window_seconds: float = 45
    sample_interval_seconds: float = 5
    error_ratio_max: float = 0.05
    latency_default_max: float = 0.5
    baseline_lookback_seconds: float = 120


@dataclass
class _Samples:
    t: list[datetime] = field(default_factory=list)
    vals: dict[tuple[str, str], list[float | None]] = field(default_factory=dict)  # (service, metric) -> per-poll value / None
    failed: dict[tuple[str, str], int] = field(default_factory=dict)
    probes: dict[str, list[bool | None]] = field(default_factory=dict)


class Verifier:
    def __init__(self, repo: Repository, catalog: Catalog, cfg: DetectorConfig, prom: PromClient, prober: Prober,
                 collector: EvidenceCollector, audit: AuditWriter, clock: Clock, vcfg: VerifierConfig | None = None) -> None:
        self.repo, self.catalog, self.cfg, self.prom, self.prober = repo, catalog, cfg, prom, prober
        self.collector, self.audit, self.clock = collector, audit, clock
        self.v = vcfg or VerifierConfig()

    # ------------------------------------------------------------------ sampling
    def _val(self, metric: str, svc: str, at: datetime, dep: str = "") -> tuple[float | None, bool]:
        res = self.prom.query(self.cfg.query(metric, svc, dep), at)
        if res.failed:
            return None, True
        vals = [s.points[-1][1] for s in res.series if s.points]
        return (min(vals) if vals else None), False

    def _sample(self, at: datetime, s: _Samples) -> None:
        s.t.append(at)
        for svc in self.catalog.names():
            kind = self.catalog.kind(svc)
            wants = [("up", "")]
            if kind in ("cache", "database"):
                wants.append(("cd_service_up", ""))
            if kind == "app":
                wants += [("request_rate", ""), ("error_ratio", ""), ("latency_p95", "")]
            if kind == "queue_worker":
                wants.append(("queue_depth", ""))
            if kind in ("app", "queue_worker"):
                wants += [("dependency_up", d) for d in self.catalog.dependencies(svc)]
            for metric, dep in wants:
                key = (svc, f"dependency_up:{dep}" if dep else metric)
                v, failed = self._val(metric, svc, at, dep)
                s.vals.setdefault(key, []).append(v)
                if failed:
                    s.failed[key] = s.failed.get(key, 0) + 1
            if self.catalog.get(svc).probe_url:
                r = self.prober.probe(svc, at)
                s.probes.setdefault(svc, []).append(r.ok)

    # ------------------------------------------------------------------ main
    def verify(self, incident_id: str, execution_id: str, affected: list[str], action_time: datetime | None = None,
               prior_recovered: bool = False) -> Verification:
        action_time = action_time or self.clock.now()
        pre = Facts([e for e in self.repo.list_evidence(incident_id) if e.payload.get("phase") == "pre_action"], self.catalog)
        baseline_at = action_time - timedelta(seconds=1)
        self.clock.sleep(self.v.settle_seconds)  # settling period after the executor returns
        window_start = self.clock.now()
        s = _Samples()
        end = window_start + timedelta(seconds=self.v.stability_window_seconds)
        while True:
            now = self.clock.now()
            self._sample(now, s)
            if now >= end:
                break
            self.clock.sleep(self.v.sample_interval_seconds)
        window_end = self.clock.now()
        post = self.collector.collect(incident_id, window_end, phase="post_action", include_events=False, include_probes=False)
        post_ids = {(e.service, e.payload.get("metric")): e.evidence_id for e in post}
        baseline = self._baseline(incident_id, pre)
        checks = self._checks(s, affected, pre, baseline, post_ids)
        verdict = self._verdict(checks, s, affected, pre, prior_recovered, incident_id)
        ver = Verification(incident_id=incident_id, execution_id=execution_id, verdict=verdict, window_start=window_start,
                           window_end=window_end, checks=checks)
        self.repo.save_verification(ver)
        self.audit.write("verifier", "verification.finished", {"verdict": verdict, "checks": {c.name: c.passed for c in checks}}, incident_id)
        self.collector.timeline.add(incident_id, window_end, "verification", f"verification {verdict}: " + ", ".join(
            f"{c.name}={'?' if c.passed is None else 'ok' if c.passed else 'FAIL'}" for c in checks), collected_at=window_end)
        return ver

    # ------------------------------------------------------------------ baseline = history before the first symptom
    def _baseline(self, incident_id: str, pre: Facts) -> dict[tuple[str, str], float]:
        inc = self.repo.get_incident(incident_id)
        out: dict[tuple[str, str], float] = {}
        if inc is None:
            return out
        end = inc.opened_at - timedelta(seconds=self.cfg.poll_interval_seconds * 6)
        start = end - timedelta(seconds=self.v.baseline_lookback_seconds)
        for svc in self.catalog.names():
            if self.catalog.kind(svc) != "app":
                continue
            for metric in ("error_ratio", "latency_p95"):
                res = self.prom.query_range(self.cfg.query(metric, svc), start, end, self.cfg.poll_interval_seconds)
                pts = [v for s_ in res.series for _, v in s_.points]
                if not res.failed and pts:
                    out[(svc, metric)] = sum(pts) / len(pts)
        return out

    # ------------------------------------------------------------------ checks
    def _checks(self, s: _Samples, affected: list[str], pre: Facts, baseline: dict, post_ids: dict) -> list[Check]:
        floor = self.cfg.low_traffic_floor_rps
        cat = self.catalog
        apps = [n for n in cat.names() if cat.kind(n) == "app"]

        def ev(*pairs) -> list[str]:
            return [post_ids[p] for p in pairs if p in post_ids]

        def avail(svc: str) -> bool | None:
            keys = [(svc, "up")] + ([(svc, "cd_service_up")] if cat.kind(svc) in ("cache", "database") else [])
            vals = [v for k in keys for v in s.vals.get(k, [])]
            if not vals or any(s.failed.get(k) for k in keys) or any(v is None for v in vals):
                return None
            return all(v == 1 for v in vals)

        checks: list[Check] = []
        # 1 readiness of affected services
        r = [avail(x) for x in affected]
        checks.append(Check(name="readiness", passed=None if any(x is None for x in r) else all(r),
                            detail="availability of " + ", ".join(affected) + " over the window" + ("" if None not in r else " could not be established"),
                            evidence=ev(*[(x, "up") for x in affected] + [(x, "cd_service_up") for x in affected])))
        # 2 dependencies of affected services (and the affected set itself) healthy
        dep_vals: list[bool | None] = []
        for x in affected:
            for d in cat.dependencies(x):
                k = (x, f"dependency_up:{d}")
                vs = s.vals.get(k)
                if vs is None:
                    continue
                dep_vals.append(None if (not vs or any(v is None for v in vs) or s.failed.get(k)) else all(v == 1 for v in vs))
            for d in cat.dependencies(x):
                dep_vals.append(avail(d))
        checks.append(Check(name="dependencies", passed=None if (not dep_vals or None in dep_vals) else all(dep_vals),
                            detail="dependency reachability (cd_dependency_up) and dependency availability over the window",
                            evidence=ev(*[(x, f"dependency_up:{d}") for x in affected for d in cat.dependencies(x)])))

        def sli(metric: str, limit_fn) -> Check:
            passed: list[bool | None] = []
            post_vals: list[float] = []
            pre_vals: list[float] = []
            base_vals: list[float] = []
            for a in apps:
                ratios, rates = s.vals.get((a, metric), []), s.vals.get((a, "request_rate"), [])
                if not ratios or s.failed.get((a, metric)) or s.failed.get((a, "request_rate")) or not rates:
                    passed.append(None)
                    continue
                usable = [(v, r_) for v, r_ in zip(ratios, rates) if v is not None and r_ is not None and r_ >= floor]
                if len(usable) < max(2, len(ratios) // 2):
                    passed.append(None)  # not enough traffic or data in the window to establish the SLI (fail closed)
                    continue
                vals = [v for v, _ in usable]
                post_vals.append(sum(vals) / len(vals))
                passed.append(max(vals) <= limit_fn(a))
                t = pre.ts(a, metric)
                if t and t.pts:
                    pre_vals.append(t.pts[-1][1] if t.tail_mean() is None else t.tail_mean())
                if (a, metric) in baseline:
                    base_vals.append(baseline[(a, metric)])
            res = None if (not passed or None in passed) else all(passed)
            return Check(name="error_sli" if metric == "error_ratio" else "latency_sli", passed=res,
                         baseline=(sum(base_vals) / len(base_vals)) if base_vals else None,
                         pre_action=(sum(pre_vals) / len(pre_vals)) if pre_vals else None,
                         post_action=(sum(post_vals) / len(post_vals)) if post_vals else None,
                         detail=f"{metric} over the window (traffic >= {floor} rps required)" + ("; could not be established" if res is None else ""),
                         evidence=ev(*[(a, metric) for a in apps]))

        checks.append(sli("error_ratio", lambda a: self.v.error_ratio_max))
        checks.append(sli("latency_p95", lambda a: cat.get(a).slo_latency_p95 or self.v.latency_default_max))
        # 5 synthetic transaction at every probe in the window
        pr = [v for vs in s.probes.values() for v in vs]
        checks.append(Check(name="synthetic_transaction", passed=None if (not pr or None in pr) else all(pr),
                            detail=f"{len(pr)} independent probes via the published probe URL" + ("; at least one could not be established" if None in pr else ""),
                            post_action=(sum(1 for v in pr if v) / len(pr)) if pr else None))
        # 6 no regression elsewhere
        others = [n for n in cat.names() if n not in affected]
        reg: list[bool | None] = []
        for o in others:
            reg.append(avail(o))
            if cat.kind(o) == "app":
                rv, vv = s.vals.get((o, "error_ratio"), []), s.vals.get((o, "request_rate"), [])
                use = [v for v, r_ in zip(rv, vv) if v is not None and r_ is not None and r_ >= floor]
                reg.append(None if (s.failed.get((o, "error_ratio")) or not use) else max(use) <= self.v.error_ratio_max)
        checks.append(Check(name="no_regression", passed=None if (None in reg) else all(reg),
                            detail="services outside the incident compared with the pre-action baseline: " + (", ".join(others) or "none"),
                            evidence=ev(*[(o, "up") for o in others])))
        # 7 telemetry fresh: no failed/empty collection inside the window
        nfail = sum(s.failed.values())
        gaps = sum(1 for k, vs in s.vals.items() if k[1] in ("up", "cd_service_up") and any(v is None for v in vs))
        checks.append(Check(name="telemetry_fresh", passed=(nfail == 0 and gaps == 0),
                            detail=f"{nfail} failed queries and {gaps} availability series with gaps during the window"))
        return checks

    def _verdict(self, checks: list[Check], s: _Samples, affected: list[str], pre: Facts, prior_recovered: bool, incident_id: str) -> str:
        by = {c.name: c for c in checks}
        if by["no_regression"].passed is False:
            return "regression"
        if any(c.passed is None for c in checks):
            return "unverifiable"  # fail closed
        if all(c.passed for c in checks):
            return "recovered"
        if prior_recovered or any(v.verdict == "recovered" for v in self.repo.list_verifications(incident_id)):
            return "relapse"
        e = by["error_sli"]
        improved = e.pre_action is not None and e.post_action is not None and e.post_action < e.pre_action * 0.5
        # partial = measurable improvement (service answers again, or the error SLI at least halved) but not all terms hold;
        # a trivially passing term (e.g. latency of fail-fast errors) is NOT improvement.
        return "partial" if (by["readiness"].passed is True or improved) else "failed"
