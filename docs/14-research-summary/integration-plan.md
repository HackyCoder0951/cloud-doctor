# Integration plan for gates G2–G5 (draft; nothing here has been run)

Coordinator draft. Stream branches are **not merged** until the user decides. Every step below is a plan; status is reported only in `sprint-status.md`.

## Order of integration (onto an `integration` branch, never `main`)
1. `stream/infra` (A) — already runnable: `tests/integration/gate_g1.sh`.
2. `stream/policy` (C) — invariants + actuator are self-contained; run its tests first, then `contracts/actuator.openapi.yaml` conformance.
3. `stream/backend` (B) — needs A's metrics (`contracts/telemetry.md`) and C's actuator API.
4. `stream/harness` (F) — needs A and B.
5. `stream/frontend` (D) — needs B's `contracts/openapi.yaml`; can be checked against fixtures independently.
6. `stream/ai` (E) — last; only after G4. Nothing in 1–5 may import or call an LLM client.

## Per-gate checks (to be scripted when the branches exist)
| Gate | Check | Script |
|---|---|---|
| G1 | contracts valid, smoke 17 checks | `tests/integration/gate_g1.sh` (exists) |
| G2 | Redis outage: one incident, evidence stored, read-only (no actuator call) | pending: needs B and F |
| G3 | closed loop: recommend → policy → actuator → verified → report; persistent fault escalates (A3–A6) | pending: needs B, C, F |
| G4 | every implemented scenario end to end with the LLM client package absent/blocked (A7) | pending |
| G5 | full test suites green, A1–A8, demo rehearsal | pending |

## Review checklist for each stream branch
- `python3 tests/contract/validate_contracts.py` still passes with the branch's changes.
- No frozen file under `contracts/` modified without an ADR/contract-change note.
- STATUS.md claims map to a command that was run; measured numbers have run counts; unmeasured = "pending".
- No Go; no attribution lines in commits; no secrets; no LLM dependency outside `ai/`.
- Detectors use `cd_service_up` and `up`/absence rules, not `up` of probe-scraped services or a rising `queue_depth` for worker crashes (see `docs/dev/infra/STATUS.md`).

## Coordinator check log
- 2026-10-30 (cloud, `git fetch --all`): remote branches are `main` (ee4aaa6), `stream/infra`, `stream/infra-p7f2rn`. **`stream/backend`, `stream/policy`, `stream/frontend`, `stream/harness` have not been pushed**, so nothing from them could be reviewed. `validate_contracts.py` PASS on the infra branch. `sprint-status.md` on `main` still lists those streams as "running, status unknown"; it was not edited from this branch (main is the newer copy; update it on main).
- Stream A re-verified in the cloud container: `tests/integration/gate_g1.sh` PASS (contract validation + 17 smoke checks). Spikes S1–S7 still not run.
- 2026-10-30 (later): `stream/backend` is now pushed (12 commits, 81 files). Reviewed: `validate_contracts.py` PASS, `pytest tests/backend` 146 passed / 4 skipped (PostgreSQL tests not run here), no `contracts/` changes, no LLM imports, no attribution lines, STATUS.md claims no measured results. Code itself not reviewed. `stream/policy`, `stream/frontend`, `stream/harness` still not pushed.
- **Fixture/measurement mismatch to resolve before G2:** `tests/backend/fixtures/scenarios.py` (`worker_crash`) models `queue_depth` rising while the worker is down. The N=1 observation in `docs/dev/infra/STATUS.md` shows the series is absent while the worker is dead (the worker exports it). The detector config already has a `queue_absent` rule, but the worker-crash fixture should be changed to a gap, and the worker-crash RCA must not rely on a rising queue. Needs a decision by the backend stream/owner; not changed from here.
- 2026-10-31: all five stream branches are on the remote; the policy, frontend and harness sessions were asked to push after GitHub was reconnected. Full results and the contract change request list are in `stream-review-2026-10-31.md`.

## Integration branch (2026-10-31)
`integration` = `main` + `stream/infra-p7f2rn`, `policy`, `backend`, `harness`, `frontend` (no merge conflicts), plus fixes found while merging:
- **Backend vs real Layer 1:** the backend had only ever run against its local stub. With the real `invariants` package every plan was denied (I-08), because the backend's own `Catalog` type was passed to rules that need `invariants.Catalog`, `container_labels` was `None`, and an approved medium-risk plan was still read as "needs approval". Fixed in `backend/policy_adapter.py` and `backend/domain/catalog.py`. The backend suite passes with the stub (146) and with the real package (131, 19 skipped as stub-only).
- **Flaky actuator test:** a race in the test helper (server closes early on 404/405), fixed in the test only; 0 failures in 40 file runs and 8 suite runs.
- **Worker-crash fixture:** now models `queue_depth` as absent while the worker is down; detector/RCA tests updated (RCA confidence 0.65, not >= 0.7, one signal fewer). Open: backend-1.
- **Rego:** `opa check` exit 0 and `opa test` 13/13 on OPA 1.22.0.
- **Verification on this branch:** contracts PASS; backend 146, invariants 129, actuator 83, policy 108, harness 134, frontend 132 (typecheck clean); combined single-process pytest 585 passed, 19 skipped, 0 failed.
- **Still open (needs a decision or a run):** the 10 contract change requests; the real-package/stub difference for a plan whose declared risk is below the catalogue's (real: approval required, stub: deny); PostgreSQL 18 for the backend; frontend build and e2e; the Postgres audit sink; cross-stream runs against the real sandbox (G2/G3).

### Contract change requests applied on `integration` (2026-10-31)
Applied: policy-1, frontend-1, frontend-2, harness-2 (`contracts/cause_ids.md`), harness-3 (`contracts/audit_events.md`), backend-1 (`cd_queue_length` in the probe sidecar and `contracts/telemetry.md`). No change needed: harness-1. **Deferred, with reasons in each request file:** policy-2 (envelope attestations), frontend-3 (new endpoints), harness-4 (new collectors and RCA rules), and the backend's own use of `cd_queue_length` (its detector still reads `queue_depth`).
Re-verified after the changes: contracts PASS; backend 146 (stub) and 131 + 19 skipped (real package); invariants 129; actuator 83; policy 108; harness 134; combined run 585 passed, 19 skipped, 0 failed; frontend `check:api` ok, 132 tests, `next build` compiles; `make smoke` PASS with 18 checks.
