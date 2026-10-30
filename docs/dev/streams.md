# Parallel Work Streams — Ownership, Interfaces and Rules

**Contract version 1 is FROZEN.** Every stream builds against `contracts/` and must not edit it. If a contract is wrong or incomplete, write a change request (see the end of this file) and carry on with a documented assumption.

Context: Cloud Doctor is a research-first system (read `README.md`, `docs/10-architecture/tech-stack.md`, `docs/13-decisions/adr-005-policy-engine.md`, `adr-007-implementation-languages.md`, `docs/14-research-summary/mvp-plan-5-nov.md`). Deterministic core with optional AI; **the AI stream is built last and nothing here may depend on any LLM API.** Language: **Python (>= 3.12) and TypeScript only. No Go.**

## Streams and directory ownership

| Stream | Branch | Owns (only edit inside) | Runs where |
|---|---|---|---|
| **A — Infra and sandbox** | `stream/infra` | `infra/` (except `infra/nginx/`), root `Makefile` | local machine (Docker) |
| **B — Backend core** | `stream/backend` | `backend/`, `tests/backend/` | cloud |
| **C — Policy and actuator** | `stream/policy` | `invariants/`, `actuator/`, `policy/`, `tests/invariants/`, `tests/actuator/`, `tests/policy/` | cloud |
| **D — Frontend** | `stream/frontend` | `frontend/`, `infra/nginx/` | cloud |
| **F — Experiments harness** | `stream/harness` | `harness/`, `experiments/`, `tests/harness/` | cloud |
| **E — AI (LAST)** | `stream/ai` | `ai/`, `tests/ai/` | not started until A–D and F reach their gates |

Shared and read-only for everyone: `contracts/`, `tests/contract/`, `docs/` (a stream may add notes under `docs/dev/<stream>/` only). Streams never edit each other's directories.

## Rules for every stream

1. Read the contracts first: `contracts/schemas/*.json`, `contracts/openapi.yaml`, `contracts/actuator.openapi.yaml`, `contracts/db/schema.sql`, `contracts/examples/*`, `infra/catalog/services.yaml`.
2. Run `python3 tests/contract/validate_contracts.py` (needs `pyyaml`, `jsonschema`) before every push; it must stay green.
3. **No Docker, sandbox, network access to Prometheus/Loki or any LLM may be required to run your tests.** Use fakes and recorded fixtures. Tests that need Docker or a database are marked optional and skipped when unavailable.
4. No secrets in the repository. Secrets and paths come from environment variables (names below). Never print secrets.
5. Dependencies: pin exact versions in your package's own `pyproject.toml` / `package.json`. Keep `invariants/` and the actuator's core on the **standard library only**.
6. Commits: small, logical, conventional-commit style, detailed bodies, **no co-author or attribution lines of any kind**. Push your branch at least hourly. Do **not** merge into `main` and do **not** open pull requests unless told to.
7. Be honest: write what is implemented, what is stubbed and what was not tested in `docs/dev/<stream>/STATUS.md`. Never claim a result that was not run. No measured numbers are claimed anywhere without a recorded run.
8. Untrusted data: log lines and evidence text are untrusted. Never execute them, never use them to build commands, never render them as HTML.
9. Fail closed: when something safety-relevant is missing or errors, deny the action.
10. Finish with a short `docs/dev/<stream>/STATUS.md` (done / partial / not started, how to run tests, known gaps, assumptions, contract change requests).

## Environment variables (names are part of the contract)

| Variable | Used by | Meaning |
|---|---|---|
| `CD_DATABASE_URL` | backend | PostgreSQL URL (optional in tests) |
| `CD_PROMETHEUS_URL` | backend | default `http://127.0.0.1:9090` |
| `CD_LOKI_URL` | backend | default `http://127.0.0.1:3100` |
| `CD_CATALOG_PATH` | backend, actuator, invariants | default `infra/catalog/services.yaml` |
| `CD_ACTUATOR_SOCKET` | backend, actuator | unix socket path of the actuator |
| `CD_SIGNING_KEY_FILE` | backend, actuator | file holding the HMAC key (mode 0600); never inline |
| `CD_SESSION_TOKEN_FILE` | backend | file holding the shared MVP login token |
| `CD_AUDIT_SINK` | actuator | `postgres` or an NDJSON file path (tests use a file) |

## Interface: `invariants` package (Stream C provides, Stream B consumes)

Standard library only. Public API (stable names; Stream B codes against a stub until C lands):

```python
invariants.__version__: str                                  # e.g. "inv-0.1"
invariants.canonical_json(obj) -> bytes                      # sorted keys, separators (',',':'), UTF-8, no NaN
invariants.sha256_tag(data: bytes) -> str                    # "sha256:<64 hex>"
invariants.plan_hash(plan: dict) -> str                      # hash of the plan WITHOUT its plan_hash field
invariants.sign_envelope(envelope_without_signature: dict, key: bytes) -> str   # HMAC-SHA256 hex over canonical_json
invariants.verify_envelope(envelope: dict, key: bytes) -> bool                  # constant-time compare
invariants.Catalog.load(path) -> Catalog                     # parses infra/catalog/services.yaml (YAML via a tiny parser or json fallback)
invariants.validate_plan(plan: dict, ctx: PolicyContext) -> ValidationResult
```

`PolicyContext` fields: `catalog`, `now` (datetime), `attempts_used(incident_id, service, action_id) -> int`, `last_attempt_at(incident_id, service, action_id) -> datetime | None`, `circuit_open(incident_id) -> bool`, `known_evidence_ids: set[str]`, `diagnosis_validated: bool`, `top_cause_service: str | None`, `approval: dict | None`, `container_labels(container: str) -> dict` (actuator-side check).
`ValidationResult`: `ok: bool`, `rule_ids: list[str]`, `reasons: list[str]`, `requires_approval: bool`.

Layer 1 rules (ids are part of the contract; `decision.json` uses them):

| Id | Invariant |
|---|---|
| I-01 | Action is in the catalogue and parameters match the typed schema and bounds (`plan.json`) |
| I-02 | Target service is in the catalog, its container carries label `cloud-doctor.sandbox=true`, and the action is in that service's `allowed_actions` |
| I-03 | Risk ceiling: `high` is never executable; `medium` requires a valid approval bound to `plan_hash`; `restart_service` on a stateless service is `low`, on a cache or queue holder `medium` unless the catalog says otherwise (use the plan's own `risk_class`, rejecting a class lower than the catalogue's rule) |
| I-04 | Attempt budget (default max 2 per incident+service+action), cooldown (default 20 s), circuit breaker not open |
| I-05 | Evidence precondition: every `evidence_refs` id exists, and the diagnosis passed validation (`diagnosis_validated`) |
| I-06 | No parameter is derived from free text: string params match their patterns; `service` must be an exact catalog name |
| I-07 | Dependency-aware rule: do not restart a victim service when `top_cause_service` is a different service that is down, unless the plan targets that cause |
| I-08 | Any internal error, missing input or timeout denies (fail closed) |

## Interface: actuator (Stream C provides, Stream B consumes)

HTTP over the unix socket `CD_ACTUATOR_SOCKET` exactly as in `contracts/actuator.openapi.yaml`. Stream B ships an `ActuatorClient` protocol with a fake for tests; Stream C ships the server plus a test client. The only executing action in the MVP is `docker restart <container>` as a fixed `argv` list (never a shell), preceded by a fixed `docker inspect` argv to verify the label. Tests use an injectable command runner; no real Docker call is made in tests.

## Interface: telemetry clients (Stream B owns)

`PromClient` and `LogClient` protocols with HTTP implementations and fixture-based fakes under `tests/backend/fixtures/`. Failed queries must yield evidence with status `error`/`timeout` and `missing_signal_state` set — never "no data".

## Interface: harness (Stream F) and backend (Stream B)

The harness injects faults and records ground truth in its **own** store (NDJSON + `experiment_runs`). The backend never reads ground truth; the only link is an optional `run_id` stored on the incident. The harness reads incidents, audit and reports through the public API (`contracts/openapi.yaml`) using fakes in tests.

## Interface: frontend (Stream D) and backend (Stream B)

Only through `contracts/openapi.yaml`. D builds against a mock server serving `contracts/examples/*` (plus its own mock data for list endpoints). Static export, no Next.js server features; evidence and logs rendered as escaped text only.

## What "done" means per stream (for the 5 Nov gates)

- **B:** detector (thresholds with consecutive-poll hysteresis, minimum-traffic guard, absence rules, three missing-signal states), incident manager and timeline, evidence collector, deterministic RCA with contradicting evidence and unknowns, C0 report (JSON valid against `report.json` + Markdown), remediation state machine with attempts, cooldown, circuit breaker and escalation, verifier (7 checks, fail closed), API implementing `openapi.yaml` with in-memory and PostgreSQL repositories, SSE stream. Tests green without Docker.
- **C:** `invariants` complete with tests for every rule and adversarial cases; actuator with signature, expiry, nonce-replay and plan-hash checks, idempotency, injectable runner, audit sink with hash chain; Layer 2 OPA client with fail-closed handling (HTTP 200 without `result` ⇒ deny, timeouts, stale/unsigned bundle) and Rego policies plus tests that run if `opa` exists.
- **D:** Next.js (static export) dashboard with all views, typed client generated from the OpenAPI, SSE hookup, mock server, tests including XSS-inert rendering, nginx config with security headers.
- **F:** scenario configs for the ten experiments from `docs/11-experiments/`, injector interface with a fake and a Docker implementation using fixed argv, run protocol, ground-truth recording, metric computation (detection, diagnosis, recovery, safety) from run records, results templates that print "pending" unless data exists, CLI.

## Contract change requests

Create `docs/dev/contract-change-requests/<stream>-<n>.md` stating: what is wrong, the proposed change, impact on other streams, and the workaround you used. The coordinator decides; until then keep working with your documented assumption.
