"""The only executing action in the MVP: `docker restart <container>`, as a fixed argv list."""
from __future__ import annotations

import json
import re

from invariants import Catalog

from .runner import CommandError, CommandRunner, CommandResult

CONTAINER_RE = re.compile(r"cd-[a-z0-9-]{2,40}")


class ExecutorError(Exception):
    pass


def inspect_argv(container: str) -> list[str]:
    return ["docker", "inspect", "--format", "{{json .Config.Labels}}", container]


def restart_argv(container: str) -> list[str]:
    return ["docker", "restart", container]


class DockerExecutor:
    def __init__(self, runner: CommandRunner, catalog: Catalog, inspect_timeout: float = 10.0,
                 restart_timeout: float = 30.0):
        self._runner, self._catalog = runner, catalog
        self._inspect_timeout, self._restart_timeout = inspect_timeout, restart_timeout

    def check_container(self, container) -> str:
        """The name must match the sandbox pattern AND be exactly a catalogue container."""
        if not (isinstance(container, str) and CONTAINER_RE.fullmatch(container)):
            raise ExecutorError("container name rejected")
        if self._catalog.by_container(container) is None:
            raise ExecutorError("container is not in the catalogue")
        return container

    def labels(self, container: str) -> dict:
        """Real labels of the running container (read-only `docker inspect`)."""
        container = self.check_container(container)
        try:
            res = self._runner.run(inspect_argv(container), self._inspect_timeout)
        except CommandError as exc:
            raise ExecutorError(str(exc)) from exc
        if res.returncode != 0:
            raise ExecutorError("docker inspect failed")
        try:
            labels = json.loads(res.stdout)
        except ValueError as exc:
            raise ExecutorError("docker inspect output is not JSON") from exc
        if labels is None:
            return {}
        if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
            raise ExecutorError("unexpected label structure")
        return labels

    def restart(self, container: str) -> tuple[list[str], CommandResult]:
        container = self.check_container(container)
        argv = restart_argv(container)
        return argv, self._runner.run(argv, self._restart_timeout)
