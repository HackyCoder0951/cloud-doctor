"""Timeline builder. event_time (when it happened) is kept apart from collected_at (when we learned of it).

Duplicates (same kind/service/event_time/summary, e.g. replayed alerts) are dropped; suppressed events are kept and
flagged: suppression affects notification only, never recording. Summaries are generated text (never raw log lines).
"""
from __future__ import annotations

from datetime import datetime

from backend.domain.clock import Clock, iso
from backend.domain.models import TimelineEvent
from backend.repositories.base import Repository


class TimelineBuilder:
    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo, self._clock = repo, clock

    @staticmethod
    def _key(kind: str, service: str | None, event_time: datetime, summary: str) -> tuple:
        return (kind, service, iso(event_time), summary)

    def add(self, incident_id: str, event_time: datetime, kind: str, summary: str, service: str | None = None,
            evidence_refs: list[str] | None = None, suppressed: bool = False, collected_at: datetime | None = None) -> TimelineEvent | None:
        summary = summary[:300]
        existing = self._repo.list_events(incident_id)
        k = self._key(kind, service, event_time, summary)
        for e in existing:
            if self._key(e.kind, e.service, e.event_time, e.summary) == k:
                return None  # duplicate
        ev = TimelineEvent(event_id=self._repo.next_event_id(incident_id), incident_id=incident_id, event_time=event_time,
                           collected_at=collected_at or self._clock.now(), kind=kind, service=service,
                           summary=summary, evidence_refs=list(evidence_refs or []), suppressed=suppressed)
        self._repo.add_event(ev)
        return ev

    def attach_evidence(self, incident_id: str, evidence) -> TimelineEvent | None:
        kind = {"container_event": "container_event", "deploy_event": "deploy_event", "loki": "log_burst"}.get(evidence.source, "metric_change")
        return self.add(incident_id, evidence.observed_at, kind, f"[{evidence.evidence_id}] {evidence.summary or evidence.source}",
                        evidence.service, [evidence.evidence_id], collected_at=evidence.collected_at)
