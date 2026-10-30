# Sprint Status (updated at every gate)

**Rule:** a gate is reported as ✅ done, ❌ failed, or 🚫 not reached. Nothing is reported done unless a command proving it was run. No measured result appears here unless it came from a recorded run.

## RESUME (read this first after any interruption)

- **Updated:** 2026-10-31 (night, user asleep).
- **Contracts:** frozen on `main` (schemas, OpenAPI, actuator API, DB schema, catalog, fixtures, `contracts/telemetry.md`); `tests/contract/validate_contracts.py` PASS and `tests/contract/check_db.sh` PASS on PostgreSQL 18.
- **Cloud sessions running** (started from `main`, each on its own branch, never merged into `main` without the user): `stream/backend` (Stream B), `stream/policy` (Stream C), `stream/frontend` (Stream D), `stream/harness` (Stream F). Their sessions are listed in the Claude app; they report in their own transcripts and in `docs/dev/<stream>/STATUS.md` on their branches. No completion notice is sent back.
- **Local stream A** is on branch `stream/infra` (pushed): `git checkout stream/infra && make up && make smoke`.
- **After an interruption:** `git fetch --all`, check which `stream/*` branches have new commits (`git log origin/stream/<x> --oneline | head`), re-run the contract validation, then continue from the next action below.
- **Next action (stream A):** more fault observations (worker crash, memory), Alertmanager webhook and Grafana, spike S3 on plain Docker; micro-VM spikes need the user to install Docker Sandboxes.

## Stream status

| Stream | Branch | State | Notes |
|---|---|---|---|
| A infra | `stream/infra` | 🟡 partial | plain-Docker sandbox, Prometheus, Loki/Promtail, catalog-generated scrape config; `make smoke` PASS (17 checks); one N=1 Redis-stop observation recorded in `docs/dev/infra/STATUS.md`; micro-VM, Alertmanager, Grafana not done |
| B backend | `stream/backend` | 🟡 running (cloud) | status unknown until its branch is read |
| C policy + actuator | `stream/policy` | 🟡 running (cloud) | status unknown until its branch is read |
| D frontend | `stream/frontend` | 🟡 running (cloud) | status unknown until its branch is read |
| F harness | `stream/harness` | 🟡 running (cloud) | status unknown until its branch is read |
| E AI | `stream/ai` | 🚫 deliberately last | nothing depends on it |

## Gates

| Gate | Condition | Status |
|---|---|---|
| Contract freeze | schemas, OpenAPI, DB schema, catalog, telemetry contract, fixtures, validation green | ✅ validated 2026-10-31 |
| G1 | sandbox app running, metrics and logs flowing, spike outcomes recorded | 🟡 **partially met**: app, metrics and logs verified on plain Docker (`make smoke` PASS); **micro-VM spikes S1–S7 not run** (need the user's sudo), outcome not recorded |
| G2 | read-only loop for the Redis outage | 🚫 not reached (needs streams B and D merged with the sandbox) |
| G3 | closed loop with policy, verification and escalation | 🚫 |
| G4 | all implemented scenarios end to end with no LLM in the path | 🚫 |
| G5 | tests green, demo rehearsed, AI channel reached or not reached | 🚫 |

## Open user actions

Install Docker Sandboxes (sudo) and `sbx login`; run `tools/nim_smoke_test.py` with the key in your own shell (only needed for the last, AI, phase); power plan; decision on merging stream branches.
