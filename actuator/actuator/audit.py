"""Hash-chained NDJSON audit sink (contracts/schemas/audit_event.json)."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Callable, Iterator

from invariants import canonical_json, sha256_tag

GENESIS = "sha256:" + "0" * 64
_HASHED = ("seq", "incident_id", "actor", "event", "detail", "prev_hash", "created_at")
_ACTOR = re.compile(r"(detector|rca|planner|policy|actuator|verifier|api|harness|operator:[A-Za-z0-9._-]{1,40})")
_EVENT = re.compile(r"[a-z][a-z0-9_.]{2,60}")
_INCIDENT = re.compile(r"INC-[0-9]{4,}")


class AuditError(Exception):
    """The audit trail could not be written or verified; callers must refuse the action."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_hash(event: dict) -> str:
    """sha256 over canonical JSON of {seq, incident_id, actor, event, detail, prev_hash, created_at};
    a key that is absent from the event (no incident) is absent from the hashed object."""
    return sha256_tag(canonical_json({k: event[k] for k in _HASHED if k in event}))


def verify_chain(path) -> tuple[bool, int, str]:
    """-> (ok, event_count, message). A missing or empty file is a valid empty chain."""
    prev, seq = GENESIS, 0
    try:
        with open(path, "rb") as fh:
            for lineno, raw in enumerate(fh, 1):
                if not raw.endswith(b"\n"):
                    return False, seq, f"line {lineno}: torn (unterminated) line"
                try:
                    ev = json.loads(raw)
                except ValueError:
                    return False, seq, f"line {lineno}: not JSON"
                if not isinstance(ev, dict) or set(ev) - set(_HASHED) - {"hash"}:
                    return False, seq, f"line {lineno}: unexpected shape"
                if ev.get("seq") != seq + 1:
                    return False, seq, f"line {lineno}: seq {ev.get('seq')!r}, expected {seq + 1}"
                if ev.get("prev_hash") != prev:
                    return False, seq, f"line {lineno}: prev_hash mismatch"
                if ev.get("hash") != event_hash(ev):
                    return False, seq, f"line {lineno}: hash mismatch"
                prev, seq = ev["hash"], seq + 1
    except FileNotFoundError:
        return True, 0, "no audit file yet"
    except OSError as exc:
        return False, seq, f"cannot read audit file: {type(exc).__name__}"
    return True, seq, "ok"


class FileAuditSink:
    """Append-only NDJSON file. Every append is fsynced; any failure raises AuditError."""

    def __init__(self, path, clock: Callable[[], datetime] = utc_now):
        self.path = str(path)
        self._clock = clock
        self._lock = threading.Lock()
        ok, count, message = verify_chain(self.path)
        if not ok:
            raise AuditError(f"audit chain is broken: {message}")
        self._seq = count
        self._prev = self._last_hash() if count else GENESIS

    def _last_hash(self) -> str:
        last = None
        for ev in self.events():
            last = ev
        return last["hash"] if last else GENESIS

    def events(self) -> Iterator[dict]:
        try:
            with open(self.path, "rb") as fh:
                for raw in fh:
                    yield json.loads(raw)
        except FileNotFoundError:
            return

    def append(self, actor: str, event: str, detail: dict, incident_id: str | None = None) -> dict:
        if not _ACTOR.fullmatch(actor) or not _EVENT.fullmatch(event) or not isinstance(detail, dict):
            raise AuditError("invalid audit event")
        if incident_id is not None and not _INCIDENT.fullmatch(incident_id):
            raise AuditError("invalid incident id")
        with self._lock:
            ev: dict = {"seq": self._seq + 1, "actor": actor, "event": event, "detail": detail,
                        "prev_hash": self._prev, "created_at": fmt(self._clock())}
            if incident_id is not None:
                ev["incident_id"] = incident_id
            try:
                ev["hash"] = event_hash(ev)
                line = json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
                try:
                    data = line.encode("utf-8")
                    if os.write(fd, data) != len(data):
                        raise OSError("short write")
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except (OSError, ValueError, TypeError) as exc:
                raise AuditError(f"audit write failed: {type(exc).__name__}") from exc
            self._seq, self._prev = ev["seq"], ev["hash"]
            return ev

    @property
    def last_seq(self) -> int:
        return self._seq
