# Sprint Status (updated at every gate)

**Rule:** a gate is reported as ✅ done, ❌ failed, or 🚫 not reached. Nothing is reported done unless a command proving it was run. No measured result appears here unless it came from a recorded run.

## RESUME (read this first after any interruption)

- **Current step:** contract freeze committed; cloud streams B, C, D, F about to start; stream A (infra) next on the local machine.
- **Last green command:** `python3 tests/contract/validate_contracts.py` (PASS) and `tests/contract/check_db.sh` (PASS on PostgreSQL 18).
- **Next action:** start stream A: simulated application, Compose stack, Prometheus, catalog-generated scrape config.
- **Power or session loss:** `git status`, `git log --oneline | head`, re-run the two commands above, then continue from the next action.

## Stream status

| Stream | Branch | State | Notes |
|---|---|---|---|
| A infra | `stream/infra` | 🚫 not started | local, plain Docker first; micro-VM after the user installs Docker Sandboxes |
| B backend | `stream/backend` | 🚫 not started | cloud |
| C policy + actuator | `stream/policy` | 🚫 not started | cloud |
| D frontend | `stream/frontend` | 🚫 not started | cloud |
| F harness | `stream/harness` | 🚫 not started | cloud |
| E AI | `stream/ai` | 🚫 deliberately last | nothing depends on it |

## Gates

| Gate | Condition | Status |
|---|---|---|
| Contract freeze | schemas, OpenAPI, DB schema, catalog, fixtures, validation green | ✅ (validated 2026-10-31) |
| G1 | sandbox app running, metrics and logs flowing, spike outcomes recorded | 🚫 |
| G2 | read-only loop for the Redis outage | 🚫 |
| G3 | closed loop with policy, verification and escalation | 🚫 |
| G4 | all implemented scenarios end to end with no LLM in the path | 🚫 |
| G5 | tests green, demo rehearsed, AI channel reached or not reached | 🚫 |

## Open user actions

Install Docker Sandboxes (sudo) and `sbx login`; run `tools/nim_smoke_test.py` with the key in your own shell (only needed for the last, AI, phase); power plan; decision on merging stream branches.
