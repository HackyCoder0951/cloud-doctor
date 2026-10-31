"""The real urllib transport against a loopback fake OPA (127.0.0.1 only, no external network)."""
import http.server
import json
import threading
import time

import pytest

from cd_policy import Layer2Client, StaticBundleHealth, TransportError, UrllibTransport
from pol_helpers import GOOD


class Handler(http.server.BaseHTTPRequestHandler):
    script = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        kind = self.script.get(self.path.rsplit("/", 1)[-1], "ok")
        if kind == "slow":
            time.sleep(1.5)
        if kind == "redirect":
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:1/evil")
            self.end_headers()
            return
        code, body = {
            "ok": (200, {"result": {"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"]}}),
            "undefined": (200, {}), "err": (500, {"code": "internal_error"}), "slow": (200, {"result": {}}),
        }.get(kind, (200, {}))
        if kind == "huge":
            code, body = 200, {"result": "x" * (2 * 1024 * 1024)}
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def opa_url():
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except OSError as exc:  # pragma: no cover
        pytest.skip(f"cannot bind loopback: {exc}")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def make(url, path="ok", timeout=0.5):
    return Layer2Client(url, StaticBundleHealth(GOOD), decision_path=f"cloud_doctor/policy/{path}", timeout=timeout)


def test_real_http_allow(opa_url):
    assert make(opa_url).evaluate({"a": 1})["result"] == "allow"


@pytest.mark.parametrize("path,code", [("undefined", "L2-UNDEFINED"), ("err", "L2-HTTP-ERROR"), ("slow", "L2-UNAVAILABLE"),
                                       ("redirect", "L2-HTTP-ERROR"), ("huge", "L2-UNAVAILABLE")])
def test_real_http_problems_deny(opa_url, path, code):
    Handler.script = {path: path}
    out = make(opa_url, path).evaluate({"a": 1})
    assert out["result"] == "deny" and out["rule_ids"] == [code], out


def test_connection_refused_denies():
    out = make("http://127.0.0.1:1").evaluate({"a": 1})
    assert out["result"] == "deny" and out["rule_ids"] == ["L2-UNAVAILABLE"]


def test_environment_proxies_are_ignored(opa_url, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    assert make(opa_url).evaluate({"a": 1})["result"] == "allow"


def test_transport_wraps_errors():
    with pytest.raises(TransportError):
        UrllibTransport().request("POST", "http://127.0.0.1:1/x", b"{}", 0.3)
