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
