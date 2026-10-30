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
