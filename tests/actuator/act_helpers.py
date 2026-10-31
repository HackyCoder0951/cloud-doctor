import json
import os
from datetime import datetime, timedelta, timezone

import invariants as inv
from actuator.audit import FileAuditSink
from actuator.client import build_signed_plan
from actuator.core import Actuator, KeyFile
from actuator.executor import DockerExecutor
from actuator.runner import CommandError, CommandResult
from inv_helpers import approval_for, catalog, make_plan

KEY = b"unit-test-signing-key-0123456789"
T0 = datetime(2026, 11, 2, 9, 0, 30, tzinfo=timezone.utc)
LABELS = {"cloud-doctor.sandbox": "true"}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


class FakeRunner:
    """Scripted CommandRunner: no real Docker, no subprocess."""

    def __init__(self, labels=None, restart_rc=0, inspect_rc=0, raise_on=None):
        self.calls = []
        self.labels = {} if labels is None else labels
        self.restart_rc, self.inspect_rc, self.raise_on = restart_rc, inspect_rc, raise_on
        self.per_container = {}

    def run(self, argv, timeout):
        argv = list(argv)
        self.calls.append(argv)
        assert isinstance(timeout, (int, float)) and timeout > 0
        if self.raise_on and argv[1] == self.raise_on:
            raise CommandError("boom")
        if argv[:2] == ["docker", "inspect"]:
            labels = self.per_container.get(argv[-1], LABELS if self.labels == {} else self.labels)
            return CommandResult(self.inspect_rc, json.dumps(labels), "")
        if argv[:2] == ["docker", "restart"]:
            return CommandResult(self.restart_rc, argv[-1], "")
        return CommandResult(127, "", "unexpected command")

    @property
    def restarts(self):
        return [c for c in self.calls if c[:2] == ["docker", "restart"]]


class BrokenAudit(FileAuditSink):
    fail = False

    def append(self, *a, **k):
        if self.fail:
            from actuator.audit import AuditError
            raise AuditError("disk full")
        return super().append(*a, **k)


def write_key(tmp_path, key=KEY, mode=0o600):
    p = tmp_path / "signing.key"
    p.write_bytes(key + b"\n")
    os.chmod(p, mode)
    return p


class Rig:
    def __init__(self, tmp_path, runner=None, **kw):
        self.tmp = tmp_path
        self.clock = Clock()
        self.runner = runner or FakeRunner()
        self.key_path = write_key(tmp_path)
        self.audit_path = tmp_path / "audit.ndjson"
        self.audit = BrokenAudit(self.audit_path, clock=self.clock)
        self.cat = catalog()
        self.actuator = Actuator(catalog=self.cat, key_file=KeyFile(str(self.key_path)), key_id="mvp-1", audit=self.audit,
                                 executor=DockerExecutor(self.runner, self.cat), clock=self.clock, **kw)
        self._n = 0

    def nonce(self):
        self._n += 1
        return f"nonce-{self._n:012d}"

    def signed(self, plan=None, *, approval=None, ttl=120, key=KEY, key_id="mvp-1", nonce=None, now=None):
        plan = plan or make_plan(params={"service": "api"})
        return build_signed_plan(plan, key, key_id=key_id, nonce=nonce or self.nonce(), now=now or self.clock(),
                                 ttl_seconds=ttl, approval=approval)

    def execute(self, signed=None, idem="idem-0000001", **kw):
        signed = signed or self.signed(**kw)
        return self.actuator.execute({"signed_plan": signed, "idempotency_key": idem})["execution"]

    def audit_events(self):
        return list(self.audit.events())
