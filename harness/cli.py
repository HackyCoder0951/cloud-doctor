"""python -m harness validate-scenarios | run <scenario> --repeats N | report | check-recoverability"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from harness.api_client import HttpApiClient
from harness.catalog import Catalog
from harness.clock import SystemClock
from harness.command import SubprocessRunner
from harness.injector import DockerInjector, InjectorConfig
from harness.metadata import MetadataCollector
from harness.paths import RESULTS_DIR, RUNS_DIR, SCENARIO_DIR, catalog_path
from harness.recoverability import check_all
from harness.records import load_runs
from harness.report import write_reports
from harness.runner import Runner
from harness.scenario import ScenarioError, find_scenario, load_all, load_scenario, schema_errors, semantic_errors, warnings
from harness.store import FileExperimentRunsSink, FileRunStore

import yaml


def _catalog() -> Catalog:
    return Catalog.load(catalog_path())


def cmd_validate(args, out: TextIO) -> int:
    catalog = _catalog()
    bad = 0
    for p in sorted(Path(args.dir).glob("exp-*.yaml")):
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        errs = schema_errors(raw) or semantic_errors(raw, catalog, p.stem)
        if errs:
            bad += 1
            out.write(f"FAIL {p.name}: {'; '.join(errs)}\n")
        else:
            warn = warnings(raw)
            out.write(f"ok   {p.name} ({raw['status']})" + (f"  WARN: {'; '.join(warn)}" if warn else "") + "\n")
    out.write(f"{'FAILED' if bad else 'all scenarios valid'}\n")
    return 1 if bad else 0


def cmd_recoverability(args, out: TextIO) -> int:
    results = check_all(load_all(_catalog(), args.dir), _catalog())
    worst = 0
    for sid, r in results.items():
        out.write(f"{sid}: {r['status']}  missing={r['missing_cause_signals'] or '-'} unverified={r['unverified_cause_signals'] or '-'} "
                  f"action_missing={r['missing_action_signals'] or '-'}  observed_in_runs=pending\n")
        worst |= r["status"] == "not_recoverable"
    out.write("Design-time check only: it does not show the signals appeared in a run.\n")
    return 1 if (args.strict and worst) else 0


def cmd_report(args, out: TextIO) -> int:
    catalog = _catalog()
    scenarios = load_all(catalog, args.dir)
    records = load_runs(args.runs_dir)
    path = write_reports(records, scenarios, catalog, args.out)
    out.write(f"wrote {path} from {len(records)} run record(s)\n")
    return 0


def _default_runner_factory(catalog: Catalog) -> Runner:
    url = os.environ.get("CD_API_URL")
    if not url:
        raise SystemExit("CD_API_URL is not set")
    token = None
    tf = os.environ.get("HARNESS_API_TOKEN_FILE") or os.environ.get("CD_SESSION_TOKEN_FILE")
    if tf:
        token = Path(tf).read_text(encoding="utf-8").strip()
    cmd = SubprocessRunner()
    return Runner(api=HttpApiClient(url, token), injector=DockerInjector(catalog, cmd, InjectorConfig.from_env()),
                  store=FileRunStore(Path(os.environ.get("HARNESS_RUNS_DIR", RUNS_DIR))), clock=SystemClock(),
                  collector=MetadataCollector(cmd, catalog, url),
                  sink=FileExperimentRunsSink(Path(os.environ.get("HARNESS_RUNS_DIR", RUNS_DIR)) / "experiment_runs.ndjson"))


def cmd_run(args, out: TextIO, factory: Callable[[Catalog], Runner]) -> int:
    catalog = _catalog()
    try:
        scenario = find_scenario(catalog, args.scenario, args.dir)
    except (ScenarioError, FileNotFoundError) as e:
        out.write(f"cannot load scenario: {e}\n")
        return 2
    runner = factory(catalog)
    variant = {"llm": args.llm, "log_noise": args.log_noise}  # metadata only
    failures = 0
    plan = [("control", i) for i in range(1, args.controls + 1)] + [("experimental", i) for i in range(1, args.repeats + 1)]
    for kind, i in plan:
        s = runner.run(scenario, kind=kind, seed=args.seed + i, repeat_index=i, variant=variant,
                       allow_draft=args.allow_draft, auto_approve=args.auto_approve)
        out.write(f"{s.run_id} {s.kind} {s.status}" + (f" ({s.abort_reason})" if s.abort_reason else "") + "\n")
        failures += s.status != "completed"
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m harness")
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate-scenarios")
    v.add_argument("--dir", default=str(SCENARIO_DIR))
    r = sub.add_parser("run")
    r.add_argument("scenario", help="EXP-01 .. EXP-12 or a path")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--controls", type=int, default=0, help="control runs (no fault) before the experimental runs")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--llm", choices=["off", "on"], default="off", help="metadata only; the harness never calls an LLM")
    r.add_argument("--log-noise", choices=["off", "on"], default="off", help="metadata only in this version")
    r.add_argument("--auto-approve", action="store_true", help="simulate the operator approving accepted medium-risk plans")
    r.add_argument("--allow-draft", action="store_true")
    r.add_argument("--dir", default=str(SCENARIO_DIR))
    rp = sub.add_parser("report")
    rp.add_argument("--runs-dir", default=str(RUNS_DIR))
    rp.add_argument("--out", default=str(RESULTS_DIR))
    rp.add_argument("--dir", default=str(SCENARIO_DIR))
    c = sub.add_parser("check-recoverability")
    c.add_argument("--strict", action="store_true", help="exit 1 when a scenario is not recoverable")
    c.add_argument("--dir", default=str(SCENARIO_DIR))
    return p


def main(argv: list[str] | None = None, out: TextIO | None = None,
         runner_factory: Callable[[Catalog], Runner] | None = None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    if args.command == "validate-scenarios":
        return cmd_validate(args, out)
    if args.command == "check-recoverability":
        return cmd_recoverability(args, out)
    if args.command == "report":
        return cmd_report(args, out)
    if args.repeats < 1 or args.controls < 0:
        out.write("--repeats must be >= 1 and --controls >= 0\n")
        return 2
    return cmd_run(args, out, runner_factory or _default_runner_factory)
