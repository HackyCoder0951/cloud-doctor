from datetime import timedelta

import httpx

from backend.domain.clock import parse_ts
from backend.telemetry.base import EMPTY, ERROR, OK, TIMEOUT, missing_signal_for
from backend.telemetry.http import HttpProber, LokiHttpClient, PromHttpClient


def prom(handler):
    return PromHttpClient("http://prom", client=httpx.Client(transport=httpx.MockTransport(handler)))


AT = parse_ts("2026-11-02T09:00:00Z")


def test_prom_http_parses_vector_and_empty():
    ok = prom(lambda r: httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"service": "api"}, "value": [1793610000, "0"]}]}}))
    res = ok.query("up", AT)
    assert res.status == OK and res.last_value() == 0.0
    empty = prom(lambda r: httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}}))
    assert empty.query("up", AT).status == EMPTY


def test_prom_http_failures_are_errors_never_empty():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    assert prom(boom).query("up", AT).status == TIMEOUT
    assert prom(refused).query("up", AT).status == ERROR
    assert prom(lambda r: httpx.Response(503)).query("up", AT).status == ERROR
    assert prom(lambda r: httpx.Response(200, text="not json")).query("up", AT).status == ERROR
    assert prom(lambda r: httpx.Response(200, json={"status": "error"})).query("up", AT).status == ERROR
    for s in (TIMEOUT, ERROR):
        assert missing_signal_for(s, expected_absent=True) == "collection_failed"


def test_missing_signal_mapping():
    assert missing_signal_for(EMPTY, True) == "no_data_expected"
    assert missing_signal_for(EMPTY, False) == "no_data_unexpected"
    assert missing_signal_for(OK, False) == "none"


def test_loki_http_parses_and_fails_closed():
    body = {"data": {"result": [{"stream": {"service": "api"}, "values": [["1793610001000000000", '{"level":"error","msg":"x"}']]}]}}
    c = LokiHttpClient("http://loki", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))
    res = c.query_range('{service="api"}', AT, AT + timedelta(seconds=10))
    assert res.status == OK and res.lines[0].level == "error"
    bad = LokiHttpClient("http://loki", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert bad.query_range("{}", AT, AT).status == ERROR


def test_http_prober_unknown_when_no_url_and_false_on_error():
    p = HttpProber({"api": "http://x/work"}, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    assert p.probe("api", AT).ok is False
    assert p.probe("redis", AT).ok is None  # cannot be established -> fail closed


def test_fake_prom_instant_range_gap_and_absent(world, cfg):
    w = world("redis_outage")
    q = lambda m, s: cfg.query(m, s)  # noqa: E731
    at = lambda s: w.scenario.at(s)  # noqa: E731
    assert w.prom.query(q("cd_service_up", "redis"), at(30)).last_value() == 1
    assert w.prom.query(q("cd_service_up", "redis"), at(90)).last_value() == 0
    # queue_depth disappears while redis is unreachable; absent() derived from the gap
    assert w.prom.query(q("queue_depth", "worker"), at(90)).status == EMPTY
    assert w.prom.query(q("absent_queue_depth", "worker"), at(90)).last_value() == 1
    assert w.prom.query(q("absent_queue_depth", "worker"), at(30)).status == EMPTY
    rng = w.prom.query_range(q("error_ratio", "api"), at(0), at(120))
    assert rng.status == OK and len(rng.series[0].points) > 20


def test_fake_outage_yields_timeout_not_empty(world, cfg):
    w = world("telemetry_outage")
    res = w.prom.query(cfg.query("up", "api"), w.scenario.at(150))
    assert res.status == TIMEOUT and res.series == []
    assert w.prom.query(cfg.query("up", "api"), w.scenario.at(50)).status == OK


def test_fake_logs_filter_and_outage(world):
    w = world("redis_outage")
    res = w.logs.query_range('{service="api",level="error"} |~ "redis connection failed"', w.scenario.at(0), w.scenario.at(120))
    assert res.status == OK and all(l.level == "error" for l in res.lines)
    assert w.logs.query_range('{service="redis"}', w.scenario.at(0), w.scenario.at(120)).status == EMPTY
    w2 = world("redis_outage_telemetry_failure")
    assert w2.logs.query_range('{service="api"}', w2.scenario.at(100), w2.scenario.at(150)).status == ERROR


def test_fake_feed_and_prober(world):
    w = world("redis_outage")
    assert [e.kind for e in w.feed.events(w.scenario.at(0), w.scenario.at(100)).events] == ["container_stop"]
    assert w.prober.probe("api", w.scenario.at(70)).ok is True
    w.scenario.data["probes"] = {"api": [{"from_s": 60, "to_s": 100, "ok": False}]}
    assert w.prober.probe("api", w.scenario.at(70)).ok is False
