"""HTTP over a unix domain socket (socketserver.UnixStreamServer), contracts/actuator.openapi.yaml."""
from __future__ import annotations

import json
import logging
import os
import socketserver
import stat
from http.server import BaseHTTPRequestHandler

import invariants as inv

from .core import Actuator, BadRequest

log = logging.getLogger("actuator.http")
MAX_BODY = 256 * 1024


def _strict_json(raw: bytes):
    def no_dupes(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate key")
            out[k] = v
        return out

    def no_const(name):
        raise ValueError("non-finite number")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=no_dupes, parse_constant=no_const)


class Handler(BaseHTTPRequestHandler):
    server: "ActuatorServer"
    timeout = 10                       # socket timeout: a stalled client cannot hold the process
    protocol_version = "HTTP/1.0"
    server_version = "cd-actuator"
    sys_version = ""

    def log_message(self, fmt, *args):  # unix-socket peers have no address; keep logs free of request data
        log.debug("%s", fmt % args if args else fmt)

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            try:
                reason = self.server.actuator.degraded_reason
            except Exception:
                reason = "error"
            return self._send(200, {"state": "degraded" if reason else "ok", "invariants_version": inv.__version__})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        route = {"/v1/validate": self.server.actuator.validate, "/v1/execute": self.server.actuator.execute}.get(self.path)
        if route is None:
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                raise ValueError
            body = _strict_json(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "bad request body"})
        try:
            self._send(200, route(body))
        except BadRequest as exc:
            self._send(400, {"error": str(exc)[:200]})
        except Exception:
            log.exception("unexpected error; failing closed")
            self._send(500, {"error": "internal error; nothing was executed"})

    def do_PUT(self):
        self._send(405, {"error": "method not allowed"})

    do_DELETE = do_PATCH = do_PUT


class ActuatorServer(socketserver.UnixStreamServer):
    """Single-threaded on purpose: requests are serialised, which keeps the state machine simple."""

    request_queue_size = 16

    def __init__(self, socket_path: str, actuator: Actuator):
        self.actuator, self.socket_path, self._bound = actuator, socket_path, False
        try:
            if stat.S_ISSOCK(os.lstat(socket_path).st_mode):
                os.unlink(socket_path)                 # stale socket from a previous run
        except FileNotFoundError:
            pass
        old = os.umask(0o117)                          # socket is created with mode 0660
        try:
            super().__init__(socket_path, Handler)
        finally:
            os.umask(old)
        self._bound = True
        os.chmod(socket_path, 0o660)

    def server_close(self):
        super().server_close()
        if self._bound:                                # never unlink a path we did not bind
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
