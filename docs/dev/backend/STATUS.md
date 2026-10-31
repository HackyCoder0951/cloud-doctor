# Stream B (backend core) - STATUS

Branch `stream/backend`, based on `main` 2113b85, with `main` 8f7a6d3 (`contracts/telemetry.md`) merged in. Contracts untouched
(`python3 tests/contract/validate_contracts.py` -> PASS before the last push). Nothing here depends on an LLM.

**No measured results are claimed.** Every scenario fixture is synthetic (hand-modelled from `docs/11-experiments/` and
`contracts/telemetry.md`), not a recording of a real sandbox run. Confidence values are a ranking aid, not probabilities. No
accuracy, MTTD or MTTR number is reported anywhere.

## How to run

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e backend[dev]          # exact pins in backend/pyproject.toml (FastAPI 0.162.0, Pydantic 2.14.2, SQLAlchemy 2.1.6, ...)
python -m pytest tests/backend       # from the repo root; `cd backend && python -m pytest` also works
python -m backend.demo_replay        # read-only replay of the synthetic Redis-outage fixture; prints the Markdown report
python -m backend.demo_replay --scenario worker_crash --until 140 --json
```

Optional PostgreSQL tests (skipped unless `CD_DATABASE_URL` is set; use an EMPTY scratch UTF8 database, the test drops `public`):

```bash
CD_DATABASE_URL=postgresql://user@127.0.0.1:5432/scratch python -m pytest tests/backend
```

Fixtures are generated: `python tests/backend/fixtures/scenarios.py` (a test fails if the committed JSON drifts from the generator).

### Last observed test results (this session, Python 3.13.17, Linux)

| Run | Result |
|---|---|
| `python -m pytest tests/backend` (no env) | 146 passed, 4 skipped (the 4 PostgreSQL tests) |
| same with `CD_DATABASE_URL` -> local **PostgreSQL 16.15** scratch DB | 150 passed |

PostgreSQL 16 was used because it was what the container had; the contract targets PostgreSQL 18 and the SQL was **not** run on 18.
Python 3.12 was not tested (3.13 only). No Docker, network, Prometheus, Loki or LLM was used by any test.

## Done (implemented and exercised by tests)

| # | Item | Notes |
|---|---|---|
| 1 | Domain layer | Pydantic v2 models for all contract objects; `validate_against_contract()` (jsonschema 2020-12 + `referencing`, real RFC 3339 `date-time` check); in-memory repo (default) and SQLAlchemy/PostgreSQL repo with tables per `contracts/db/schema.sql` (the frozen SQL is applied verbatim); audit hash chain exactly per `audit_event.json` (reproduces the example hash; DB triggers reject UPDATE/DELETE - verified on PG 16). Canonical JSON/hash helpers reproduce the example `payload_hash`, `plan_hash`, audit `hash`. |
| 2 | Telemetry clients | `PromClient`/`LogClient`/`ChangeFeed`/`Prober` protocols; httpx implementations for Prometheus, Loki and the synthetic probe; fixture fakes. A failed/timed-out query is `error`/`timeout` + `collection_failed`, never "no data" (tested at client, collector, API and report level). |
| 3 | Detector | `backend/config/detector.yaml`: service down (`up==0 OR cd_service_up==0`), error ratio with traffic floor (2 rps, > the 1 rps minimum in telemetry.md), p95, queue growth, queue-series absence (a signal), `cd_dependency_up`, restart via `process_start_time_seconds` (alert `event_time` = process start), optional memory trend, `absent()` telemetry-gap rule. Tri-state signals + enter-after-N/leave-after-M hysteresis; hold on missing data never resolves an alert. Three missing-signal states; expected-state registry with owner/reason/expiry; expected-down is suppressed, recorded, and re-emitted unsuppressed on expiry. Health HEALTHY/DEGRADED/UNHEALTHY/UNKNOWN. |
| 4 | Incidents + timeline | Grouping by connected component **of the subgraph induced by affected services** + time window; unrelated concurrent fault -> separate incident; state machine with `InvalidTransition`; sweep of self-recovered incidents; relapse flag; timeline keeps `event_time` vs `collected_at`, de-duplicates, keeps suppressed events. |
| 5 | Evidence collector | NUL stripped before storing; `payload_hash` over canonical JSON before insert; logs untrusted with count-only summaries; snapshots of ALL catalog services (so contradicting evidence is citable); `snapshot_before_action`. |
| 6 | Deterministic RCA | Candidates from topology, change events/`build_info` history, signatures; scoring = coverage x independent-signal-type factor x (1 - contradiction share), temporal-only cap 0.30, generic local-fault cap 0.35, max 0.95, never `confirmed`. Output has contradicting claims, alternatives (incl. considered-and-rejected causes), unknowns. Tested on: Redis cascade, worker crash, memory exhaustion (+recurrence), bad deployment (with and without a change feed), false-correlation decoy (decoy refuted, not first), DB saturation (exhaustion, not "down"), restart-before-recovery (never a cause), telemetry failure. |
| 7 | C0 report | JSON valid against `report.json` (`mode: deterministic`, `mitigated` separate from `root_cause_confirmed`) + escaped Markdown. |
| 8 | Remediation | Planner (catalogue mapping), plan_hash via local helper, state machine with attempts (max 2), cooldown (20 s), circuit breaker (human reset), regression abort, escalation, strategy-change rule; `ActuatorClient` protocol, in-process fake, unix-socket client; HMAC-SHA256 signing with the key from `CD_SIGNING_KEY_FILE` (refuses missing/short/group-or-world-readable keys); `policy_adapter.py` with real-`invariants` switch and a clearly marked local stub. |
| 9 | Verifier | Seven checks over a configurable window comparing baseline/pre/post; `passed: null` -> `unverifiable`; taxonomy recovered/partial/failed/regression/relapse/unverifiable; independent probe through the catalog `published_probe_url`. |
| 10 | API | Every operation in `contracts/openapi.yaml` is routed (test asserts it); cookie login from `CD_SESSION_TOKEN_FILE`; Idempotency-Key on mutating routes; approve/reject bound to `plan_hash`; SSE with `Last-Event-ID`; `/status` ok/degraded/fail_closed; sanitized error bodies. `python -m backend.demo_replay` works offline. |
| 11 | Tests | Control run, flapping, low traffic, decoy, telemetry failure, contract conformance of every emitted object, poisoned-log tests, optional PG tests. |

## Partial / not done / known gaps (be aware before relying on this)

- **Real `invariants` and actuator are not integrated.** `policy_adapter.py` uses a LOCAL STUB of I-01..I-08 unless the real package exposes the public API (the empty `invariants/` namespace directory is detected and ignored). The switch is untested against the real package. The unix-socket client was only tested against a tiny in-test HTTP-over-unix server, not Stream C's actuator. `/status` says "LOCAL STUB".
- **HTTP clients and PromQL templates were never run against a real Prometheus/Loki/sandbox** (httpx mock transport only). Metric names follow `contracts/telemetry.md`; `process_resident_memory_bytes` / `process_cpu_seconds_total` (memory/CPU candidates) are **not** in that contract - assumed from the standard process collector. The telemetry contract has no DB connection gauge, so DB saturation relies on log signatures + `cd_dependency_up` + probe state, and says so in `unknowns`.
- **No change feed in live wiring** (`services_from_env` uses a feed that reports "not configured"). Deploy detection then relies on the `build_info` version history (tested), and deploy/container-stop events are missing from live evidence (reported as an unknown, never as "no change").
- Layer 2 (OPA) is not wired (Layer-2-less mode, the documented safe default).
- No Alembic migration: the PG tables come from applying the frozen `schema.sql`; `SqlRepository` does not create schema. Id allocation uses `max()+1` (collisions fail on the primary key).
- State that lives only in memory (lost on restart): sessions, idempotency store, login-failure counter (global, not per-IP), expected-state registry (no API to declare), remediation engine state (cooldown, circuit breaker, pending approvals), orchestrator bookkeeping. The action budget "M actions per window" from remediation-loops.md is not implemented; merging two already-open incidents bridged by a later alert is not implemented (the alert joins the earliest).
- `RemediationEngine.run` holds one lock and the verifier sleeps through the stability window, so remediation of one incident blocks others while it verifies; the background orchestrator thread is started by `create_app(start_background=True)` but only `Orchestrator.step()` is tested.
- Verified-recovery semantics for the Redis case rely on a partial re-check: a first window can be `partial` while the error ratio is still decaying; the engine re-verifies once.
- Contract-change request filed: `docs/dev/contract-change-requests/backend-1.md` (queue backlog invisible while the worker is dead).

## Assumptions (documented, not contract text)

1. **Redis restart is `medium` risk (needs approval)** per `streams.md` I-03 and `remediation-patterns.md`; `docs/11-experiments/redis-failure.md` calls it low. The stricter rule is implemented; worker/api restarts are `low`. Restarting a database is `high` (never executed; escalate).
2. Incident grouping uses connected components of the subgraph induced by affected services, because the full catalog graph is one connected component.
3. `Idempotency-Key` is required on `diagnose`, `approve`, `reject` (the routes that declare it in `openapi.yaml`); `login`/`logout` do not declare it and are exempt. A missing/invalid key is HTTP 400.
4. Hypothesis rows in PostgreSQL store the diagnosis-level `engine_version` and `recommended_action` under a reserved `_diagnosis` key in the rank-1 `body` (the schema has no column for them); it is stripped on load.
5. `ok=True, requires_approval=True` from `validate_plan` is read as "passes, pending approval"; if the real package returns `ok=False` with only `I-03` and no approval, the adapter also maps it to `allow_with_approval`.
6. Canonical JSON uses `ensure_ascii=False` (UTF-8, as streams.md says); identical to ASCII-escaped output for the ASCII-only objects in the contracts.
7. Strategy-change rule: a repeat of a failed action on the same target is allowed only if the new diagnosis names a different top cause; otherwise the planner escalates (so with an unchanged diagnosis exactly one action runs). The attempt budget/cooldown/breaker path is tested with a planner that permits the repeat.
8. A lone restart is informational (`opens_incident: false`); it is recorded and attached to related incidents' timelines.
9. Scenario timing in fixtures uses 5 s resolution and a one-step instant lookback.
10. The observation from the infra stream (stop Redis -> signals in 6-15 s, N=1) shaped the fixtures' *shape* only; it is not used as a result.
