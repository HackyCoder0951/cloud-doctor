"""Shared helpers for the simulated services: JSON logging and a tiny HTTP server.

Telemetry contract: contracts/telemetry.md. Log text produced here is UNTRUSTED downstream.
"""
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from prometheus_client.core import GaugeMetricFamily

SERVICE = os.environ.get("SERVICE_NAME", "unknown")
_LOG_FILE = os.environ.get("LOG_FILE")
_lock = threading.Lock()
_fh = open(_LOG_FILE, "a", buffering=1) if _LOG_FILE else None


def log(level, msg, **fields):
    """Write one JSON log line to stdout (and the shared log volume when configured)."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
           "level": level, "service": SERVICE, "msg": msg}
    rec.update(fields)
    line = json.dumps(rec, separators=(",", ":"))
    with _lock:
        print(line, flush=True)
        if _fh:
            _fh.write(line + "\n")


def serve(port, routes, daemon=False):
    """Serve routes: {path: handler(query) -> (status, content_type, bytes)} on 0.0.0.0:port."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            path, _, query = self.path.partition("?")
            handler = routes.get(path)
            if handler is None:
                status, ctype, body = 404, "application/json", b'{"error":"not found"}'
            else:
                try:
                    status, ctype, body = handler(query)
                except Exception as err:  # noqa: BLE001 - never leak internals to the client
                    log("error", "handler failed", error=type(err).__name__)
                    status, ctype, body = 500, "application/json", b'{"error":"internal"}'
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence default access log
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if not daemon:
        thread.join()
    return server


class _FsCollector:
    """Filesystem size and usage of the shared log volume, read at scrape time (statvfs)."""

    def __init__(self, mount):
        self.mount = mount

    def collect(self):
        try:
            st = os.statvfs(self.mount)
        except OSError:
            return  # series absent if the mount cannot be read
        size, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        for name, doc, val in (("cd_fs_size_bytes", "Filesystem size", size), ("cd_fs_used_bytes", "Filesystem bytes in use", size - free)):
            g = GaugeMetricFamily(name, doc, labels=["mount"])
            g.add_metric([self.mount], float(val))
            yield g


def register_fs_metrics(mount="/logs"):
    REGISTRY.register(_FsCollector(mount))


def metrics_route(_query=""):
    return 200, CONTENT_TYPE_LATEST, generate_latest()


def json_body(obj, status=200):
    return status, "application/json", json.dumps(obj).encode()
