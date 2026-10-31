import json
from datetime import timedelta

import pytest

from cd_policy import BundleStatus, Layer2Client, OpaHealthEndpoint, StaticBundleHealth, TransportError
from pol_helpers import GOOD, NOW, FakeOpa, client, reply

INPUT = {"action": "restart_service", "params": {"service": "api"}}
ALLOW = {"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"]}


def test_allow_roundtrip_and_request_shape():
    c, opa = client()
    out = c.evaluate(INPUT)
    assert out == {"result": "allow", "rule_ids": ["C-DEFAULT-ALLOW"], "bundle_signed": True, "bundle_revision": "r1"}
    method, url, body, timeout = opa.requests[0]
    assert method == "POST" and url == "http://127.0.0.1:8181/v1/data/cloud_doctor/policy/decision"
    assert json.loads(body) == {"input": INPUT} and 0 < timeout <= 5


@pytest.mark.parametrize("result", ["allow_with_approval", "deny"])
def test_other_valid_results_pass_through(result):
    c, _ = client(FakeOpa(reply({"result": result, "rule_ids": ["C-X"]})))
    assert c.evaluate(INPUT)["result"] == result


@pytest.mark.parametrize("opa_reply,code", [
    (TransportError("ConnectionRefusedError"), "L2-UNAVAILABLE"),
    (TransportError("timeout"), "L2-UNAVAILABLE"),
    ((404, b"{}"), "L2-HTTP-ERROR"), ((500, b'{"result": {"result":"allow","rule_ids":[]}}'), "L2-HTTP-ERROR"),
    ((302, b""), "L2-HTTP-ERROR"), ((204, b""), "L2-HTTP-ERROR"), ((201, b"{}"), "L2-HTTP-ERROR"),
    ((200, b"not json"), "L2-MALFORMED"), ((200, b""), "L2-MALFORMED"), ((200, b"\xff\xfe"), "L2-MALFORMED"),
    ((200, b"[]"), "L2-MALFORMED"), ((200, b"true"), "L2-MALFORMED"), ((200, b'"allow"'), "L2-MALFORMED"),
    ((200, b"{}"), "L2-UNDEFINED"),                                         # undefined decision
    ((200, b'{"decision_id": "abc"}'), "L2-UNDEFINED"),
    (reply(None), "L2-INVALID-RESULT"), (reply(True), "L2-INVALID-RESULT"), (reply("allow"), "L2-INVALID-RESULT"),
    (reply({}), "L2-INVALID-RESULT"), (reply({"result": "allow"}), "L2-INVALID-RESULT"),
    (reply({"result": "maybe", "rule_ids": []}), "L2-INVALID-RESULT"),
    (reply({"result": "allow", "rule_ids": "C-X"}), "L2-INVALID-RESULT"),
    (reply({"result": "allow", "rule_ids": [1]}), "L2-INVALID-RESULT"),
    (reply({"result": "allow", "rule_ids": ["x" * 200]}), "L2-INVALID-RESULT"),
    (reply({"result": ["allow"], "rule_ids": []}), "L2-INVALID-RESULT"),
])
def test_every_opa_problem_is_a_deny(opa_reply, code):
    c, _ = client(FakeOpa(opa_reply))
    out = c.evaluate(INPUT)
    assert out["result"] == "deny" and out["rule_ids"] == [code] and out["bundle_signed"] is False and out["problem"]


def test_unexpected_transport_exception_is_a_deny():
    c, _ = client(FakeOpa(RuntimeError("anything")))
    assert c.evaluate(INPUT)["result"] == "deny"


@pytest.mark.parametrize("status,code", [
    (BundleStatus(active=False, signed=True, revision="r1", last_activated=NOW), "L2-UNAVAILABLE"),
    (BundleStatus(active=True, signed=False, revision="r1", last_activated=NOW), "L2-UNSIGNED-BUNDLE"),
])
def test_inactive_or_unsigned_bundle_denies_without_querying_opa(status, code):
    c, opa = client(status=status)
    assert c.evaluate(INPUT)["rule_ids"] == [code] and opa.requests == []


def test_stale_bundle_denies():
    c, opa = client(status=BundleStatus(True, True, "r1", NOW - timedelta(hours=2)), max_bundle_age_seconds=600)
    assert c.evaluate(INPUT)["rule_ids"] == ["L2-BUNDLE-STALE"] and opa.requests == []
    c, _ = client(status=BundleStatus(True, True, "r1", None), max_bundle_age_seconds=600)
    assert c.evaluate(INPUT)["rule_ids"] == ["L2-BUNDLE-STALE"]
    c, _ = client(status=BundleStatus(True, True, "r1", NOW - timedelta(seconds=599)), max_bundle_age_seconds=600)
    assert c.evaluate(INPUT)["result"] == "allow"


def test_bundle_health_error_or_wrong_type_denies():
    class Boom:
        def status(self):
            raise OSError("no route")
    c = Layer2Client("http://127.0.0.1:8181", Boom(), transport=FakeOpa())
    assert c.evaluate(INPUT)["result"] == "deny"
    class Weird:
        def status(self):
            return {"active": True}
    assert Layer2Client("http://127.0.0.1:8181", Weird(), transport=FakeOpa()).evaluate(INPUT)["result"] == "deny"


def test_unserialisable_input_denies():
    c, opa = client()
    assert c.evaluate({"x": float("nan")})["result"] == "deny" and opa.requests == []
    assert c.evaluate({"x": object()})["result"] == "deny"


@pytest.mark.parametrize("url", ["ftp://x", "http://", "http://u:p@h", "http://h/?q=1", "http://h/#f", "file:///etc/passwd", ""])
def test_rejects_bad_base_urls(url):
    with pytest.raises(ValueError):
        Layer2Client(url, StaticBundleHealth(GOOD))


@pytest.mark.parametrize("path", ["", "../x", "a b", "a/../b", "a?x=1", "a//b", "/a"])
def test_rejects_bad_decision_paths(path):
    with pytest.raises(ValueError):
        Layer2Client("http://127.0.0.1:8181", StaticBundleHealth(GOOD), decision_path=path)


def test_bundle_health_is_mandatory():
    with pytest.raises(ValueError):
        Layer2Client("http://127.0.0.1:8181", None)


def test_health_endpoint_200_means_active_and_declared_signed():
    ok = OpaHealthEndpoint("http://127.0.0.1:8181", bundle_signed=True, revision="r9", transport=FakeOpa((200, b"{}")))
    st = ok.status()
    assert st.active and st.signed and st.revision == "r9"
    bad = OpaHealthEndpoint("http://127.0.0.1:8181", bundle_signed=True, transport=FakeOpa((500, b"{}")))
    assert not bad.status().active
    unsigned = OpaHealthEndpoint("http://127.0.0.1:8181", bundle_signed=False, transport=FakeOpa((200, b"{}")))
    c = Layer2Client("http://127.0.0.1:8181", unsigned, transport=FakeOpa())
    assert c.evaluate(INPUT)["rule_ids"] == ["L2-UNSIGNED-BUNDLE"]
    down = OpaHealthEndpoint("http://127.0.0.1:8181", bundle_signed=True, transport=FakeOpa(TransportError("refused")))
    assert Layer2Client("http://127.0.0.1:8181", down, transport=FakeOpa()).evaluate(INPUT)["result"] == "deny"
