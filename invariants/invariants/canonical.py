"""Canonical JSON, hashing and envelope signing (standard library only)."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

_ZERO_HASH = "sha256:" + "0" * 64


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, separators (',', ':'), UTF-8, NaN/Infinity rejected."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_tag(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def plan_hash(plan: dict) -> str:
    """Hash of the plan WITHOUT its plan_hash field."""
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    return sha256_tag(canonical_json(body))


def _envelope_body(envelope: dict) -> dict:
    return {k: v for k, v in envelope.items() if k != "signature"}


def sign_envelope(envelope_without_signature: dict, key: bytes) -> str:
    """HMAC-SHA256 (hex) over canonical_json of the envelope (any `signature` key is ignored)."""
    if not isinstance(key, (bytes, bytearray)) or len(key) == 0:
        raise ValueError("signing key must be non-empty bytes")
    return hmac.new(bytes(key), canonical_json(_envelope_body(envelope_without_signature)), hashlib.sha256).hexdigest()


def verify_envelope(envelope: dict, key: bytes) -> bool:
    """Constant-time check of envelope['signature']; any problem yields False."""
    try:
        sig = envelope.get("signature")
        if not isinstance(sig, str) or len(sig) != 64:
            return False
        expected = sign_envelope(envelope, key)
        return hmac.compare_digest(expected.encode("ascii"), sig.encode("ascii"))
    except Exception:
        return False
