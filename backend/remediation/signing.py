"""Request signing: HMAC-SHA256 over the canonical JSON of the envelope, keyed from the file CD_SIGNING_KEY_FILE.

The key is read from a file only (never an environment value or the repo). A missing, unreadable, empty or group/world
readable key file is an error: callers must fail closed (no signature => no execution).
"""
from __future__ import annotations

import os
import secrets
import stat
from datetime import datetime, timedelta

from backend import policy_adapter as pa
from backend.domain.clock import iso


class SigningUnavailable(RuntimeError):
    pass


def load_key(path: str | None = None) -> bytes:
    p = path or os.environ.get("CD_SIGNING_KEY_FILE")
    if not p:
        raise SigningUnavailable("CD_SIGNING_KEY_FILE is not set")
    try:
        st = os.stat(p)
        if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SigningUnavailable("signing key file must not be group/world accessible (mode 0600)")
        key = open(p, "rb").read().strip()
    except OSError as exc:
        raise SigningUnavailable(f"signing key file unreadable: {type(exc).__name__}") from exc
    if len(key) < 16:
        raise SigningUnavailable("signing key is too short")
    return key


def sign_plan(plan: dict, key: bytes, now: datetime, ttl_seconds: int = 120, key_id: str = "mvp-1", approval: dict | None = None,
              nonce: str | None = None) -> dict:
    """Build the signed_plan.json envelope. The signature covers {plan, key_id, issued_at, expires_at, nonce, approval}."""
    env: dict = {"plan": plan, "key_id": key_id, "issued_at": iso(now), "expires_at": iso(now + timedelta(seconds=ttl_seconds)),
                 "nonce": nonce or secrets.token_urlsafe(18)}
    if approval:
        env["approval"] = approval
    env["signature"] = pa.sign_envelope({k: v for k, v in env.items() if k != "signature"}, key)
    return env
