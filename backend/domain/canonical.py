"""Canonical JSON and hashing exactly as the frozen contracts describe.

Canonical JSON = sorted keys, separators (',', ':'), UTF-8, NaN/Infinity rejected.
Hashes are tagged ``sha256:<64 hex>``. The same recipe is used by the `invariants` package
(streams.md); this module is the local helper used until/unless that package is installed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

ZERO_HASH = "sha256:" + "0" * 64


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_tag(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def payload_hash(payload: dict) -> str:
    """Hash of the canonical JSON of an evidence payload; computed BEFORE insert, never from stored JSONB."""
    return sha256_tag(canonical_json(payload))


def plan_hash(plan: dict) -> str:
    """sha256 over the canonical JSON of the plan with its ``plan_hash`` field removed."""
    return sha256_tag(canonical_json({k: v for k, v in plan.items() if k != "plan_hash"}))


def strip_nul(obj: Any) -> Any:
    """Recursively remove NUL characters from strings (and dict keys); PostgreSQL JSONB rejects \\u0000."""
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, list):
        return [strip_nul(v) for v in obj]
    if isinstance(obj, dict):
        return {strip_nul(k): strip_nul(v) for k, v in obj.items()}
    return obj
