"""Evidence collector.

Rules (contracts/schemas/evidence.json, docs/10-architecture/tech-stack.md 2.3):
  * stores query, status, summary and payload;
  * strips NUL characters from payload text BEFORE storing;
  * computes payload_hash over canonical JSON BEFORE insert (never recomputed from stored JSONB);
  * log evidence is untrusted; summaries are generated from counts, never from log text;
  * a failed/timed-out query is stored as status error/timeout with missing_signal_state collection_failed,
    never as an empty result;
  * ``snapshot_before_action`` preserves evidence that a restart would destroy.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.audit import AuditWriter
from backend.detector.config import DetectorConfig
from backend.detector.expected import ExpectedStateRegistry
from backend.domain.canonical import payload_hash, strip_nul
from backend.domain.catalog import Catalog
from backend.domain.clock import Clock, iso
from backend.domain.models import Evidence
from backend.incidents.timeline import TimelineBuilder
from backend.repositories.base import Repository
from backend.telemetry.base import (EMPTY, ChangeFeed, LogClient, Prober, PromClient, PromResult,
                                    missing_signal_for)

MAX_LINES, MAX_LINE_CHARS = 100, 500

KIND_METRICS = {
    "app": ["up", "request_rate", "error_ratio", "latency_p95", "build_version", "start_time", "memory_bytes", "cpu_cores"],
    "queue_worker": ["up", "queue_depth", "start_time", "memory_bytes"],
    "cache": ["up", "cd_service_up"],
    "database": ["up", "cd_service_up"],
    "load_generator": ["up", "start_time"],
}


def _fmt(v: float) -> str:
    return f"{v:.3g}"


class EvidenceCollector:
    def __init__(self, repo: Repository, catalog: Catalog, cfg: DetectorConfig, prom: PromClient, logs: LogClient,
                 feed: ChangeFeed, prober: Prober, registry: ExpectedStateRegistry, audit: AuditWriter, clock: Clock,
                 timeline: TimelineBuilder | None = None, lookback_seconds: int = 300) -> None:
        self.repo, self.catalog, self.cfg, self.prom, self.logs, self.feed, self.prober = repo, catalog, cfg, prom, logs, feed, prober
        self.registry, self.audit, self.clock = registry, audit, clock
        self.timeline = timeline or TimelineBuilder(repo, clock)
        self.lookback = timedelta(seconds=lookback_seconds)

    # ------------------------------------------------------------------ storing
    def store(self, incident_id: str, *, source: str, type: str, service: str, observed_at: datetime, query: str, status: str,
              missing: str, summary: str, payload: dict, untrusted: bool, salient: bool = True) -> Evidence:
        payload = strip_nul(payload)  # 1. strip NUL (JSONB rejects \u0000)
        ev = Evidence(evidence_id=self.repo.next_evidence_id(incident_id), incident_id=incident_id, source=source, type=type,
                      service=service, observed_at=observed_at, collected_at=self.clock.now(), query=strip_nul(query)[:2000],
                      status=status, missing_signal_state=missing, summary=strip_nul(summary)[:500], payload=payload,
                      payload_hash=payload_hash(payload),  # 2. hash the canonical JSON BEFORE insert
                      untrusted=untrusted)
        self.repo.add_evidence(ev)
        if salient or status in ("error", "timeout"):  # routine context readings stay in the evidence store, not the timeline
            self.timeline.attach_evidence(incident_id, ev)
        return ev

    # ------------------------------------------------------------------ metrics
    def _metric(self, incident_id: str, svc: str, metric: str, dep: str, start: datetime, end: datetime, phase: str) -> Evidence:
        name = f"dependency_up:{dep}" if dep else metric
        q = self.cfg.query(metric, svc, dep)
        res = self.prom.query_range(q, start, end, self.cfg.poll_interval_seconds)
        base = {"metric": name, "phase": phase, "window": {"start": iso(start), "end": iso(end)}}
        if res.failed:
            return self.store(incident_id, source="prometheus", type="metric", service=svc, observed_at=end, query=q, status=res.status,
                              missing="collection_failed", summary=f"{svc} {name}: collection {res.status} ({res.error or 'no detail'}); signal NOT observed",
                              payload={**base, "error": res.error or res.status, "series": []}, untrusted=False)
        if metric == "build_version":
            versions = [{"t": iso(p[0]), "version": s.labels.get("version", "")} for s in res.series for p in s.points]
            versions.sort(key=lambda r: r["t"])
            payload = {**base, "versions": versions, "series": []}
            observed = end
            summary = f"{svc} versions seen: {sorted({v['version'] for v in versions}) or 'none'}"
        else:
            pts = sorted(((t, v) for s in res.series for t, v in s.points), key=lambda p: p[0])
            payload = {**base, "series": [{"t": iso(t), "v": v} for t, v in pts]}
            if pts:
                vals = [v for _, v in pts]
                observed = pts[-1][0]
                if name in ("up", "cd_service_up") or name.startswith("dependency_up"):
                    zero = next((t for t, v in pts if v == 0), None)
                    observed = zero or observed
                summary = (f"{svc} {name}: first {_fmt(vals[0])}, last {_fmt(vals[-1])}, min {_fmt(min(vals))}, max {_fmt(max(vals))} "
                           f"over {len(vals)} samples" + (f"; zero since {iso(observed)[11:19]}" if name in ("up", "cd_service_up") and observed and vals[-1] == 0 else ""))
            else:
                observed, summary = end, f"{svc} {name}: no samples in window"
        status = res.status if res.series else EMPTY
        expected = self.registry.active(svc, end) is not None
        return self.store(incident_id, source="prometheus", type="metric", service=svc, observed_at=observed, query=q, status=status,
                          missing=missing_signal_for(status, expected), summary=summary, payload=payload, untrusted=False,
                          salient=self._salient_metric(metric, payload, status))

    @staticmethod
    def _salient_metric(metric: str, payload: dict, status: str) -> bool:
        if status != "ok":
            return True  # a signal that disappeared is itself notable
        if metric == "build_version":
            return len({v["version"] for v in payload.get("versions", [])}) > 1
        vals = [p["v"] for p in payload.get("series", [])]
        if len(vals) < 2:
            return False
        if metric in ("up", "cd_service_up") or "dependency_up" in str(payload.get("metric", "")):
            return min(vals) == 0
        first, last = vals[0], vals[-1]
        return abs(last - first) > 0.3 * max(abs(first), 1e-9) and abs(last - first) > 1e-6 * max(abs(first), 1.0) and metric != "start_time" or \
            (metric == "start_time" and last > first + 1)

    def _logs(self, incident_id: str, svc: str, start: datetime, end: datetime, phase: str) -> Evidence:
        q = f'{{service="{svc}"}}'
        res = self.logs.query_range(q, start, end, MAX_LINES)
        base = {"metric": "logs", "phase": phase, "window": {"start": iso(start), "end": iso(end)}}
        if res.failed:
            return self.store(incident_id, source="loki", type="log", service=svc, observed_at=end, query=q, status=res.status,
                              missing="collection_failed", summary=f"{svc} logs: collection {res.status}; log signal NOT observed",
                              payload={**base, "error": res.error or res.status, "lines": []}, untrusted=True)
        lines = [{"t": iso(l.t), "level": l.level[:16], "line": strip_nul(l.line)[:MAX_LINE_CHARS]} for l in res.lines[:MAX_LINES]]
        errs = sum(1 for l in lines if l["level"] in ("error", "fatal", "critical"))
        status = res.status if lines else EMPTY
        observed = res.lines[-1].t if res.lines else end
        return self.store(incident_id, source="loki", type="log", service=svc, observed_at=observed, query=q, status=status,
                          missing=missing_signal_for(status, self.registry.active(svc, end) is not None),
                          summary=f"{svc} logs: {len(lines)} lines, {errs} error-level in window (text is untrusted)",
                          payload={**base, "lines": lines, "truncated": len(res.lines) > MAX_LINES}, untrusted=True, salient=errs > 0)

    def _events(self, incident_id: str, services: list[str], start: datetime, end: datetime, phase: str) -> list[Evidence]:
        res = self.feed.events(start, end)
        if res.status in ("error", "timeout"):
            return [self.store(incident_id, source="deploy_event", type="event", service=services[0], observed_at=end, query="change_feed",
                               status=res.status, missing="collection_failed", summary="change feed unavailable; deploys/container events NOT observed",
                               payload={"metric": "change_feed", "phase": phase, "error": res.error or res.status, "kind": "unavailable"}, untrusted=False)]
        out = []
        for e in res.events:
            src = "deploy_event" if e.kind == "deploy" else "container_event"
            out.append(self.store(incident_id, source=src, type="event", service=e.service, observed_at=e.event_time, query="change_feed",
                                  status="ok", missing="none",
                                  summary=f"{e.service} {e.kind}" + (f" {e.detail.get('version_from')} -> {e.detail.get('version_to')}" if e.kind == "deploy" else ""),
                                  payload={"metric": "change_event", "phase": phase, "kind": e.kind, "detail": e.detail, "event_time": iso(e.event_time)},
                                  untrusted=False))
        return out

    def _probe(self, incident_id: str, svc: str, at: datetime, phase: str) -> Evidence | None:
        if not self.catalog.get(svc).probe_url:
            return None
        r = self.prober.probe(svc, at)
        if r.ok is None:
            return self.store(incident_id, source="synthetic_probe", type="probe", service=svc, observed_at=at, query=f"probe {svc}",
                              status="error", missing="collection_failed", summary=f"{svc} synthetic probe could not be established",
                              payload={"metric": "synthetic_probe", "phase": phase, "ok": None, "error": r.error or "unknown"}, untrusted=False)
        return self.store(incident_id, source="synthetic_probe", type="probe", service=svc, observed_at=at, query=f"probe {svc}", status="ok",
                          missing="none", summary=f"{svc} synthetic transaction {'succeeded' if r.ok else 'FAILED'} (status {r.status_code})",
                          payload={"metric": "synthetic_probe", "phase": phase, "ok": r.ok, "status_code": r.status_code, "latency_s": r.latency_s},
                          untrusted=False, salient=not r.ok)

    # ------------------------------------------------------------------ public
    def collect(self, incident_id: str, at: datetime | None = None, phase: str = "initial", services: list[str] | None = None,
                include_logs: bool = True, include_events: bool = True, include_probes: bool = True) -> list[Evidence]:
        """Snapshot of every catalog service (context for contradicting evidence), not only the affected ones."""
        at = at or self.clock.now()
        start = at - self.lookback
        out: list[Evidence] = []
        names = services or self.catalog.names()
        for svc in names:
            kind = self.catalog.kind(svc)
            for metric in KIND_METRICS.get(kind, ["up"]):
                out.append(self._metric(incident_id, svc, metric, "", start, at, phase))
            if kind in ("app", "queue_worker"):
                for dep in self.catalog.dependencies(svc):
                    out.append(self._metric(incident_id, svc, "dependency_up", dep, start, at, phase))
            if include_logs and kind in ("app", "queue_worker", "load_generator"):
                out.append(self._logs(incident_id, svc, start, at, phase))
            if include_probes and (p := self._probe(incident_id, svc, at, phase)):
                out.append(p)
        if include_events:
            out.extend(self._events(incident_id, names, start, at, phase))
        self.audit.write("rca", "evidence.collected", {"phase": phase, "count": len(out),
                                                       "failed": sum(1 for e in out if e.status in ("error", "timeout"))}, incident_id)
        return out

    def snapshot_before_action(self, incident_id: str, at: datetime | None = None) -> list[Evidence]:
        """Must run BEFORE any remediation action: restarts destroy in-memory state and logs."""
        evs = self.collect(incident_id, at, phase="pre_action")
        self.audit.write("planner", "evidence.pre_action_snapshot", {"evidence_ids": [e.evidence_id for e in evs]}, incident_id)
        return evs

    def has_pre_action_snapshot(self, incident_id: str) -> bool:
        return any(e.payload.get("phase") == "pre_action" for e in self.repo.list_evidence(incident_id))
