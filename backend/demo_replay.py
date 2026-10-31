"""Read-only demo: replay recorded (synthetic) fixtures through detector -> incident -> evidence -> RCA -> report.

    python -m backend.demo_replay [--scenario redis_outage] [--fixtures DIR] [--until SECONDS] [--json]

No Docker, no network, no LLM. Nothing is executed: the loop stops at the report (remediation is not wired here).
The fixtures under tests/backend/fixtures/ are synthetic scenarios modelled on the docs, NOT recordings of a real run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.detector.config import DetectorConfig
from backend.domain.catalog import Catalog
from backend.domain.clock import FakeClock
from backend.domain.contracts import REPO_ROOT, validate_against_contract
from backend.repositories import MemoryRepository
from backend.services import Orchestrator, build_services
from backend.telemetry.fakes import (FixtureChangeFeed, FixtureLogClient, FixtureProber, FixturePromClient, Scenario,
                                     build_query_index)

DEFAULT_FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures"


def replay(scenario_path: Path, until_s: float | None = None, repo=None):
    cat, cfg = Catalog.load(), DetectorConfig.load()
    sc = Scenario.load(scenario_path)
    clock = FakeClock(sc.at(cfg.poll_interval_seconds))
    svc = build_services(repo or MemoryRepository(), cat, cfg, clock, FixturePromClient(sc, build_query_index(cfg, cat)), FixtureLogClient(sc),
                         FixtureChangeFeed(sc), FixtureProber(sc), actuator=None)  # no actuator: strictly read-only
    orch = Orchestrator(svc, remediate=False)
    t = cfg.poll_interval_seconds
    end = until_s if until_s is not None else sc.duration
    while t <= end:
        clock.set(sc.at(t))
        orch.step()
        t += sc.step
    return svc, sc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", default="redis_outage")
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--until", type=float, default=140.0, help="replay up to this many seconds into the scenario")
    ap.add_argument("--json", action="store_true", help="print the JSON report instead of Markdown")
    a = ap.parse_args(argv)
    path = Path(a.fixtures) / f"{a.scenario}.json"
    if not path.exists():
        print(f"fixture not found: {path}", file=sys.stderr)
        return 2
    svc, sc = replay(path, a.until)
    incidents = svc.repo.list_incidents()
    if not incidents:
        print(f"scenario {sc.name!r}: no incident opened up to t={a.until:.0f}s (control runs are expected to end here).")
        return 0
    print(f"<!-- replay of synthetic fixture {sc.name!r} up to t={a.until:.0f}s; {len(incidents)} incident(s); read-only, nothing executed -->\n")
    for inc in sorted(incidents, key=lambda i: i.opened_at):
        if svc.repo.latest_diagnosis(inc.incident_id) is None:
            continue
        rep = svc.reports.build(inc.incident_id)
        validate_against_contract(rep, "report")
        print(json.dumps(rep, indent=2) if a.json else svc.reports.render_markdown(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
