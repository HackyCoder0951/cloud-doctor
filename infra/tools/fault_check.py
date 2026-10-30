#!/usr/bin/env python3
"""Observe which telemetry signals change when a sandbox container is stopped, and how they recover.

Usage: python3 infra/tools/fault_check.py [container=cd-redis] [service=redis]
This is a single observation (N=1) to verify the telemetry contract; it is NOT an experiment result.
It only stops and starts a container named cd-* that carries the sandbox label (checked first).
"""
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

PROM = "http://127.0.0.1:9090"
LOKI = "http://127.0.0.1:3100"
container = sys.argv[1] if len(sys.argv) > 1 else "cd-redis"
service = sys.argv[2] if len(sys.argv) > 2 else "redis"
if not re.fullmatch(r"cd-[a-z0-9-]{2,40}", container):
    sys.exit("refusing: container name must match cd-*")
labels = json.loads(subprocess.check_output(["docker", "inspect", "--format", "{{json .Config.Labels}}", container], text=True))
if labels.get("cloud-doctor.sandbox") != "true":
    sys.exit("refusing: container lacks the cloud-doctor.sandbox=true label")


def q(expr):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    res = json.load(urllib.request.urlopen(url, timeout=10))["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def error_ratio():
    errs = q('sum(rate(http_requests_total{service="api",status=~"5.."}[15s]))') or 0.0
    tot = q('sum(rate(http_requests_total{service="api"}[15s]))') or 0.0
    return errs / tot if tot > 0 else None


def snapshot():
    return {
        "cd_service_up": q(f'cd_service_up{{service="{service}"}}'),
        "up": q(f'up{{service="{service}"}}'),
        "api_error_ratio": error_ratio(),
        "queue_depth": q('queue_depth{service="worker",queue="jobs"}'),
        "api_dep_redis": q('cd_dependency_up{service="api",dependency="redis"}'),
    }


def log_lines(text):
    params = urllib.parse.urlencode({"query": f'{{service="api"}} |= "{text}"', "limit": 5, "since": "5m"})
    data = json.load(urllib.request.urlopen(f"{LOKI}/loki/api/v1/query_range?{params}", timeout=10))
    return sum(len(r["values"]) for r in data["data"]["result"])


print("baseline:", snapshot())
t0 = time.time()
subprocess.check_call(["docker", "stop", container], stdout=subprocess.DEVNULL)
print(f"stopped {container} at t=0")
seen = {}
for _ in range(25):
    time.sleep(3)
    s = snapshot()
    t = round(time.time() - t0)
    if "down" not in seen and (s["cd_service_up"] == 0 or s["up"] == 0):
        seen["down"] = t
    if "errors" not in seen and (s["api_error_ratio"] or 0) > 0.05:
        seen["errors"] = t
    if "queue_gone" not in seen and s["queue_depth"] is None:
        seen["queue_gone"] = t
    print(f"t={t:>3}s", s)
    if len(seen) == 3:
        break
print("first seen (seconds after stop):", seen)
print("api log lines mentioning the failure in Loki:", log_lines("redis connection failed"))

t1 = time.time()
subprocess.check_call(["docker", "start", container], stdout=subprocess.DEVNULL)
print(f"started {container} at t=0 (recovery observation)")
rec = {}
for _ in range(25):
    time.sleep(3)
    s = snapshot()
    t = round(time.time() - t1)
    if "up_again" not in rec and (s["cd_service_up"] == 1):
        rec["up_again"] = t
    if "errors_gone" not in rec and s["api_error_ratio"] is not None and s["api_error_ratio"] < 0.01:
        rec["errors_gone"] = t
    if "queue_back" not in rec and s["queue_depth"] is not None:
        rec["queue_back"] = t
    print(f"t={t:>3}s", s)
    if len(rec) == 3:
        break
print("recovery seen (seconds after start):", rec)
print("NOTE: single observation (N=1); detection and recovery times here are NOT experiment results.")
