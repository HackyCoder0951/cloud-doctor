"""`python -m actuator` — configuration comes ONLY from environment variables."""
from __future__ import annotations

import logging
import os
import signal
import sys

import invariants as inv

from .audit import AuditError, FileAuditSink
from .core import Actuator, KeyFile
from .executor import DockerExecutor
from .runner import SubprocessRunner
from .server import ActuatorServer


def build_from_env(env=os.environ, runner=None) -> tuple[Actuator, str]:
    socket_path = env.get("CD_ACTUATOR_SOCKET")
    key_file = env.get("CD_SIGNING_KEY_FILE")
    sink = env.get("CD_AUDIT_SINK")
    if not socket_path or not key_file or not sink:
        raise SystemExit("CD_ACTUATOR_SOCKET, CD_SIGNING_KEY_FILE and CD_AUDIT_SINK must be set")
    if sink == "postgres":
        raise SystemExit("CD_AUDIT_SINK=postgres is not implemented in the actuator yet; use an NDJSON file path")
    catalog = inv.Catalog.load(env.get("CD_CATALOG_PATH", "infra/catalog/services.yaml"))
    keys = KeyFile(key_file)
    keys.get()                                    # fail fast on a missing, short or world-readable key
    audit = FileAuditSink(sink)                   # fails if the existing chain is broken
    executor = DockerExecutor(runner or SubprocessRunner(), catalog)
    actuator = Actuator(catalog=catalog, key_file=keys, key_id=env.get("CD_SIGNING_KEY_ID", "mvp-1"),
                        audit=audit, executor=executor)
    return actuator, socket_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        actuator, socket_path = build_from_env()
    except (AuditError, OSError, ValueError, inv.CatalogError, RuntimeError) as exc:
        print(f"actuator: refusing to start: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    server = ActuatorServer(socket_path, actuator)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    logging.getLogger("actuator").info("listening on %s (invariants %s)", socket_path, inv.__version__)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
