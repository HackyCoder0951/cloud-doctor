"""Command execution for the injector: fixed argv lists only, never a shell."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

ALLOWED_PROGRAMS = ("docker", "git")


class ArgvError(ValueError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], *, timeout: float,
            env: Mapping[str, str] | None = None) -> CommandResult: ...


def check_argv(argv: object) -> list[str]:
    """Reject anything that is not a non-empty list/tuple of strings (a str would invite shell use)."""
    if isinstance(argv, (str, bytes)) or not isinstance(argv, (list, tuple)) or not argv:
        raise ArgvError("argv must be a non-empty list of strings")
    if not all(isinstance(a, str) and "\x00" not in a for a in argv):
        raise ArgvError("argv items must be strings without NUL")
    if argv[0] not in ALLOWED_PROGRAMS:
        raise ArgvError(f"program {argv[0]!r} is not allowed")
    return list(argv)


class SubprocessRunner:
    """subprocess.run with shell=False, a timeout, and no check (callers inspect the result)."""

    def run(self, argv: Sequence[str], *, timeout: float,
            env: Mapping[str, str] | None = None) -> CommandResult:
        args = check_argv(argv)
        merged = {**os.environ, **env} if env else None
        try:
            proc = subprocess.run(args, shell=False, capture_output=True, text=True,
                                  timeout=timeout, check=False, env=merged)
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", "timeout")
        except FileNotFoundError:
            return CommandResult(127, "", "program not found")
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)
