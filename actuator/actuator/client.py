"""Small test/ops client for the actuator's unix-socket API, plus a helper to build signed plans."""
from __future__ import annotations

import http.client
import json
import socket
import sys
from datetime import datetime, timedelta, timezone

import invariants as inv


class ActuatorError(Exception):
    def __init__(self, status: int, body):
        super().__init__(f"actuator returned HTTP {status}")
        self.status, self.body = status, body


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


class ActuatorClient:
    def __init__(self, socket_path: str, timeout: float = 40.0):
        self.socket_path, self.timeout = socket_path, timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        conn = _UnixConnection(self.socket_path, self.timeout)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = json.loads(resp.read() or b"null")
            if resp.status != 200:
                raise ActuatorError(resp.status, data)
            return data
        finally:
            conn.close()

    def healthz(self) -> dict:
        return self._call("GET", "/healthz")

    def validate(self, signed_plan: dict) -> dict:
        return self._call("POST", "/v1/validate", {"signed_plan": signed_plan})

    def execute(self, signed_plan: dict, idempotency_key: str) -> dict:
        return self._call("POST", "/v1/execute", {"signed_plan": signed_plan, "idempotency_key": idempotency_key})


def build_signed_plan(plan: dict, key: bytes, *, key_id: str = "mvp-1", nonce: str,
                      now: datetime | None = None, ttl_seconds: int = 120, approval: dict | None = None) -> dict:
    """Sign a plan the way the control plane must (see docs/dev/policy/INTEGRATION.md)."""
    now = now or datetime.now(timezone.utc)
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    env = {"plan": plan, "key_id": key_id, "issued_at": fmt(now),
           "expires_at": fmt(now + timedelta(seconds=ttl_seconds)), "nonce": nonce}
    if approval is not None:
        env["approval"] = approval
    env["signature"] = inv.sign_envelope(env, key)
    return env


def main(argv=None) -> int:  # python -m actuator.client --socket PATH healthz|validate FILE|execute FILE KEY
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 3 and argv[0] == "--socket":
        client, rest = ActuatorClient(argv[1]), argv[2:]
    else:
        import os
        client, rest = ActuatorClient(os.environ["CD_ACTUATOR_SOCKET"]), argv
    if rest[:1] == ["healthz"]:
        out = client.healthz()
    elif rest[:1] == ["validate"] and len(rest) == 2:
        out = client.validate(json.load(open(rest[1])))
    elif rest[:1] == ["execute"] and len(rest) == 3:
        out = client.execute(json.load(open(rest[1])), rest[2])
    else:
        print("usage: python -m actuator.client [--socket PATH] healthz | validate FILE | execute FILE IDEMPOTENCY_KEY", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
