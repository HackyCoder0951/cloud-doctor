"""Expected-state registry: declared maintenance / intentional faults with owner, reason and expiry.

A declaration prevents false incidents without hiding data: the detector still records the observation
(suppressed alert + background timeline note). Expired declarations stop applying immediately.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Declaration:
    service: str
    owner: str
    reason: str
    declared_at: datetime
    expires_at: datetime
    kind: str = "down"  # the only kind supported: the service is expected to be down / absent
    suppress_dependents: bool = False


class ExpectedStateRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[Declaration] = []

    def declare(self, service: str, owner: str, reason: str, declared_at: datetime, expires_at: datetime,
                suppress_dependents: bool = False) -> Declaration:
        if not owner.strip() or not reason.strip():
            raise ValueError("owner and reason are required")
        if expires_at <= declared_at:
            raise ValueError("expiry must be after the declaration time (declarations are never open-ended)")
        d = Declaration(service, owner.strip(), reason.strip(), declared_at, expires_at, "down", suppress_dependents)
        with self._lock:
            self._items.append(d)
        return d

    def active(self, service: str, now: datetime) -> Declaration | None:
        with self._lock:
            for d in reversed(self._items):
                if d.service == service and d.declared_at <= now < d.expires_at:
                    return d
        return None

    def active_for_dependency(self, dependencies: list[str], now: datetime) -> Declaration | None:
        for dep in dependencies:
            d = self.active(dep, now)
            if d and d.suppress_dependents:
                return d
        return None

    def all(self) -> list[Declaration]:
        with self._lock:
            return list(self._items)
