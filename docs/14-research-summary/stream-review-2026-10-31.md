# Stream branch review (coordinator, 2026-10-31)

Scope: heads fetched from the remote on this date. Checks run by the coordinator in a cloud container, not by the stream sessions. **Code was not read line by line; this is a conformance and reproducibility check, not a code review.** Nothing is merged.

| Branch | Head | Commits / files | Contracts changed since merge-base | Attribution lines | Go files | Reproduced result |
|---|---|---|---|---|---|---|
| `stream/backend` | `9ed470d` | 12 / 81 | none | 0 | 0 | `pytest tests/backend`: 146 passed, 4 skipped (PostgreSQL tests not run here) |
| `stream/policy` | `c59e915` | 4 / 45 | none | 0 | 0 | 317 passed + 1 failed, 2 skipped; **flaky, see below** |
| `stream/frontend` | `f367e38` | 7 / 77 | none | 0 | 0 | `npm ci`, `tsc --noEmit`, Vitest 132 passed (9 files). Build, nginx e2e and Chromium run **not** reproduced |
| `stream/harness` | `5a72e37` | 9 / 53 | none | 0 | 0 | `pytest tests/harness`: 134 passed |
| `stream/infra-p7f2rn` | this branch | 25 vs main | none | 0 | 0 | `tests/integration/gate_g1.sh` PASS (17 smoke checks) |

`validate_contracts.py` PASS on every branch. All streams state that no experiment was run and no metric is measured.

## Findings
1. **Flaky policy test.** `tests/actuator/test_act_server.py::test_unknown_routes_and_methods` failed with `BrokenPipeError` in 2 of 8 full-suite runs here (passes alone and in most runs). The stream reported 318 passed; that was not wrong for its run, but the suite is not deterministic. Not fixed from here; owner: stream C. N=8, so the failure rate is only roughly known.
2. **Rego unverified.** `policy/rego/` was never executed (`opa test`/`opa check` skipped: no `opa` binary). B4 in the acceptance plan depends on it. Needs a run with `opa` before G3.
3. **Postgres audit sink not started** (actuator refuses `CD_AUDIT_SINK=postgres`); the audit trail is NDJSON only.
4. **Harness:** EXP-05/11/12 injection not implemented; EXP-03/04/05/06/09/11 are flagged not recoverable from telemetry (harness-4). Diagnosis accuracy is not meaningful until `cause_id` values are reconciled (harness-2).
5. **Worker-crash signal confirmed independently.** backend-1 (from the contract text) and the N=1 sandbox observation in `docs/dev/infra/STATUS.md` agree: `queue_depth` disappears while the worker is dead. The backend `worker_crash` fixture still models it as rising; fix together with backend-1.

## Contract change requests awaiting a user decision (none applied)
| ID | Subject | Affects |
|---|---|---|
| backend-1 | export queue length from the probe sidecar (`cd_queue_length`) so backlog is visible when the worker or Redis is down | telemetry contract, Stream A, B fixture |
| policy-1 | allow `A-*` rule ids in actuator `validate_response` | `contracts/schemas/actuator.json` |
| policy-2 | signed `attestations` in the envelope so the actuator can re-check I-05/I-07; define audit hash for absent `incident_id` | envelope schema, B, C |
| frontend-1 | `404` on `getReport` when no diagnosis yet | `openapi.yaml`, B |
| frontend-2 | state that the backend serves `/api/v1` and the proxy forwards it unchanged | docs, B, nginx |
| frontend-3 | `last_event_id` query parameter on `/stream`; `GET /auth/me` for role | `openapi.yaml`, B |
| harness-1 | no API input sets `incident.run_id` (harness matches by time window instead) | optional |
| harness-2 | freeze the `cause_id` vocabulary | B RCA, F scenarios, evaluation validity |
| harness-3 | approval semantics and audit `detail` keys | B, C, F |
| harness-4 | no CPU, memory, disk or DB-connection metrics in the telemetry contract | A, B, F; six scenarios not recoverable otherwise |

Highest impact before G2/G3: backend-1, harness-2, harness-4, policy-2.

## Not verified by the coordinator
Frontend `npm run build`, nginx and Chromium e2e; PostgreSQL 18 for the backend; any cross-stream integration (backend against the real sandbox, actuator against real Docker).
