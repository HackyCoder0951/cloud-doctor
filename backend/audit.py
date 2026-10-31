"""Audit writer: append-only hash chain exactly as contracts/schemas/audit_event.json describes.

hash = sha256 over canonical JSON of {seq, incident_id, actor, event, detail, prev_hash, created_at};
prev_hash of the first event is 'sha256:' + 64 zeros. Failure to write raises (callers fail closed).
"""
from __future__ import annotations

import threading

from backend.domain.canonical import ZERO_HASH, canonical_json, sha256_tag, strip_nul
from backend.domain.clock import Clock, SystemClock, iso
from backend.domain.models import AuditEvent
from backend.repositories.base import Repository


def compute_hash(seq: int, incident_id: str | None, actor: str, event: str, detail: dict, prev_hash: str, created_at: str) -> str:
    body = {"seq": seq, "incident_id": incident_id, "actor": actor, "event": event, "detail": detail,
            "prev_hash": prev_hash, "created_at": created_at}
    if incident_id is None:
        body.pop("incident_id")  # absent optional field is omitted from the hashed object
    return sha256_tag(canonical_json(body))


def verify_chain(events: list[AuditEvent]) -> bool:
    prev, seq = ZERO_HASH, 0
    for e in events:
        seq += 1
        if e.seq != seq or e.prev_hash != prev:
            return False
        if compute_hash(e.seq, e.incident_id, e.actor, e.event, e.detail, e.prev_hash, iso(e.created_at)) != e.hash:
            return False
        prev = e.hash
    return True


class AuditWriter:
    def __init__(self, repo: Repository, clock: Clock | None = None) -> None:
        self._repo = repo
        self._clock = clock or SystemClock()
        self._lock = threading.Lock()

    def write(self, actor: str, event: str, detail: dict | None = None, incident_id: str | None = None) -> AuditEvent:
        detail = strip_nul(detail or {})
        with self._lock:  # serialise chain writers (the DB also takes an advisory lock)
            last = self._repo.last_audit()
            seq = (last.seq + 1) if last else 1
            prev = last.hash if last else ZERO_HASH
            created = self._clock.now()
            h = compute_hash(seq, incident_id, actor, event, detail, prev, iso(created))
            ev = AuditEvent(seq=seq, incident_id=incident_id, actor=actor, event=event, detail=detail,
                            prev_hash=prev, hash=h, created_at=created)
            self._repo.append_audit(ev)
            return ev

    def chain_valid(self) -> bool:
        return verify_chain(self._repo.all_audit())
