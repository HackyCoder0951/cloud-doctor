"""Repository-relative locations used by the harness."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = REPO_ROOT / "experiments" / "scenarios"
RUNS_DIR = REPO_ROOT / "experiments" / "runs"
RESULTS_DIR = REPO_ROOT / "experiments" / "results"
SCENARIO_SCHEMA = Path(__file__).resolve().parent / "schemas" / "scenario.json"


def catalog_path(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    value = env.get("CD_CATALOG_PATH")
    return Path(value) if value else REPO_ROOT / "infra" / "catalog" / "services.yaml"
