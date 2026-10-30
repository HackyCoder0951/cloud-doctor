"""Fail-closed OPA REST client. ANY problem is a deny: connection error, timeout, non-200,
malformed JSON, HTTP 200 without a `result` key (undefined decision), a result of the wrong shape,
and a bundle that is not active, not signed or stale."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Protocol

MAX_RESPONSE_BYTES = 1024 * 1024
_RESULTS = ("allow", "allow_with_approval", "deny")
_PATH = re.compile(r"[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*")


class TransportError(Exception):
    """Connection refused, DNS failure, timeout, reset, oversized or otherwise unusable response."""


class Transport(Protocol):
    def request(self, method: str, url: str, body: Optional[bytes], timeout: float) -> tuple[int, bytes]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class UrllibTransport:
    """urllib only; proxies from the environment are ignored and redirects are never followed."""

    def __init__(self):
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def request(self, method, url, body, timeout):
        req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return resp.status, self._read(resp)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, self._read(exc)
            finally:
                exc.close()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError(type(exc).__name__) from exc

    @staticmethod
    def _read(resp) -> bytes:
        data = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise TransportError("response too large")
        return data


@dataclass(frozen=True)
class BundleStatus:
    active: bool
    signed: bool
    revision: Optional[str] = None
    last_activated: Optional[datetime] = None


class BundleHealth(Protocol):
    """Reports whether the policy bundle OPA serves is active, signed and fresh."""

    def status(self) -> BundleStatus: ...


class StaticBundleHealth:
    def __init__(self, status: BundleStatus):
        self._status = status

    def status(self) -> BundleStatus:
        return self._status


class OpaHealthEndpoint:
    """Best-effort implementation over OPA's `GET /health?bundles`: 200 means the bundle is active.

    Signature state cannot be read from that endpoint; `bundle_signed` is the OPERATOR'S declaration
    that OPA is configured with a `signing` block (OPA then refuses to activate an unsigned or
    badly signed bundle). Treat it as configuration, not as verification by this client."""

    def __init__(self, base_url: str, *, bundle_signed: bool, revision: Optional[str] = None,
                 transport: Optional[Transport] = None, timeout: float = 1.0):
        self._url = base_url.rstrip("/") + "/health?bundles"
        self._signed, self._revision = bundle_signed, revision
        self._transport, self._timeout = transport or UrllibTransport(), timeout

    def status(self) -> BundleStatus:
        code, _ = self._transport.request("GET", self._url, None, self._timeout)
        return BundleStatus(active=code == 200, signed=self._signed, revision=self._revision,
                            last_activated=datetime.now(timezone.utc) if code == 200 else None)


def _problem(code: str, why: str) -> dict:
    return {"result": "deny", "rule_ids": [code], "bundle_signed": False, "problem": why}


class Layer2Client:
    def __init__(self, base_url: str, bundle_health: BundleHealth, *, decision_path: str = "cloud_doctor/policy/decision",
                 timeout: float = 1.5, transport: Optional[Transport] = None,
                 max_bundle_age_seconds: Optional[float] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.query or parts.fragment:
            raise ValueError("base_url must be a plain http(s) URL")
        if not _PATH.fullmatch(decision_path):
            raise ValueError("invalid decision path")
        if bundle_health is None:
            raise ValueError("a bundle health check is required")
        self._url = f"{base_url.rstrip('/')}/v1/data/{decision_path}"
        self._health, self._timeout = bundle_health, float(timeout)
        self._transport = transport or UrllibTransport()
        self._max_age = None if max_bundle_age_seconds is None else timedelta(seconds=max_bundle_age_seconds)
        self._clock = clock

    def evaluate(self, opa_input: dict) -> dict:
        """Never raises. Returns {"result","rule_ids","bundle_revision","bundle_signed"} for compose_decision,
        or a deny that carries a `problem` description."""
        try:
            return self._evaluate(opa_input)
        except Exception as exc:  # fail closed on anything unforeseen
            return _problem("L2-UNAVAILABLE", f"unexpected error: {type(exc).__name__}")

    def _evaluate(self, opa_input: dict) -> dict:
        try:
            st = self._health.status()
        except Exception as exc:
            return _problem("L2-UNAVAILABLE", f"bundle health check failed: {type(exc).__name__}")
        if not isinstance(st, BundleStatus) or not st.active:
            return _problem("L2-UNAVAILABLE", "bundle is not active")
        if st.signed is not True:
            return _problem("L2-UNSIGNED-BUNDLE", "bundle is not signed")
        if self._max_age is not None:
            if st.last_activated is None or self._clock() - st.last_activated > self._max_age:
                return _problem("L2-BUNDLE-STALE", "bundle activation is older than the allowed age")
        try:
            body = json.dumps({"input": opa_input}, allow_nan=False).encode()
        except (TypeError, ValueError):
            return _problem("L2-MALFORMED", "input is not serialisable")
        try:
            code, raw = self._transport.request("POST", self._url, body, self._timeout)
        except TransportError as exc:
            return _problem("L2-UNAVAILABLE", f"OPA unreachable: {exc}")
        if code != 200:
            return _problem("L2-HTTP-ERROR", f"OPA answered HTTP {code}")
        try:
            doc = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return _problem("L2-MALFORMED", "OPA response is not JSON")
        if not isinstance(doc, dict):
            return _problem("L2-MALFORMED", "OPA response is not an object")
        if "result" not in doc:
            return _problem("L2-UNDEFINED", "HTTP 200 without a result key: undefined decision")
        res = doc["result"]
        if (not isinstance(res, dict) or res.get("result") not in _RESULTS or not isinstance(res.get("rule_ids"), list)
                or not all(isinstance(r, str) and 0 < len(r) <= 64 for r in res["rule_ids"])):
            return _problem("L2-INVALID-RESULT", "result has an unexpected shape")
        out = {"result": res["result"], "rule_ids": list(res["rule_ids"]), "bundle_signed": True}
        if isinstance(st.revision, str):
            out["bundle_revision"] = st.revision
        return out
