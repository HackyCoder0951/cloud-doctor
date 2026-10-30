"""Simulated worker: consumes jobs from the Redis list 'jobs' and records them in the app database."""
import json
import os
import threading
import time

import psycopg
import redis
from prometheus_client import Counter, Gauge

from app.common import json_body, log, metrics_route, serve

JOBS = Counter("jobs_processed_total", "Jobs finished", ["result"])
QUEUE = Gauge("queue_depth", "Length of the jobs list", ["queue"])
DEP = Gauge("cd_dependency_up", "Whether this service reaches its dependency", ["dependency"])

R = redis.Redis(host=os.environ["REDIS_HOST"], port=6379, socket_connect_timeout=1, socket_timeout=3)
DB = dict(host=os.environ["DB_HOST"], port=5432, dbname="postgres", user="postgres",
          password=os.environ["APP_DB_PASSWORD"], connect_timeout=1)
_state = {"redis": False, "db": False}


def ensure_table():
    with psycopg.connect(**DB) as conn:
        conn.execute("create table if not exists jobs_done (id text primary key, done_at timestamptz default now())")


def record(job_id):
    with psycopg.connect(**DB) as conn:
        conn.execute("insert into jobs_done (id) values (%s) on conflict do nothing", (job_id,))


def clear_queue_metric():
    try:
        QUEUE.remove("jobs")  # the series disappears while Redis is unreachable (see telemetry contract)
    except KeyError:
        pass


def loop():
    while True:
        try:
            item = R.brpop("jobs", timeout=1)
            _state["redis"] = True
            DEP.labels(dependency="redis").set(1)
            QUEUE.labels(queue="jobs").set(R.llen("jobs"))
        except Exception as err:  # noqa: BLE001
            if _state["redis"] or not _state.get("logged"):
                log("error", "redis connection failed", error=str(err)[:120])
                _state["logged"] = True
            _state["redis"] = False
            DEP.labels(dependency="redis").set(0)
            clear_queue_metric()
            time.sleep(1)
            continue
        if not item:
            continue
        try:
            job = json.loads(item[1])
            record(job["id"])
            _state["db"] = True
            DEP.labels(dependency="app-db").set(1)
            JOBS.labels(result="ok").inc()
        except Exception as err:  # noqa: BLE001
            _state["db"] = False
            DEP.labels(dependency="app-db").set(0)
            JOBS.labels(result="error").inc()
            log("error", "job failed", error=type(err).__name__)


def readyz(_query):
    ok = _state["redis"]
    return json_body({"redis": _state["redis"], "app-db": _state["db"]}, status=200 if ok else 503)


if __name__ == "__main__":
    log("info", "worker starting")
    for _ in range(30):
        try:
            ensure_table()
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    threading.Thread(target=loop, daemon=True).start()
    serve(8001, {"/healthz": lambda q: json_body({"status": "alive"}), "/readyz": readyz, "/metrics": metrics_route})
