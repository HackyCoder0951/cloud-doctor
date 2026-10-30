"""Read-mostly client for the public Cloud Doctor API (contracts/openapi.yaml).

The client only ever sends identifiers, query parameters and (optionally) an operator approval. Ground truth,
scenario ids, run ids and fault parameters are never passed to it.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import CookieJar
from typing import Any, Protocol


class ApiError(RuntimeError):
    def __init__(self, endpoint: str, status: int | None, message: str) -> None:
        super().__init__(f"{endpoint}: {status}: {message}")
        self.endpoint, self.status = endpoint, status


class CloudDoctorApi(Protocol):
    def list_services(self) -> list[dict]: ...
    def list_incidents(self, limit: int = 200) -> list[dict]: ...
    def get_incident(self, incident_id: str) -> dict: ...
    def get_timeline(self, incident_id: str) -> list[dict]: ...
    def get_evidence(self, incident_id: str) -> list[dict]: ...
    def get_diagnosis(self, incident_id: str) -> dict | None: ...
    def get_remediation(self, incident_id: str) -> dict: ...
    def get_verification(self, incident_id: str) -> list[dict]: ...
    def get_report(self, incident_id: str) -> dict | None: ...
    def list_audit(self, incident_id: str | None = None, after_seq: int = 0, limit: int = 500) -> dict: ...
    def approve_plan(self, incident_id: str, plan_id: str, plan_hash: str, reason: str) -> dict: ...


class HttpApiClient:
    """urllib implementation. `base_url` is CD_API_URL and includes the /api/v1 prefix."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0,
                 opener: urllib.request.OpenerDirector | None = None) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("CD_API_URL must be http(s)")
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self._logged_in = token is None

    def _login(self) -> None:
        self._send("POST", "/auth/login", None, {"token": self._token}, expect_json=False)
        self._logged_in = True

    def _send(self, method: str, path: str, params: dict[str, Any] | None, body: dict | None,
              expect_json: bool = True, headers: dict[str, str] | None = None) -> Any:
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        hdrs = {"Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise ApiError(path, e.code, "http error") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError(path, None, type(e).__name__) from None
        if not expect_json or not raw:
            return None
        return json.loads(raw)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._logged_in:
            self._login()
        return self._send("GET", path, params, None)

    def _get_or_none(self, path: str) -> Any:
        try:
            return self._get(path)
        except ApiError as e:
            if e.status == 404:
                return None
            raise

    def list_services(self) -> list[dict]:
        return self._get("/services")

    def list_incidents(self, limit: int = 200) -> list[dict]:
        return self._get("/incidents", {"limit": limit})

    def get_incident(self, incident_id: str) -> dict:
        return self._get(f"/incidents/{incident_id}")

    def get_timeline(self, incident_id: str) -> list[dict]:
        return self._get(f"/incidents/{incident_id}/timeline")

    def get_evidence(self, incident_id: str) -> list[dict]:
        return self._get(f"/incidents/{incident_id}/evidence")

    def get_diagnosis(self, incident_id: str) -> dict | None:
        return self._get_or_none(f"/incidents/{incident_id}/diagnosis")

    def get_remediation(self, incident_id: str) -> dict:
        return self._get(f"/incidents/{incident_id}/remediation")

    def get_verification(self, incident_id: str) -> list[dict]:
        return self._get(f"/incidents/{incident_id}/verification")

    def get_report(self, incident_id: str) -> dict | None:
        return self._get_or_none(f"/incidents/{incident_id}/report")

    def list_audit(self, incident_id: str | None = None, after_seq: int = 0, limit: int = 500) -> dict:
        params: dict[str, Any] = {"after_seq": after_seq, "limit": limit}
        if incident_id:
            params["incident"] = incident_id
        return self._get("/audit", params)

    def approve_plan(self, incident_id: str, plan_id: str, plan_hash: str, reason: str) -> dict:
        if not self._logged_in:
            self._login()
        key = uuid.uuid4().hex
        return self._send("POST", f"/incidents/{incident_id}/remediation/plans/{plan_id}/approve", None,
                          {"plan_hash": plan_hash, "reason": reason}, headers={"Idempotency-Key": key})
