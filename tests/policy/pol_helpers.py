import json
from datetime import datetime, timezone

from cd_policy import BundleStatus, Layer2Client, StaticBundleHealth, TransportError

NOW = datetime(2026, 11, 2, 9, 1, 0, tzinfo=timezone.utc)
GOOD = BundleStatus(active=True, signed=True, revision="r1", last_activated=NOW)


class FakeOpa:
    """Python test double of OPA's REST data API (no network)."""

    def __init__(self, reply=None):
        self.reply = reply if reply is not None else (200, json.dumps({"result": {"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"]}}).encode())
        self.requests = []

    def request(self, method, url, body, timeout):
        self.requests.append((method, url, body, timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        if callable(self.reply):
            return self.reply()
        return self.reply


def client(opa=None, status=GOOD, **kw):
    opa = opa or FakeOpa()
    kw.setdefault("clock", lambda: NOW)
    return Layer2Client("http://127.0.0.1:8181", StaticBundleHealth(status), transport=opa, **kw), opa


def reply(result):
    return (200, json.dumps({"result": result}).encode())
