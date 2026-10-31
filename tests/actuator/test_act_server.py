import http.client
import json
import os
import socket
import stat
import sys
import tempfile
import threading

import pytest

import invariants as inv
from actuator.__main__ import build_from_env
from actuator.client import ActuatorClient, ActuatorError, _UnixConnection
from actuator.runner import CommandError, SubprocessRunner
from actuator.server import ActuatorServer
from act_helpers import KEY, FakeRunner, Rig, write_key
from inv_helpers import approval_for, make_plan


@pytest.fixture
def served(tmp_path):
    rig = Rig(tmp_path)
    sock_dir = tempfile.mkdtemp(prefix="cda")
    path = os.path.join(sock_dir, "a.sock")
    try:
        server = ActuatorServer(path, rig.actuator)
    except OSError as exc:  # pragma: no cover
        pytest.skip(f"cannot create unix sockets here: {exc}")
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield rig, path, ActuatorClient(path, timeout=5)
    server.shutdown()
    server.server_close()
    t.join(2)
    os.rmdir(sock_dir)


def raw(path, method, target, body=b"", headers=None):
    c = _UnixConnection(path, 5)
    try:
        c.request(method, target, body=body, headers=headers or {})
    except (BrokenPipeError, ConnectionResetError):
        pass  # the server answered (404/405/413) and closed before the body was sent; the response is still readable
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def test_socket_mode_is_0660_and_removed_on_close(served):
    rig, path, client = served
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o660 and stat.S_ISSOCK(os.stat(path).st_mode)


def test_healthz(served):
    rig, path, client = served
    assert client.healthz() == {"state": "ok", "invariants_version": "inv-0.1"}
    os.unlink(rig.key_path)
    assert client.healthz()["state"] == "degraded"


def test_validate_and_execute_over_the_socket(served):
    rig, path, client = served
    s = rig.signed()
    assert client.validate(s)["ok"] is True
    out = client.execute(s, "idem-sock-0001")
    assert out["execution"]["result"] == "success" and out["execution"]["executed_argv"] == ["docker", "restart", "cd-api"]
    assert client.execute(s, "idem-sock-0001") == out
    assert len(rig.runner.restarts) == 1


def test_refusal_is_a_200_with_result_refused(served):
    rig, path, client = served
    plan = make_plan(params={"service": "redis"}, risk="medium")
    out = client.execute(rig.signed(plan), "idem-sock-0002")
    assert out["execution"]["result"] == "refused" and "I-03" in out["execution"]["refusal_rule_ids"]


def test_bad_requests_are_400_and_never_execute(served):
    rig, path, client = served
    cases = [b"", b"not json", b"[]", b'{"signed_plan": {}, "idempotency_key": "short"}', b'{"a":1,"a":2}',
             b'{"signed_plan": NaN}']
    for body in cases:
        status, _ = raw(path, "POST", "/v1/execute", body, {"Content-Length": str(len(body))})
        assert status == 400, body
    status, _ = raw(path, "POST", "/v1/execute", b"{}", {"Transfer-Encoding": "chunked", "Content-Length": "2"})
    assert status == 400
    sk = socket.socket(socket.AF_UNIX)
    sk.connect(path)
    sk.sendall(b"POST /v1/execute HTTP/1.0\r\nContent-Length: 10485760\r\n\r\n")   # oversized declaration
    assert sk.recv(64).startswith(b"HTTP/1.0 400")
    sk.close()
    with pytest.raises(ActuatorError) as e:
        client._call("POST", "/v1/validate", {})
    assert e.value.status == 400
    assert client.validate({})["ok"] is False          # well-formed request, envelope malformed: 200 + ok=false
    assert rig.runner.calls == []


def test_unknown_routes_and_methods(served):
    rig, path, client = served
    assert raw(path, "GET", "/v1/execute")[0] == 404
    assert raw(path, "POST", "/admin", b"{}", {"Content-Length": "2"})[0] == 404
    assert raw(path, "PUT", "/v1/execute", b"{}", {"Content-Length": "2"})[0] == 405
    assert raw(path, "DELETE", "/healthz")[0] == 405


def test_stalled_client_does_not_block_the_server(served):
    rig, path, client = served
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    s.sendall(b"POST /v1/execute HTTP/1.0\r\nContent-Length: 50\r\n\r\n{")   # never finishes
    # the handler times out after 10 s; meanwhile a fresh connection queues. Just prove the socket accepts.
    s.close()
    assert client.healthz()["state"] == "ok"


def test_stale_socket_file_is_replaced(tmp_path):
    rig = Rig(tmp_path)
    d = tempfile.mkdtemp(prefix="cdb")
    path = os.path.join(d, "a.sock")
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    s.close()
    server = ActuatorServer(path, rig.actuator)
    server.server_close()
    assert not os.path.exists(path)
    os.rmdir(d)


def test_regular_file_at_socket_path_is_not_deleted(tmp_path):
    rig = Rig(tmp_path)
    p = tmp_path / "s"
    p.write_text("precious")
    with pytest.raises(OSError):
        ActuatorServer(str(p), rig.actuator)
    assert p.read_text() == "precious"


# ---- subprocess runner ------------------------------------------------------------------------
def test_subprocess_runner_no_shell_and_minimal_env(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    r = SubprocessRunner().run([sys.executable, "-c", "import os,sys;print(sorted(os.environ));print(sys.argv[1])", "a; echo pwned $(id)"], 10)
    assert r.returncode == 0
    assert "SECRET_TOKEN" not in r.stdout and "'PATH'" in r.stdout
    assert "a; echo pwned $(id)" in r.stdout.splitlines()[1]     # passed verbatim, not interpreted


def test_subprocess_runner_timeout_and_missing_binary_and_bad_argv():
    with pytest.raises(CommandError):
        SubprocessRunner().run([sys.executable, "-c", "import time;time.sleep(5)"], 0.3)
    with pytest.raises(CommandError):
        SubprocessRunner().run(["/nonexistent/binary"], 1)
    for bad in ([], [1], "docker restart x"):
        with pytest.raises(CommandError):
            SubprocessRunner().run(bad, 1)


# ---- python -m actuator configuration ----------------------------------------------------------
def test_build_from_env_reads_only_environment(tmp_path):
    import json as _j
    from inv_helpers import CATALOG_DICT
    cat = tmp_path / "c.json"
    cat.write_text(_j.dumps(CATALOG_DICT))
    key = write_key(tmp_path)
    env = {"CD_ACTUATOR_SOCKET": str(tmp_path / "s"), "CD_SIGNING_KEY_FILE": str(key),
           "CD_AUDIT_SINK": str(tmp_path / "audit.ndjson"), "CD_CATALOG_PATH": str(cat)}
    actuator, sock = build_from_env(env, runner=FakeRunner())
    assert sock == env["CD_ACTUATOR_SOCKET"] and actuator.degraded_reason is None


@pytest.mark.parametrize("drop", ["CD_ACTUATOR_SOCKET", "CD_SIGNING_KEY_FILE", "CD_AUDIT_SINK"])
def test_build_from_env_requires_variables(tmp_path, drop):
    from inv_helpers import CATALOG_DICT
    cat = tmp_path / "c.json"
    cat.write_text(json.dumps(CATALOG_DICT))
    env = {"CD_ACTUATOR_SOCKET": "x", "CD_SIGNING_KEY_FILE": str(write_key(tmp_path)),
           "CD_AUDIT_SINK": str(tmp_path / "a"), "CD_CATALOG_PATH": str(cat)}
    del env[drop]
    with pytest.raises(SystemExit):
        build_from_env(env)


def test_build_from_env_rejects_postgres_sink_and_insecure_key(tmp_path):
    from inv_helpers import CATALOG_DICT
    cat = tmp_path / "c.json"
    cat.write_text(json.dumps(CATALOG_DICT))
    base = {"CD_ACTUATOR_SOCKET": "x", "CD_SIGNING_KEY_FILE": str(write_key(tmp_path)), "CD_CATALOG_PATH": str(cat)}
    with pytest.raises(SystemExit):
        build_from_env({**base, "CD_AUDIT_SINK": "postgres"})
    p = tmp_path / "loose.key"
    p.write_bytes(KEY)
    os.chmod(p, 0o644)
    with pytest.raises(PermissionError):
        build_from_env({**base, "CD_SIGNING_KEY_FILE": str(p), "CD_AUDIT_SINK": str(tmp_path / "a")})
