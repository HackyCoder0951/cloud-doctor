"""Probe sidecar: exposes cd_service_up for redis (port 9121) and app-db (port 9187).

Redis is probed with a real PING; the database with a TCP connect. The redis probe also reports the length of
the `jobs` list as cd_queue_length, measured here so the backlog stays visible while the worker is dead (the
worker's own queue_depth series disappears with it). It carries no sandbox label, so the actuator can never act on it.
"""
import os
import socket
import threading
import time

from app.common import log, serve

REDIS_HOST = os.environ["REDIS_HOST"]
DB_HOST = os.environ["DB_HOST"]
STATE = {"redis": 0, "app-db": 0, "queue_length": None}  # queue_length None = Redis unreachable (series absent)


def probe_redis():
    """Returns (up, length of the `jobs` list or None). PING and LLEN share one connection."""
    try:
        with socket.create_connection((REDIS_HOST, 6379), timeout=1) as s:
            s.settimeout(1)
            s.sendall(b"*1\r\n$4\r\nPING\r\n*2\r\n$4\r\nLLEN\r\n$4\r\njobs\r\n")
            buf = b""
            while buf.count(b"\r\n") < 2:
                chunk = s.recv(64)
                if not chunk:
                    break
                buf += chunk
            lines = buf.split(b"\r\n")
            if not lines[0].startswith(b"+PONG"):
                return 0, None
            length = int(lines[1][1:]) if len(lines) > 1 and lines[1].startswith(b":") else None
            return 1, length
    except (OSError, ValueError):
        return 0, None


def probe_db():
    try:
        with socket.create_connection((DB_HOST, 5432), timeout=1):
            return 1
    except OSError:
        return 0


def loop():
    while True:
        STATE["redis"], STATE["queue_length"] = probe_redis()
        STATE["app-db"] = probe_db()
        time.sleep(2)


def exposition(name):
    def handler(_query):
        body = f"# HELP cd_service_up Probe result (1 reachable, 0 not)\n# TYPE cd_service_up gauge\ncd_service_up {STATE[name]}\n"
        if name == "redis" and STATE["queue_length"] is not None:
            body += ('# HELP cd_queue_length Length of the Redis list `jobs`, measured by the probe (absent while Redis is unreachable)\n'
                     f'# TYPE cd_queue_length gauge\ncd_queue_length{{queue="jobs"}} {STATE["queue_length"]}\n')
        return 200, "text/plain; version=0.0.4", body.encode()
    return handler


if __name__ == "__main__":
    log("info", "probes starting")
    threading.Thread(target=loop, daemon=True).start()
    serve(9187, {"/metrics": exposition("app-db")}, daemon=True)
    serve(9121, {"/metrics": exposition("redis")})
