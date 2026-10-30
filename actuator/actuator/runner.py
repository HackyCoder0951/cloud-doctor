"""Injectable command runner. The only place that starts a process; never uses a shell."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Protocol, Sequence

_DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class CommandError(Exception):
    """The command could not be run or timed out."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], timeout: float) -> CommandResult: ...


class SubprocessRunner:
    """argv list, shell=False, bounded runtime, no stdin, environment limited to PATH."""

    def run(self, argv: Sequence[str], timeout: float) -> CommandResult:
        argv = list(argv)
        if not argv or not all(isinstance(a, str) for a in argv):
            raise CommandError("argv must be a non-empty list of strings")
        try:
            proc = subprocess.run(
                argv, shell=False, capture_output=True, text=True, timeout=timeout, check=False,
                stdin=subprocess.DEVNULL, env={"PATH": os.environ.get("PATH", _DEFAULT_PATH)},
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandError("command timed out") from exc
        except OSError as exc:
            raise CommandError(f"command could not be started: {type(exc).__name__}") from exc
        return CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")
