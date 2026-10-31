"""Load generator: about 10 requests per second against the api's /work (the traffic floor in contracts/telemetry.md)."""
import os
import threading
import time
import urllib.error
import urllib.request

from prometheus_client import Counter

from app.common import register_fs_metrics, json_body, log, metrics_route, serve

REQS = Counter("loadgen_requests_total", "Synthetic requests sent", ["status"])
TARGET = os.environ.get("TARGET_URL", "http://cd-api:8000/work")
THREADS = int(os.environ.get("THREADS", "4"))
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "0.4"))  # 4 threads / 0.4 s = 10 requests per second


def worker():
    while True:
        started = time.time()
        try:
            with urllib.request.urlopen(TARGET, timeout=2) as resp:
                REQS.labels(status=str(resp.status)).inc()
        except urllib.error.HTTPError as err:
            REQS.labels(status=str(err.code)).inc()
        except Exception:  # noqa: BLE001
            REQS.labels(status="error").inc()
        time.sleep(max(0.0, INTERVAL - (time.time() - started)))


if __name__ == "__main__":
    register_fs_metrics()
    log("info", "loadgen starting", target=TARGET, threads=THREADS)
    for _ in range(THREADS):
        threading.Thread(target=worker, daemon=True).start()
    serve(9101, {"/healthz": lambda q: json_body({"status": "alive"}), "/metrics": metrics_route})
