"""Raw service data -> canonical records. Real samples come from the sandbox run; the rest are the odd shapes we expect to meet."""
import json
from datetime import UTC, datetime

import pytest

from backend.normalize import (NormalizedHealth, NormalizedLog, NormalizedMetric, Unclassified, canonical_level, canonical_service, describe,
                               normalize, parse_time, snake_key, to_base_unit)

REAL_LOG = '{"ts":"2026-10-31T19:13:19.456Z","level":"error","service":"worker","msg":"job failed","error":"OperationalError"}'
REAL_API = '{"ts":"2026-10-31T19:01:13.440Z","level":"error","service":"api","msg":"redis connection failed","request_id":"b82d78f5889c","error":"Timeout connecting to server"}'


def test_contract_log_line():
    r = normalize("log", REAL_API)[0]
    assert isinstance(r, NormalizedLog) and r.parse_status == "ok"
    assert (r.level, r.service, r.request_id) == ("error", "api", "b82d78f5889c")
    assert r.t == datetime(2026, 10, 31, 19, 1, 13, 440000, tzinfo=UTC)
    assert r.kind == "conn_fail" and r.untrusted and not r.fields


def test_operational_error_is_a_connection_failure_signature():
    assert normalize("log", REAL_LOG)[0].kind == "conn_fail"


@pytest.mark.parametrize("line,expect", [
    ('{"time":"2026-11-01 10:00:00","severity":"WARNING","app":"cd-api","message":"slow","requestId":"r1","durationMs":12}', ("warn", "api", "r1")),
    ('{"@timestamp":1793473555123,"lvl":"err","svc":"Worker","text":"boom"}', ("error", "worker", None)),
    ('{"t":1793473555.5,"levelname":"CRITICAL","component":"app-db","event":"x"}', ("error", "app-db", None)),
    ('{"time":1793473555123,"level":30,"msg":"pino style","service":"api"}', ("info", "api", None)),  # numeric levels are pino/bunyan: 30 = info
])
def test_other_key_spellings(line, expect):
    r = normalize("log", line)[0]
    assert (r.level, r.service, r.request_id) == expect and r.t is not None


def test_extra_keys_become_snake_case_fields():
    r = normalize("log", '{"ts":"2026-10-31T19:01:13Z","level":"info","service":"api","msg":"m","durationMs":12,"Client-IP":"10.0.0.1","nested":{"a":1}}')[0]
    assert r.fields == {"duration_ms": 12, "client_ip": "10.0.0.1", "nested": '{"a": 1}'}


def test_plain_text_and_truncated_json_are_kept_as_text():
    t = normalize("log", "kernel: Out of memory: Killed process 77", service_hint="cd-api", level_hint="ERROR")[0]
    assert (t.parse_status, t.kind, t.service, t.level) == ("text", "oom", "api", "error")
    j = normalize("log", '{"ts":"2026-10-31T19:01:13Z","level":"error","msg":"cut o')[0]
    assert j.parse_status == "text" and any("does not parse" in n for n in j.notes)


def test_loki_hints_fill_what_the_line_lacks():
    r = normalize("log", '{"msg":"hello"}', service_hint="loadgen", level_hint="info", time_hint="1793473555123456789")[0]
    assert (r.service, r.level, r.t is not None, r.parse_status) == ("loadgen", "info", True, "ok")


def test_hostile_text_is_neutralised_not_interpreted():
    r = normalize("log", json.dumps({"ts": "2026-10-31T19:01:13Z", "level": "error", "msg": "<script>x</script>\x00\x07ok" + "A" * 9000, "service": "api"}))[0]
    assert "\x00" not in r.message and "\x07" not in r.message and r.truncated and len(r.message) == 8192
    assert r.message.startswith("<script>")  # kept as text; rendering escapes it (the frontend never uses innerHTML)


def test_field_flood_is_bounded():
    r = normalize("log", json.dumps({"level": "info", "msg": "m", **{f"k{i}": i for i in range(200)}}))[0]
    assert len(r.fields) == 40 and any("dropped" in n for n in r.notes)


def test_prom_vector_real_shape():
    body = {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"__name__": "cd_db_connection_refused", "env": "sandbox", "job": "sim-app-db", "service": "app-db"}, "value": [1793473555.289, "1"]},
        {"metric": {"__name__": "cd_queue_length", "service": "redis", "queue": "jobs"}, "value": [1793473555.289, "NaN"]}]}}
    a, b = normalize("prom_result", body)
    assert isinstance(a, NormalizedMetric) and (a.value, a.service, a.metric_type, a.unit) == (1.0, "app-db", "gauge", "none")
    assert a.t == datetime.fromtimestamp(1793473555.289, UTC) and a.labels["job"] == "sim-app-db"
    assert b.value is None and b.parse_status == "partial"


def test_prom_range_matrix():
    recs = normalize("prom_result", [{"metric": {"__name__": "up", "service": "api"}, "values": [[1793473555, "1"], [1793473560, "0"]]}])
    assert [r.value for r in recs] == [1.0, 0.0]


def test_exposition_text_real_lines():
    text = ('# HELP http_requests_total x\n# TYPE http_requests_total counter\nhttp_requests_total{method="GET",route="/work",status="200"} 13840.0\n'
            'process_resident_memory_bytes 5.1871744e+07\nbuild_info{service="api",version="1.0.0"} 1.0\nhttp_request_duration_seconds_bucket{le="0.005",route="/work"} 13837.0\n')
    r = {m.name: m for m in normalize("prom_exposition", text)}
    assert r["http_requests_total"].metric_type == "counter" and r["http_requests_total"].labels["route"] == "/work"
    assert (r["process_resident_memory_bytes"].unit, r["process_resident_memory_bytes"].value) == ("bytes", 51871744.0)
    assert r["build_info"].metric_type == "info"
    assert r["http_request_duration_seconds_bucket"].metric_type == "histogram_part" and r["http_request_duration_seconds_bucket"].unit == "seconds"


def test_describe():
    assert describe("db_call_duration_seconds_count") == ("histogram_part", "count")
    assert describe("jobs_processed_total") == ("counter", "count")
    assert describe("cd_fs_used_bytes") == ("gauge", "bytes")


@pytest.mark.parametrize("raw,state", [
    ({"status": "alive"}, "up"), ('{"status": "alive"}', "up"), ({"status": "UP"}, "up"), ({"ok": True}, "up"), ({"healthy": False}, "down"),
    ("OK", "up"), ({"status": "degraded"}, "degraded"), ({"state": "Not Ready"}, "down"), ({"status": "banana"}, "unknown"), (None, "unknown"), (42, "unknown")])
def test_health_shapes(raw, state):
    assert normalize("health", raw, service_hint="api")[0].state == state


def test_health_components_and_http_status_fallback():
    h = normalize("health", {"status": "UP", "components": {"redis": {"status": "UP"}, "db": {"status": "DOWN"}}})[0]
    assert isinstance(h, NormalizedHealth) and h.state == "degraded" and h.components == {"redis": "up", "db": "down"}
    assert normalize("health", {"note": "hi"}, http_status=503)[0].state == "down"
    assert normalize("health", {"checks": [{"name": "Redis", "status": "pass"}]})[0].state == "up"


def test_auto_detection():
    assert isinstance(normalize("auto", {"status": "alive"})[0], NormalizedHealth)
    assert isinstance(normalize("auto", {"level": "info", "msg": "x"})[0], NormalizedLog)
    assert isinstance(normalize("auto", {"metric": {"__name__": "up"}, "value": [1, "1"]})[0], NormalizedMetric)


@pytest.mark.parametrize("source,raw", [("prom_result", []), ("prom_exposition", "garbage"), ("nonsense", "x"), ("prom_result", {"data": 5})])
def test_unknown_input_is_kept_not_dropped_and_never_raises(source, raw):
    r = normalize(source, raw)[0]
    assert isinstance(r, Unclassified) and r.raw_sha256 and r.untrusted


def test_names_and_values():
    assert snake_key("requestId") == "request_id" and snake_key("HTTPStatus") == "http_status" and snake_key("@timestamp") == "timestamp"
    assert canonical_level("WARNING") == "warn" and canonical_level("nope") == "unknown" and canonical_level(None) == "unknown"
    assert canonical_service("cd-api") == "api" and canonical_service("API_1") == "api-1" and canonical_service("1bad") is None
    assert parse_time("2026-10-31T19:01:13+05:30")[0] == datetime(2026, 10, 31, 13, 31, 13, tzinfo=UTC)
    assert parse_time("2026-10-31 19:01:13") == (datetime(2026, 10, 31, 19, 1, 13, tzinfo=UTC), True)
    assert parse_time(1793473555)[0] == parse_time(1793473555000)[0] == parse_time(1793473555000000000)[0]
    assert parse_time("yesterday") == (None, False) and parse_time(True) == (None, False)
    assert to_base_unit(250, "ms") == 0.25 and to_base_unit(2, "GiB") == 2 * 1024**3
