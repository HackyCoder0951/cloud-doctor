"""Run records: NDJSON files per run, plus an optional experiment_runs sink with a file implementation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
FILES = {"metadata": "metadata.ndjson", "ground_truth": "ground_truth.ndjson", "api": "api_records.ndjson"}


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class RunWriter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._handles = {k: open(directory / name, "a", encoding="utf-8") for k, name in FILES.items()}

    def _write(self, stream: str, obj: dict) -> None:
        h = self._handles[stream]
        h.write(dumps(obj) + "\n")
        h.flush()

    def metadata(self, obj: dict) -> None:
        self._write("metadata", obj)

    def ground_truth(self, obj: dict) -> None:
        self._write("ground_truth", obj)

    def api(self, obj: dict) -> None:
        self._write("api", obj)

    def close(self) -> None:
        for h in self._handles.values():
            h.close()


class FileRunStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def open(self, run_id: str) -> RunWriter:
        if not RUN_ID_RE.match(run_id):
            raise ValueError("invalid run id")
        d = self.root / run_id
        d.mkdir(parents=True, exist_ok=False)
        return RunWriter(d)


class ExperimentRunsSink(Protocol):
    """Mirror of the experiment_runs table (contracts/db/schema.sql). Harness writes only."""
    def upsert(self, row: dict) -> None: ...


class FileExperimentRunsSink:
    """Append-only NDJSON; the last line per run_id wins. A PostgreSQL sink is NOT implemented."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def upsert(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(dumps(row) + "\n")
