"""Probe sidecar: exposes cd_service_up for redis (port 9121) and app-db (port 9187).

Redis is probed with a real PING; the database with a TCP connect. The redis probe also reports the length of
the `jobs` list as cd_queue_length, measured here so the backlog stays visible while the worker is dead (the
worker's own queue_depth series disappears with it). The database probe also reports server-side connection counts
(total, limit, per client application_name) and the time of a `select 1` measured from inside the sandbox network.
It carries no sandbox label, so the actuator can never act on it.
"""
import os
import socket
import threading
import time

import psycopg

from app.common import log, serve

REDIS_HOST = os.environ["REDIS_HOST"]
DB_HOST = os.environ["DB_HOST"]
DB_PASSWORD = os.environ.get("APP_DB_PASSWORD", "")
# queue_length / db_stats / db_refused None = the source is unreachable: the series are absent, never reported as 0
STATE = {"redis": 0, "app-db": 0, "queue_length": None, "db_stats": None, "db_refused": None}


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
    """Returns (up, stats or None, refused or None). Up is a TCP connect; stats come from pg_stat_activity over one short
    connection. refused is 1 when the database rejected that connection with `too many clients` (the connection limit is
    reached, so there are no stats exactly when they matter), 0 when it was accepted, None when the port does not answer."""
    try:
        with socket.create_connection((DB_HOST, 5432), timeout=1):
            pass
    except OSError:
        return 0, None, None
    try:
        with psycopg.connect(host=DB_HOST, port=5432, dbname="postgres", user="postgres", password=DB_PASSWORD,
                             connect_timeout=2, application_name="cd-probe") as conn:
            t0 = time.monotonic()
            conn.execute("select 1")
            took = time.monotonic() - t0
            limit = int(conn.execute("show max_connections").fetchone()[0])
            rows = conn.execute("select coalesce(nullif(application_name, ''), 'unknown'), count(*) from pg_stat_activity "
                                "where backend_type = 'client backend' and pid <> pg_backend_pid() group by 1").fetchall()
            return 1, {"duration": took, "limit": limit, "by_client": {name: int(n) for name, n in rows}}, 0
    except psycopg.OperationalError as exc:
        # a refused connection carries no SQLSTATE client-side (it is a plain OperationalError), so match the server message
        return 1, None, 1 if "too many clients" in str(exc) else 0
    except Exception:  # noqa: BLE001 - the port answers but the database does not: up, with no stats
        return 1, None, 0


def loop():
    while True:
        STATE["redis"], STATE["queue_length"] = probe_redis()
        STATE["app-db"], STATE["db_stats"], STATE["db_refused"] = probe_db()
        time.sleep(2)


def exposition(name):
    def handler(_query):
        body = f"# HELP cd_service_up Probe result (1 reachable, 0 not)\n# TYPE cd_service_up gauge\ncd_service_up {STATE[name]}\n"
        if name == "redis" and STATE["queue_length"] is not None:
            body += ('# HELP cd_queue_length Length of the Redis list `jobs`, measured by the probe (absent while Redis is unreachable)\n'
                     f'# TYPE cd_queue_length gauge\ncd_queue_length{{queue="jobs"}} {STATE["queue_length"]}\n')
        if name == "app-db" and STATE["db_refused"] is not None:
            body += ("# HELP cd_db_connection_refused 1 when the database refused the probe with too many clients (connection limit reached)\n"
                     f"# TYPE cd_db_connection_refused gauge\ncd_db_connection_refused {STATE['db_refused']}\n")
        stats = STATE["db_stats"]
        if name == "app-db" and stats is not None:
            by = "".join(f'cd_db_connections_by_client{{client="{c}"}} {n}\n' for c, n in sorted(stats["by_client"].items()))
            body += ("# HELP cd_db_connections Client connections to the database (excluding the probe)\n# TYPE cd_db_connections gauge\n"
                     f"cd_db_connections {sum(stats['by_client'].values())}\n"
                     "# HELP cd_db_max_connections Configured max_connections\n# TYPE cd_db_max_connections gauge\n"
                     f"cd_db_max_connections {stats['limit']}\n"
                     "# HELP cd_db_connections_by_client Client connections by application_name\n# TYPE cd_db_connections_by_client gauge\n"
                     + by +
                     "# HELP cd_db_probe_duration_seconds Server round-trip of `select 1` measured by the probe, not through any fault proxy\n"
                     f"# TYPE cd_db_probe_duration_seconds gauge\ncd_db_probe_duration_seconds {stats['duration']:.6f}\n")
        return 200, "text/plain; version=0.0.4", body.encode()
    return handler


if __name__ == "__main__":
    log("info", "probes starting")
    threading.Thread(target=loop, daemon=True).start()
    serve(9187, {"/metrics": exposition("app-db")}, daemon=True)
    serve(9121, {"/metrics": exposition("redis")})
