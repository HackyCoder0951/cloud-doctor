"""Load run records and derive timestamps/classifications from them. Metrics read only through this module."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from harness.clock import iso, parse_ts
from harness.store import FILES

TERMINAL_STATES = ("recovered", "escalated", "closed")
EXECUTED_RESULTS = ("success", "failed")


def sli_ok(value: Any, op: str, threshold: float) -> bool:
    return isinstance(value, (int, float)) and (value <= threshold if op == "<=" else value >= threshold)


def steady_satisfied(services: dict[str, dict], steady_state: Iterable[dict]) -> bool:
    """All conditions hold and are present (missing data is not 'steady'; fail closed)."""
    return all(sli_ok(services.get(c["service"], {}).get(c["sli"]), c["op"], c["threshold"]) for c in steady_state)


def steady_violated(services: dict[str, dict], steady_state: Iterable[dict]) -> list[str]:
    """Services with a PRESENT sli value that breaches its condition."""
    out = []
    for c in steady_state:
        v = services.get(c["service"], {}).get(c["sli"])
        if isinstance(v, (int, float)) and not sli_ok(v, c["op"], c["threshold"]):
            out.append(c["service"])
    return out


@dataclass(frozen=True)
class Sample:
    t: datetime
    services: dict[str, dict]


@dataclass
class IncidentView:
    incident_id: str
    incident: dict
    first_seen: datetime
    timeline: list[dict] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    first_diagnosis: dict | None = None
    diagnosis: dict | None = None
    remediation: dict = field(default_factory=dict)
    verifications: list[dict] = field(default_factory=list)
    report: dict | None = None

    @property
    def opened_at(self) -> datetime:
        return parse_ts(self.incident["opened_at"])

    @property
    def services(self) -> frozenset[str]:
        return frozenset(self.incident.get("services", []))


@dataclass
class RunRecord:
    run_id: str
    metadata: dict
    scenario: dict
    kind: str
    events: list[dict]
    samples: list[Sample]
    incidents: dict[str, IncidentView]
    audit_chain_valid: bool | None
    api_errors: int

    def event(self, name: str) -> dict | None:
        return next((e for e in self.events if e["event"] == name), None)

    def _t(self, name: str) -> datetime | None:
        e = self.event(name)
        return parse_ts(e["t"]) if e else None

    @property
    def started_at(self) -> datetime | None:
        return parse_ts(self.metadata["started_at"]) if self.metadata.get("started_at") else None

    @property
    def t_inject(self) -> datetime | None:
        return self._t("inject")

    @property
    def status(self) -> str:
        e = self.event("run_end")
        return e["status"] if e else "incomplete"

    @property
    def abort_reason(self) -> str | None:
        e = self.event("abort")
        return e["reason"] if e else None

    @property
    def observe_seconds(self) -> float:
        """Seconds with the system observed in the observe/control phase (control runs: the FP-rate exposure)."""
        e = self.event("observe_window")
        return float(e["seconds"]) if e else 0.0


@dataclass(frozen=True)
class DetectionEvent:
    t: datetime
    services: frozenset[str]
    ref: str


@dataclass
class Classification:
    tp: DetectionEvent | None
    duplicates: list[DetectionEvent]
    late: list[DetectionEvent]
    fp: list[DetectionEvent]


def classify_events(events: list[DetectionEvent], t_inject: datetime | None, deadline_s: float,
                    affected: Iterable[str]) -> Classification:
    """Per-fault (never point-adjusted) scoring.

    tp: first event inside [t_inject, t_inject+deadline] touching an affected service.
    duplicates: further such events (same fault). late: touching an affected service after the deadline (the
    fault counts as missed; the event is not also a false positive). fp: everything else; in a control run
    (t_inject None) every event is a false positive.
    """
    affected = set(affected)
    out = Classification(None, [], [], [])
    for ev in sorted(events, key=lambda e: e.t):
        if t_inject is None:
            out.fp.append(ev)
            continue
        overlaps = bool(ev.services & affected)
        offset = (ev.t - t_inject).total_seconds()
        if overlaps and 0 <= offset <= deadline_s:
            if out.tp is None:
                out.tp = ev
            else:
                out.duplicates.append(ev)
        elif overlaps and offset > deadline_s:
            out.late.append(ev)
        else:
            out.fp.append(ev)
    return out


def incident_events(rec: RunRecord) -> list[DetectionEvent]:
    return [DetectionEvent(v.opened_at, v.services, v.incident_id) for v in rec.incidents.values()]


def classify_run(rec: RunRecord) -> Classification:
    return classify_events(incident_events(rec), rec.t_inject, rec.scenario["timing"]["detection_deadline_seconds"],
                           rec.scenario["affected_services"])


def tp_incident(rec: RunRecord) -> IncidentView | None:
    tp = classify_run(rec).tp
    return rec.incidents[tp.ref] if tp else None


def executions_of(view: IncidentView, executed_only: bool = True) -> list[dict]:
    ex = view.remediation.get("executions", [])
    return [e for e in ex if not executed_only or e.get("result") in EXECUTED_RESULTS]


def derive_timestamps(rec: RunRecord) -> dict[str, str | None]:
    t_inject = rec.t_inject
    t_impact = None
    if t_inject is not None:
        for s in rec.samples:
            if s.t >= t_inject and steady_violated(s.services, rec.scenario["steady_state"]):
                t_impact = s.t
                break
    view = tp_incident(rec)
    t_detect = view.opened_at if view else None
    t_diagnose = t_action = t_recover = None
    if view:
        diag_times = [parse_ts(e["event_time"]) for e in view.timeline if e.get("kind") == "diagnosis"]
        if view.first_diagnosis:
            diag_times.append(parse_ts(view.first_diagnosis["generated_at"]))
        t_diagnose = min(diag_times) if diag_times else None
        starts = [parse_ts(e["started_at"]) for e in executions_of(view)]
        t_action = min(starts) if starts else None
        ok = [parse_ts(v["window_end"]) for v in view.verifications if v.get("verdict") == "recovered"]
        t_recover = min(ok) if ok else None
    return {"t_inject": iso(t_inject), "t_impact": iso(t_impact), "t_detect": iso(t_detect),
            "t_diagnose": iso(t_diagnose), "t_action": iso(t_action), "t_recover": iso(t_recover)}


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(directory: str | Path) -> RunRecord:
    d = Path(directory)
    meta_lines = _lines(d / FILES["metadata"])
    if not meta_lines:
        raise ValueError(f"{d}: no metadata")
    metadata = meta_lines[0]
    events = _lines(d / FILES["ground_truth"])
    samples: list[Sample] = []
    views: dict[str, IncidentView] = {}
    chain: bool | None = None
    errors = 0
    for r in _lines(d / FILES["api"]):
        kind = r["kind"]
        if kind == "sample":
            samples.append(Sample(parse_ts(r["t"]), r["services"]))
        elif kind == "incident_snapshot":
            data = r["data"]
            v = views.get(r["incident_id"])
            if v is None:
                v = views[r["incident_id"]] = IncidentView(r["incident_id"], data["incident"], parse_ts(r["t"]))
            v.incident = data["incident"]
            v.timeline = data.get("timeline", v.timeline)
            v.evidence_ids = data.get("evidence_ids", v.evidence_ids)
            if data.get("diagnosis"):
                v.diagnosis = data["diagnosis"]
                v.first_diagnosis = v.first_diagnosis or data["diagnosis"]
            v.remediation = data.get("remediation") or v.remediation
            v.verifications = data.get("verification", v.verifications)
            v.report = data.get("report") or v.report
        elif kind == "audit":
            chain = r["chain_valid"] if chain is not False else False
        elif kind == "api_error":
            errors += 1
    return RunRecord(metadata["run_id"], metadata, metadata["scenario"], metadata["kind"], events, samples, views,
                     chain, errors)


def load_runs(root: str | Path) -> list[RunRecord]:
    root = Path(root)
    if not root.is_dir():
        return []
    return [load_run(p) for p in sorted(root.iterdir()) if p.is_dir() and (p / FILES["metadata"]).exists()]
