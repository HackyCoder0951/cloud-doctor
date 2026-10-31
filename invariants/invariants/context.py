"""PolicyContext and ValidationResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .catalog import Catalog

MAX_ATTEMPTS_DEFAULT = 2
COOLDOWN_SECONDS_DEFAULT = 20.0


@dataclass
class PolicyContext:
    """Everything Layer 1 needs from the outside world. Missing inputs deny (fail closed)."""

    catalog: Catalog
    now: datetime
    attempts_used: Optional[Callable[[str, str, str], int]] = None
    last_attempt_at: Optional[Callable[[str, str, str], Optional[datetime]]] = None
    circuit_open: Optional[Callable[[str], bool]] = None
    known_evidence_ids: Optional[set] = None
    diagnosis_validated: bool = False
    top_cause_service: Optional[str] = None
    approval: Optional[dict] = None
    container_labels: Optional[Callable[[str], dict]] = None
    # Extensions (defaults are fail-closed):
    down_services: Optional[set] = None   # None => the top cause is assumed to be down (I-07)
    max_attempts: int = MAX_ATTEMPTS_DEFAULT
    cooldown_seconds: float = COOLDOWN_SECONDS_DEFAULT


@dataclass
class ValidationResult:
    ok: bool
    rule_ids: list[str] = field(default_factory=list)       # violated rules (empty when ok)
    reasons: list[str] = field(default_factory=list)
    requires_approval: bool = False                          # effective risk is medium
    passed_rule_ids: list[str] = field(default_factory=list)
    pending_approval: bool = False                           # only failure: no valid approval yet
    plan_id: Optional[str] = None
    plan_hash: Optional[str] = None
