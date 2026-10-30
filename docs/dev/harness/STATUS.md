# Stream F (experiment harness) — STATUS

Branch `stream/harness` (from main 2113b85, with origin/main 8f7a6d3 merged in for `contracts/telemetry.md`). Last updated 2026-10-30.

**No experiment has been run against a real sandbox. No metric in this repository is measured. Every metric reads `pending` until runs are recorded.**

## Done (implemented and covered by tests that I ran)

| Area | State | Where |
|---|---|---|
| Scenario schema + EXP-01..10 + drafts EXP-11/12, validation | done | `harness/schemas/scenario.json`, `experiments/scenarios/`, `harness/scenario.py` |
| Injector interface, `FakeInjector`, `DockerInjector` (fixed argv, catalog + label validation) | done (argv-level only) | `harness/injector.py`, `harness/command.py` |
| Persistent-fault watcher (EXP-10) | done (container stop/kill only) | `PersistentFaultWatcher` |
| Run protocol, abort conditions, teardown, ground-truth NDJSON, metadata, `experiment_runs` file sink | done | `harness/runner.py`, `store.py`, `metadata.py`, `records.py` |
| Public-API client (urllib) | done, tested against a fake opener only | `harness/api_client.py` |
| Metrics (detection, diagnosis, recovery, safety) + trivial baseline detector | done | `harness/metrics.py`, `baseline.py` |
| Recoverability check (design time) | done | `harness/recoverability.py` |
| Reports (summary.json + Markdown per scenario) | done | `harness/report.py` |
| CLI | done | `harness/cli.py` |

## How to run

```bash
pip install pyyaml==6.0.3 jsonschema==4.26.0 pytest==9.2.0      # pins in harness/pyproject.toml
python3 -m pytest tests/harness -q                              # last run: 134 passed
python3 tests/contract/validate_contracts.py                    # last run: PASS
python3 -m harness validate-scenarios
python3 -m harness check-recoverability [--strict]
python3 -m harness report [--runs-dir experiments/runs] [--out experiments/results]
# needs a running sandbox and Docker (NOT run by me):
CD_API_URL=http://127.0.0.1:<port>/api/v1 HARNESS_API_TOKEN_FILE=<file> \
  python3 -m harness run EXP-01 --repeats 5 --controls 2 --seed 100
```

Environment (injector-only variables are `HARNESS_*` and are not shared with `CD_*` components): `CD_API_URL` (base URL **including** `/api/v1`), `HARNESS_API_TOKEN_FILE` (falls back to `CD_SESSION_TOKEN_FILE`),
`CD_CATALOG_PATH`, `HARNESS_RUNS_DIR`, `HARNESS_COMPOSE_FILE`, `HARNESS_COMPOSE_PROJECT`, `HARNESS_IMAGE_TAG_ENV` (default `CD_API_IMAGE_TAG`), `HARNESS_TOXIPROXY_URL`, `HARNESS_TOXIPROXY_TOKEN_FILE`, `HARNESS_TOXIPROXY_PROXIES`, `HARNESS_DOCKER_TIMEOUT`.

## Protocol summary

baseline (steady state held for `baseline_seconds`, no open incidents, else abort `steady_state_not_reached` with no injection) -> control (no fault, scenario duration; used for false positives) or inject (decoy first for EXP-09) ->
observe (poll the API; end when all incidents are terminal for `settle_seconds`, or at `detection_deadline_seconds` with no incident = recorded `detection_missed`) -> aborts (`blast_radius_exceeded`, `max_executions_exceeded`,
`action_blast_radius_exceeded`, `duration_cap`, `harness_error`) -> teardown (stop watcher, revert faults). Records per run in `experiments/runs/<run_id>/`: `metadata.ndjson`, `ground_truth.ndjson`, `api_records.ndjson`.
`t_inject` is taken after the injection command returns. Ground truth is never sent to the API (tested over the real urllib client: no URL, header or body contains scenario ids, run ids, fault types or cause ids).

## Assumptions (all unverified against real runs)

- Scenario thresholds, timings, abort caps and repetitions are provisional design values.
- `cause_id` equivalence classes are guesses (contract change request harness-2).
- Incidents are matched to a fault by time window and affected services (harness-1); harness and API clocks are assumed to agree (same host).
- Unauthorized-action count uses `GET .../remediation` decisions (harness-3).
- EXP-06 assumes a Toxiproxy proxy named `api-app-db` on the api->app-db path; EXP-07 assumes the compose file takes the api image tag from the `CD_API_IMAGE_TAG` variable; hogs assume `python3` inside the target container. None of this exists in the repo that I verified.
- EXP-08 uses `app-db` as the downstream dependency; restarting it is not allowed by the catalog, so the accepted outcome is escalation.
- The simulated operator approval (`--auto-approve`, default off) uses a neutral reason text so the system under test is not told about the harness; it is recorded as ground truth locally.
- Targets come only from the catalog, so infrastructure containers without the sandbox label (probes, prometheus, loki, promtail) can never be injected.

## Known gaps / not done

- Never run against real Docker, Toxiproxy or a live API. `DockerInjector` was only checked as exact argv lists through a fake runner; the hog scripts are only compiled, not executed in a container.
- Not implemented: `connection_hog` (EXP-05), `disk_fill` (EXP-11), `telemetry_outage` (EXP-12) injection (runs abort with `harness_error`); log-noise injection (flag is metadata only); the "restart worsens health" variant of EXP-10;
  persistent mode for hogs/deployments/toxics; a PostgreSQL `experiment_runs` sink (file sink only); full environment reset between runs (the harness reverts its own faults; `make reset` / `make up` belongs to infra and is not driven from here).
- `check-recoverability` is design-time only; "observed in runs" is `pending`. It currently reports EXP-03, 04, 05, 06, 09 and the draft EXP-11 as `not_recoverable` because `contracts/telemetry.md` has no CPU/memory/disk/DB-connection signals (harness-4).
- AI metrics (unsupported-claim rate, calibration, hallucination, value-add) are out of scope and not computed.
- Diagnosis accuracy uses the first diagnosis per incident; confidence calibration is not computed.
- The fake API in tests is my own model of the contract; shapes are hand-written against `contracts/schemas`, not machine-validated.
- **Pushing:** `git push` to `origin` returned HTTP 403 (no GitHub write access in this session), so the commits exist only in the local clone of this session unless pushed by someone with access.

## Contract change requests

`docs/dev/contract-change-requests/harness-1.md` .. `harness-4.md`.
