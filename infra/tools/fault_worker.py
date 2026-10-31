#!/usr/bin/env python3
"""Observe which telemetry signals change when the worker is killed (SIGKILL, a crash), and how they recover.

Usage: python3 infra/tools/fault_worker.py
Single observation (N=1) to verify the telemetry contract; NOT an experiment result.
Only touches the container cd-worker, and only if it carries the cloud-doctor.sandbox=true label.
"""
import json
import subprocess
import time
import urllib.parse
import urllib.request

PROM = "http://127.0.0.1:9090"
container = "cd-worker"
labels = json.loads(subprocess.check_output(["docker", "inspect", "--format", "{{json .Config.Labels}}", container], text=True))
if labels.get("cloud-doctor.sandbox") != "true":
    raise SystemExit("refusing: container lacks the cloud-doctor.sandbox=true label")


def q(expr):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    res = json.load(urllib.request.urlopen(url, timeout=10))["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def snapshot():
    return {
        "up": q('up{service="worker"}'),
        "processed_rate": q('sum(rate(jobs_processed_total{service="worker"}[15s]))'),
        "queue_depth": q('queue_depth{service="worker",queue="jobs"}'),
        "start_time": q('process_start_time_seconds{service="worker"}'),
        "api_5xx_ratio": q('sum(rate(http_requests_total{service="api",status=~"5.."}[15s])) / sum(rate(http_requests_total{service="api"}[15s]))'),
    }


def observe(label, t0, targets, steps=30):
    seen = {}
    for _ in range(steps):
        time.sleep(3)
        s = snapshot()
        t = round(time.time() - t0)
        for name, cond in targets.items():
            if name not in seen and cond(s, base):
                seen[name] = t
        print(f"t={t:>3}s", s)
        if len(seen) == len(targets):
            break
    print(f"{label}:", seen)


base = snapshot()
print("baseline:", base)
t0 = time.time()
subprocess.check_call(["docker", "kill", container], stdout=subprocess.DEVNULL)
print(f"killed {container} at t=0")
observe("first seen (seconds after kill)", t0, {
    "up_zero": lambda s, b: s["up"] == 0,
    "processing_stopped": lambda s, b: (s["processed_rate"] or 0) < 0.1,
    "queue_growing": lambda s, b: (s["queue_depth"] or 0) > (b["queue_depth"] or 0) + 5,
})
t1 = time.time()
subprocess.check_call(["docker", "start", container], stdout=subprocess.DEVNULL)
print(f"started {container} at t=0 (recovery observation)")
observe("recovery seen (seconds after start)", t1, {
    "up_one": lambda s, b: s["up"] == 1,
    "processing_resumed": lambda s, b: (s["processed_rate"] or 0) > 1,
    "start_time_changed": lambda s, b: s["start_time"] is not None and s["start_time"] != b["start_time"],
    "queue_draining": lambda s, b: s["queue_depth"] is not None and s["queue_depth"] < 20,
})
print("NOTE: single observation (N=1); times here are NOT experiment results.")
