"""Test doubles shared by the harness tests: no Docker, no network, no LLM."""
from __future__ import annotations

from typing import Mapping, Sequence

from harness.command import CommandResult, check_argv


class FakeRunner:
    """Records every argv (validated like the real runner) and answers `docker inspect` labels."""

    def __init__(self, unlabeled: set[str] = frozenset(), failing: set[str] = frozenset(),
                 running: dict[str, bool] | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.unlabeled = set(unlabeled)
        self.failing = set(failing)
        self.running = running if running is not None else {}

    def run(self, argv: Sequence[str], *, timeout: float, env: Mapping[str, str] | None = None) -> CommandResult:
        args = check_argv(argv)
        assert timeout > 0
        self.calls.append((args, dict(env or {})))
        if args[:2] == ["docker", "inspect"]:
            container = args[-1]
            fmt = args[3]
            if container in self.failing:
                return CommandResult(1, "", "no such container")
            if "State.Running" in fmt:
                return CommandResult(0, "true\n" if self.running.get(container, True) else "false\n")
            return CommandResult(0, "" if container in self.unlabeled else "true\n")
        if len(args) > 2 and args[1] in ("stop", "kill") and args[-1] in self.running:
            self.running[args[-1]] = False
        if len(args) > 2 and args[1] in ("start", "restart") and args[-1] in self.running:
            self.running[args[-1]] = True
        return CommandResult(0, "", "")

    @property
    def argvs(self) -> list[list[str]]:
        return [a for a, _ in self.calls]

    def mutating(self) -> list[list[str]]:
        return [a for a in self.argvs if a[:2] != ["docker", "inspect"]]
