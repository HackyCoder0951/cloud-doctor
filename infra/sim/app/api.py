"""Simulated API service: /work uses Redis and enqueues a job; /readyz checks Redis and the database."""
import json
import os
import threading
import time
import uuid

import psycopg
import redis
from prometheus_client import Counter, Gauge, Histogram

from app.common import json_body, log, metrics_route, serve

REQS = Counter("http_requests_total", "Requests handled", ["route", "method", "status"])
LAT = Histogram("http_request_duration_seconds", "Request latency", ["route"],
                buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5))
DEP = Gauge("cd_dependency_up", "Whether this service reaches its dependency", ["dependency"])
Gauge("build_info", "Deployed version", ["version"]).labels(version=os.environ.get("APP_VERSION", "1.0.0")).set(1)

R = redis.Redis(host=os.environ["REDIS_HOST"], port=6379, socket_connect_timeout=1, socket_timeout=1)
DB = dict(host=os.environ["DB_HOST"], port=5432, dbname="postgres", user="postgres",
          password=os.environ["APP_DB_PASSWORD"], connect_timeout=1)


def redis_ok():
    try:
        R.ping()
        DEP.labels(dependency="redis").set(1)
        return True
    except Exception:  # noqa: BLE001
        DEP.labels(dependency="redis").set(0)
        return False


def db_ok():
    try:
        with psycopg.connect(**DB) as conn:
            conn.execute("select 1")
        DEP.labels(dependency="app-db").set(1)
        return True
    except Exception:  # noqa: BLE001
        DEP.labels(dependency="app-db").set(0)
        return False


def observed(route, fn):
    def handler(query):
        started = time.time()
        status = 500
        try:
            status, ctype, body = fn(query)
            return status, ctype, body
        finally:
            LAT.labels(route=route).observe(time.time() - started)
            REQS.labels(route=route, method="GET", status=str(status)).inc()
    return handler


def work(_query):
    rid = uuid.uuid4().hex[:12]
    try:
        R.incr("hits")
        R.lpush("jobs", json.dumps({"id": rid, "t": time.time()}))
        DEP.labels(dependency="redis").set(1)
        return json_body({"ok": True, "id": rid})
    except Exception as err:  # noqa: BLE001
        DEP.labels(dependency="redis").set(0)
        log("error", "redis connection failed", request_id=rid, error=str(err)[:120])
        return json_body({"ok": False, "id": rid}, status=503)


def readyz(_query):
    r_ok, d_ok = redis_ok(), db_ok()
    return json_body({"redis": r_ok, "app-db": d_ok}, status=200 if (r_ok and d_ok) else 503)


def background_dependency_check():
    while True:
        redis_ok()
        db_ok()
        time.sleep(2)


if __name__ == "__main__":
    log("info", "api starting", version=os.environ.get("APP_VERSION", "1.0.0"))
    threading.Thread(target=background_dependency_check, daemon=True).start()
    serve(8000, {
        "/healthz": observed("/healthz", lambda q: json_body({"status": "alive"})),
        "/readyz": observed("/readyz", readyz),
        "/work": observed("/work", work),
        "/metrics": metrics_route,
    })
