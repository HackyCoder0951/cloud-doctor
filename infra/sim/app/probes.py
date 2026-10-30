"""Probe sidecar: exposes cd_service_up for redis (port 9121) and app-db (port 9187).

Redis is probed with a real PING; the database with a TCP connect. It carries no sandbox label,
so the actuator can never act on it.
"""
import os
import socket
import threading
import time

from app.common import log, serve

REDIS_HOST = os.environ["REDIS_HOST"]
DB_HOST = os.environ["DB_HOST"]
STATE = {"redis": 0, "app-db": 0}


def probe_redis():
    try:
        with socket.create_connection((REDIS_HOST, 6379), timeout=1) as s:
            s.settimeout(1)
            s.sendall(b"*1\r\n$4\r\nPING\r\n")
            return 1 if s.recv(16).startswith(b"+PONG") else 0
    except OSError:
        return 0


def probe_db():
    try:
        with socket.create_connection((DB_HOST, 5432), timeout=1):
            return 1
    except OSError:
        return 0


def loop():
    while True:
        STATE["redis"], STATE["app-db"] = probe_redis(), probe_db()
        time.sleep(2)


def exposition(name):
    def handler(_query):
        body = f"# HELP cd_service_up Probe result (1 reachable, 0 not)\n# TYPE cd_service_up gauge\ncd_service_up {STATE[name]}\n"
        return 200, "text/plain; version=0.0.4", body.encode()
    return handler


if __name__ == "__main__":
    log("info", "probes starting")
    threading.Thread(target=loop, daemon=True).start()
    serve(9187, {"/metrics": exposition("app-db")}, daemon=True)
    serve(9121, {"/metrics": exposition("redis")})
