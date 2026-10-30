"""Incident manager: groups alerts into incidents and runs the incident state machine.

Grouping (docs/03-failure-detection/alert-correlation.md): an alert joins an open incident when its service is in the
connected component (dependency graph, edges undirected) formed with the incident's services AND it is within the time
window of the incident's last activity. Otherwise a separate incident is opened, so an unrelated concurrent fault never
becomes a mega-incident. Suppressed alerts are recorded in the timeline but never open an incident.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.audit import AuditWriter
from backend.detector.config import DetectorConfig
from backend.detector.engine import BackgroundEvent, PollResult
from backend.domain.catalog import Catalog
from backend.domain.clock import Clock
from backend.domain.models import Alert, Incident
from backend.repositories.base import Repository

from .timeline import TimelineBuilder

TRANSITIONS: dict[str, set[str]] = {
    "detected": {"investigating", "escalated", "closed"},
    "investigating": {"diagnosed", "escalated", "closed"},
    "diagnosed": {"remediating", "escalated", "closed"},
    "remediating": {"verifying", "escalated"},
    "verifying": {"recovered", "remediating", "escalated"},
    "recovered": {"closed"},
    "escalated": {"closed"},
    "closed": set(),
}
OPEN_STATES = {"detected", "investigating", "diagnosed", "remediating", "verifying", "escalated"}


class InvalidTransition(ValueError):
    pass


class IncidentManager:
    def __init__(self, repo: Repository, catalog: Catalog, cfg: DetectorConfig, audit: AuditWriter, clock: Clock,
                 close_after_seconds: int = 60, relapse_window_seconds: int = 600) -> None:
        self.repo, self.catalog, self.cfg, self.audit, self.clock = repo, catalog, cfg, audit, clock
        self.timeline = TimelineBuilder(repo, clock)
        self.close_after, self.relapse_window = close_after_seconds, relapse_window_seconds
        self._last_activity: dict[str, datetime] = {}
        self._alert_incident: dict[str, str] = {}  # active alert fingerprint -> incident
        self._active: dict[str, dict[str, Alert]] = {}  # incident -> firing alerts
        self.background: list[BackgroundEvent] = []
        self._bg_keys: set[str] = set()
        self.listeners: list = []  # callables(event_type: str, incident_id: str | None, data: dict)

    # ------------------------------------------------------------------ events out (SSE bus)
    def _emit(self, typ: str, incident_id: str | None = None, **data) -> None:
        for fn in self.listeners:
            fn(typ, incident_id, data)

    # ------------------------------------------------------------------ ingest
    def ingest(self, poll: PollResult) -> list[str]:
        """Process one detector poll. Returns ids of incidents touched."""
        for b in poll.background:
            if b.key not in self._bg_keys:
                self._bg_keys.add(b.key)
                self.background.append(b)
        touched: list[str] = []
        for alert in sorted(poll.alerts, key=lambda a: (a.observed_at, a.fingerprint)):
            inc_id = self._handle(alert, poll.at)
            if inc_id and inc_id not in touched:
                touched.append(inc_id)
        return touched

    def _region_match(self, inc: Incident, service: str) -> bool:
        members = set(inc.services)
        return service in members or bool(self.catalog.neighbours(service) & members)

    def _find(self, alert: Alert) -> Incident | None:
        window = timedelta(seconds=self.cfg.incident_window_seconds)
        best = None
        for inc in self.repo.list_incidents(limit=200):
            if inc.state not in OPEN_STATES or not self._region_match(inc, alert.service):
                continue
            last = self._last_activity.get(inc.incident_id, inc.opened_at)
            active = bool(self._active.get(inc.incident_id))
            if active or alert.fired_at - last <= window:
                if best is None or inc.opened_at < best.opened_at:
                    best = inc
        return best

    def _handle(self, alert: Alert, now: datetime) -> str | None:
        rule = self.cfg.rules.get(alert.rule)
        opens = rule is None or rule.params.get("opens_incident", True)
        if alert.state == "resolved":
            inc_id = self._alert_incident.pop(alert.fingerprint, None)
            if not inc_id:
                return None
            self._active.get(inc_id, {}).pop(alert.fingerprint, None)
            self._last_activity[inc_id] = now
            self.timeline.add(inc_id, alert.resolved_at or now, "alert", f"resolved: {alert.summary}", alert.service, suppressed=alert.suppressed,
                              collected_at=now)
            self.repo.save_alert(alert.model_copy(update={"incident_id": inc_id}))
            self._emit("incident.updated", inc_id, service=alert.service)
            return inc_id
        # firing
        inc = self._find(alert)
        if alert.suppressed:
            # recorded, not opened: attach to a related incident's timeline, else keep as background
            if inc:
                self._attach(inc, alert, now)
                return inc.incident_id
            self._bg(BackgroundEvent(alert.observed_at, now, "alert", alert.service,
                                     f"suppressed ({alert.suppress_reason}): {alert.summary}", True, f"supp/{alert.fingerprint}/{alert.fired_at.isoformat()}"))
            self.repo.save_alert(alert)
            return None
        if inc:
            self._attach(inc, alert, now)
            return inc.incident_id
        if not opens:
            self._bg(BackgroundEvent(alert.observed_at, now, "container_event" if alert.rule == "restart" else "alert", alert.service,
                                     alert.summary, False, f"info/{alert.fingerprint}/{alert.observed_at.isoformat()}"))
            self.repo.save_alert(alert)
            return None
        return self._open(alert, now).incident_id

    def _bg(self, b: BackgroundEvent) -> None:
        if b.key not in self._bg_keys:
            self._bg_keys.add(b.key)
            self.background.append(b)

    def _attach(self, inc: Incident, alert: Alert, now: datetime) -> None:
        changed = False
        if alert.service not in inc.services:
            inc.services.append(alert.service)
            changed = True
        sym = alert.summary[:200]
        if sym and sym not in inc.symptoms and not alert.suppressed:
            inc.symptoms.append(sym)
            changed = True
        sev = self._severity(inc, alert)
        if sev != inc.severity:
            inc.severity, changed = sev, True
        if changed:
            self.repo.save_incident(inc)
        self._alert_incident[alert.fingerprint] = inc.incident_id
        if not alert.suppressed:
            self._active.setdefault(inc.incident_id, {})[alert.fingerprint] = alert
        self._last_activity[inc.incident_id] = now
        self.timeline.add(inc.incident_id, alert.observed_at, "alert", alert.summary, alert.service, suppressed=alert.suppressed, collected_at=alert.fired_at)
        self.repo.save_alert(alert.model_copy(update={"incident_id": inc.incident_id}))
        if changed:
            self._emit("incident.updated", inc.incident_id, service=alert.service)

    @staticmethod
    def _severity(inc: Incident, alert: Alert) -> str:
        order = ["low", "medium", "high", "critical"]
        base = "high" if alert.severity == "critical" else "medium"
        if len(inc.services) >= 4:
            base = "critical"
        return max(inc.severity, base, key=order.index)

    def _open(self, alert: Alert, now: datetime) -> Incident:
        inc = Incident(incident_id=self.repo.next_incident_id(), state="detected", opened_at=now, severity="medium",
                       services=[alert.service], symptoms=[alert.summary[:200]])
        inc.severity = self._severity(inc, alert)
        for prev in self.repo.list_incidents(limit=200):  # relapse: a recently recovered/closed incident on the same service
            if prev.state in ("recovered", "closed") and alert.service in prev.services and prev.closed_at \
                    and now - prev.closed_at <= timedelta(seconds=self.relapse_window):
                inc.symptoms.append(f"possible relapse of {prev.incident_id}")
                break
        self.repo.save_incident(inc)
        self.audit.write("detector", "incident.opened", {"services": inc.services, "rule": alert.rule}, inc.incident_id)
        self._attach(inc, alert, now)
        self.timeline.add(inc.incident_id, now, "note", f"incident opened (rule {alert.rule}, {alert.service})", alert.service, collected_at=now)
        # attach prior background observations on related services (e.g. restarts just before the incident)
        self.merge_background(inc.incident_id)
        self._emit("incident.opened", inc.incident_id, service=alert.service)
        return self.repo.get_incident(inc.incident_id)

    def merge_background(self, incident_id: str, lookback_seconds: int = 300) -> int:
        inc = self.repo.get_incident(incident_id)
        n = 0
        for b in self.background:
            if b.service and self._region_match(inc, b.service) and b.event_time >= inc.opened_at - timedelta(seconds=lookback_seconds):
                if self.timeline.add(incident_id, b.event_time, b.kind, b.summary, b.service, suppressed=b.suppressed, collected_at=b.collected_at):
                    n += 1
        return n

    # ------------------------------------------------------------------ state machine
    def transition(self, incident_id: str, new_state: str, actor: str = "api", reason: str = "",
                   outcome: str | None = None, root_cause_confirmed: bool | None = None) -> Incident:
        inc = self.repo.get_incident(incident_id)
        if inc is None:
            raise KeyError(incident_id)
        if new_state not in TRANSITIONS[inc.state]:
            raise InvalidTransition(f"{inc.state} -> {new_state}")
        now = self.clock.now()
        old = inc.state
        inc.state = new_state
        if outcome:
            inc.outcome = outcome
        if root_cause_confirmed is not None:
            inc.root_cause_confirmed = root_cause_confirmed
        if new_state in ("closed",):
            inc.closed_at = now
        if new_state == "recovered":
            inc.closed_at = now
        self.repo.save_incident(inc)
        self.audit.write(actor, "incident.state_changed", {"from": old, "to": new_state, "reason": reason[:200]}, incident_id)
        self.timeline.add(incident_id, now, "note", f"incident {old} -> {new_state}" + (f": {reason[:150]}" if reason else ""), collected_at=now)
        self._last_activity[incident_id] = now
        self._emit("incident.updated", incident_id, state=new_state)
        return inc

    def sweep(self, now: datetime) -> list[str]:
        """Auto-close incidents whose alerts all resolved without any action (transient / self-recovered)."""
        closed = []
        for inc in self.repo.list_incidents(limit=200):
            if inc.state in ("detected", "investigating", "diagnosed") and not self._active.get(inc.incident_id) \
                    and now - self._last_activity.get(inc.incident_id, inc.opened_at) >= timedelta(seconds=self.close_after):
                self.transition(inc.incident_id, "closed", "detector", "all alerts resolved without remediation (self-recovered)", outcome="unresolved")
                closed.append(inc.incident_id)
        return closed

    def active_alerts(self, incident_id: str) -> list[Alert]:
        return list(self._active.get(incident_id, {}).values())
