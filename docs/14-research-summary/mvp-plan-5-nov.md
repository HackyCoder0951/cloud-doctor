# Sprint Plan — Full Scope, Build 31 Oct to 4 Nov, MVP Testing 5 Nov 2026

**Status:** plan only; nothing is built. **Revision 3 (user decisions, 2026-10-31 night): the AI phase moves to the very end and nothing else depends on any LLM API; parallel sessions and regular pushes are approved; cloud sessions start first while the user sleeps.** **Revision 2 (user instruction):** no scope is pre-cut from the proposed design — micro-VM sandbox, hybrid policy with OPA, Alertmanager and Grafana, all ten scenarios, the AI channel, evaluation and hardening all stay in scope. This replaces the earlier reduced-scope version and the timeline of `development-plan.md`. Hours are planning assumptions; **no result is claimed until it has been measured.**

## 1. Capacity arithmetic (read this first)

| Quantity | Value |
|---|---|
| Build window | Sat 31 Oct ~03:00 to Wed 4 Nov 24:00, about **117 wall-clock hours** (testing on Thu 5 Nov) |
| Assumed availability | 24 hours a day, minus power outages |
| Planning estimate, full plan (P0–P15) | 490–900 hours (`development-plan.md`) |
| Planning estimate, challenge-MVP tier (P0–P10) | 340–620 hours |

The full-scope estimate is **4 to 8 times** the available wall-clock time, and even the MVP tier is about 3 to 5 times. Those estimates assumed one developer at a normal pace, so they may be pessimistic when most code is generated and several streams run in parallel — but how much so is **unknown**, and the dominant costs are the ones parallelism does not remove (spikes on your machine, debugging integrations, waiting for faults and recovery windows, verifying results).

So the plan does the following instead of pretending:
1. **Nothing is removed in advance.** The full scope stays the target.
2. **Order, not omission:** work is sequenced by dependency so a working core path exists as early as possible; this is not a cut, it is the only way the later parts have something to attach to.
3. **Parallel streams** (section 3) to raise throughput, if you approve them.
4. **Daily gates with honest status.** Anything not reached by the end of 4 Nov is reported as *not reached*, never as done, in `docs/14-research-summary/sprint-status.md`.
5. **Rest and breaks are part of the plan.** Continuous 24-hour operation raises error rates in code and in decisions, and a power cut during an unfinished step costs more than a break. Plan about 20 productive hours a day.

## 2. In-scope work (nothing deferred in advance)

All phases of `development-plan.md` (P0–P15) as designed: spikes S1–S7 and ADR acceptance; foundation (repo, CI, contracts, schema); micro-VM sandbox with the Compose app; Prometheus, Alertmanager, Loki, Promtail and Grafana; fault injection and the experiment harness; detection with multiwindow burn-rate rules, thresholds, trend and absence rules; incidents and timeline; evidence store and deterministic RCA with C0 report; the full Next.js dashboard; Layer 1 invariants, separate Python actuator, OPA Layer 2 with signed bundles; remediation, verification and loop guards; the AI gateway (C0 and C1 via NVIDIA NIM) with grounding validator and injection corpus; the ten experiments (plus EXP-11/12 candidates); evaluation metrics; security hardening; documentation updates.

## 3. Parallel workstreams (need your approval to start separate sessions)

Parallel sessions would work in separate git worktrees on the same repository. Nothing starts without your explicit go-ahead.

| Stream | Scope | Depends on |
|---|---|---|
| **A — Infra and sandbox** | Spikes S1–S7, micro-VM bring-up, Compose app, service catalog, Prometheus/Alertmanager/Loki/Promtail/Grafana, load generator | Contract freeze |
| **B — Backend core** | Detector, incidents, timeline, evidence, RCA, remediation engine, verifier, API | Contract + schema freeze, stream A signals |
| **C — Policy and actuator** | `invariants`, actuator process, OPA Layer 2, audit chain, approvals | Contract freeze |
| **D — Frontend** | Next.js dashboard, typed client, SSE | OpenAPI contract |
| **E — AI (LAST, starts only after A–D and F reach their gates)** | Gateway (C0/C1 NIM adapter), sanitiser, grounding validator, injection corpus | Evidence schema; **nothing else depends on it** |
| **F — Experiments** | Injector, ten scenarios, ground truth, evaluation metrics | Streams A and B |

**Critical shared step (first ~4 hours, one session):** freeze the OpenAPI contract, JSON Schemas (plan, decision, evidence, diagnosis, report), database schema and the service-catalog format. Fan-out starts only after that, otherwise the streams diverge.

## 4. Schedule with gates

| Window | Focus | Gate (reported honestly) |
|---|---|---|
| **Day 1** Sat 31 Oct | Contract/schema freeze; spikes S1–S7 and sandbox decision (micro-VM or fallback, decided by about hour 12); Compose app and Prometheus up; repo, CI skeleton; scaffolds for backend, actuator, frontend, harness; NIM smoke test run | **G1:** sandbox app running with metrics and logs flowing; contracts frozen; spike outcomes recorded in ADR-004; NIM capability flags recorded |
| **Day 2** Sun 1 Nov | Detection (burn-rate, thresholds, trend, absence), Alertmanager webhook, incidents and timeline, evidence collector, injector with first four scenarios; `invariants` complete with tests; dashboard core views | **G2:** read-only loop for the Redis outage visible end to end |
| **Day 3** Mon 2 Nov | RCA and C0 report; dashboard v1 complete; actuator and OPA Layer 2; remediation engine and verifier | **G3:** closed loop with policy, verification and escalation on a persistent fault |
| **Day 4** Tue 3 Nov | Remaining scenarios; approvals and audit views; evaluation metrics; security tests; integration of all streams | **G4:** all implemented scenarios runnable end to end with **no LLM anywhere in the path** |
| **Day 5** Wed 4 Nov | Experiment runs with repeats; hardening; documentation and results templates; rehearsals; **then the AI phase (stream E) last**: NIM adapter, grounding validator, injection corpus; feature freeze at the end of the day | **G5:** automated tests green; demo rehearsed; status file complete; AI channel reported as reached or not reached |
| **Thu 5 Nov** | **MVP testing** (bug fixes only) | Acceptance results recorded |

At each gate, if a stream is behind, the response is to **re-balance people and sessions and re-order work**, and to record exactly what is not reached — not to silently shrink the claims.

## 5. Sandbox plan (micro-VM)

Findings on this machine (2026-10-31): Ubuntu 25.04; the current user can open `/dev/kvm` through an ACL although not in the `kvm` group; hardware virtualization is present; the user is in the `docker` group; `sbx` is **not installed**; `sudo` requires a password.

What only you can do: install Docker Sandboxes (the vendor documents an installer run with `sudo`; the exact command is on its install page [S-093]) and complete `sbx login` in a browser. Then spikes S1–S7 run (ADR-004). Fallback if a spike fails: the same Compose stack in a plain dedicated VM (KVM is available for that), decided by about hour 12.

## 6. LLM channel (NVIDIA NIM) — built last, optional for every other test

Does it work? **Partly confirmed, partly untested** (details in `docs/05-ai/llm-channels.md`):
- Confirmed from NVIDIA's pages: OpenAI-compatible hosted chat endpoint at `https://integrate.api.nvidia.com/v1`, Bearer authentication, 85 models listed by the public models endpoint, `max_tokens` up to 4096 [S-122–S-124].
- Not confirmed: server-side structured output (the hosted request schema lists no `response_format`/`nvext`), tool calling per model, rate limits and credits (third-party figures only), data-retention terms.
- Therefore the design makes **no safety assumption** about NIM: JSON is requested by prompt, parsed, schema-validated and citation-checked client-side, retried once, then falls back to C0; evidence is pre-fetched; a client-side rate limit applies; only synthetic, redacted data is sent.
- **Because the AI phase is last, the 5 Nov core tests (A1–A8) and scenarios B1–B5, B7, B8 run with no API key, no network access to any LLM and no dependency on NIM.** Only B6 depends on it.
- Your step (can wait until you are awake): set `NVIDIA_API_KEY` **in your own shell** and run `python3 tools/nim_smoke_test.py [model-id]`; paste only the printed summary, never the key.

## 7. Power-outage and fatigue resilience

- **Commit often** (small logical commits, no attribution lines); push on a regular cadence if you approve pushing to the public repository.
- **Idempotent scripts** for bring-up and teardown; Compose `restart: unless-stopped`; database state in named volumes.
- A short `RESUME` section in `sprint-status.md` updated at every gate: current step, last green command, next action.
- Spikes and long runs record results to files as they go, not at the end.
- Planned rest blocks; do not start risky changes (database migrations, sandbox reconfiguration) when tired or when the power situation is unstable.

## 8. Acceptance testing on 5 Nov

**Core checklist (carried over):**

| ID | Test | Pass condition |
|---|---|---|
| A1 | Clean start with one command | All services healthy; startup time recorded |
| A2 | Control run (5 minutes, no fault) | Zero incidents |
| A3 | Redis outage | One incident; evidence stored; top-1 cause correct; contradicting evidence and alternatives listed |
| A4 | Closed loop | Recommendation → policy → actuator → verified recovery → schema-valid report; audit entries |
| A5 | Persistent fault | Attempts bounded; cooldown honored; escalation; no further actions |
| A6 | Policy negatives | Unknown action, non-allowlisted target, tampered signature, replayed or expired plan refused and audited |
| A7 | No LLM | Full demo works with no API key |
| A8 | Dashboard | All panels present; injected script text in a log line renders inert |

**Extended checklist for the full scope** (each reported ✅ pass / ❌ fail / 🚫 not reached):

| ID | Test |
|---|---|
| B1 | Micro-VM (or fallback VM) isolation: no host mounts beyond the clone; egress policy blocks unintended destinations |
| B2 | Alertmanager pipeline with a **real** fault (pending → firing → resolved → webhook), duplicate delivery handled once; synthetic alerts used only for plumbing |
| B3 | Burn-rate detection: detects the injected faults; control run quiet; low-traffic case documented |
| B4 | OPA Layer 2: down, undefined (`{}`), stale or unsigned bundle all deny; Layer 2 cannot loosen Layer 1 |
| B5 | Worker crash, memory exhaustion, bad deployment (rollback with approval), CPU saturation, DB connection exhaustion, network latency, dependency outage, false-correlation decoy |
| B6 | AI channel via NIM: valid output accepted; seeded invalid citations rejected; timeout, 429 and malformed output fall back to C0; poisoned-log corpus never changes a decision |
| B7 | Evaluation metrics computed from runs with run counts; trivial baselines reported |
| B8 | Security checklist (threat model TM-01…TM-16) with ✅/🚫/❌ |

**The MVP passes if A1–A8 pass.** Everything else is reported as it stands. Initial targets (assumptions, not claims): detection within 30 s of injection, diagnosis within 10 s of incident opening, verified recovery within 2 minutes.

## 9. Risks (updated)

| Risk | Impact | Mitigation |
|---|---|---|
| Full scope exceeds capacity (section 1) | Parts not reached by 4 Nov | Dependency ordering, parallel streams, honest status; no hidden shortcuts |
| Micro-VM spikes fail or take long | Sandbox rework | Fallback VM decision at hour ~12 |
| Integration debugging dominates | Gate slips | Contract freeze first; integration tests per gate |
| Power outages or fatigue | Lost work, errors | Section 7 |
| NIM capabilities weaker than assumed (no schema enforcement, rate limits) | AI stream rework | Client-side validation design already assumes this; smoke test early |
| NIM data terms unknown | Privacy exposure | Synthetic, redacted data only until terms are read |
| Actuator and Docker daemon privilege | Host impact if subverted | Micro-VM boundary if spikes pass; otherwise mitigations in ADR-007 |
| Over-claiming results | Credibility | Measured numbers with run counts only |

## 10. Approvals and remaining inputs

**Received (2026-10-31):** AI phase moved to the end; parallel sessions approved; regular pushes to the public repository approved.

**Execution while the user sleeps:** cloud sessions start from the pushed `main` branch, so contracts, schemas and the stream ownership map are frozen and pushed **before** any cloud session starts. Streams B (backend core), C (policy and actuator), D (frontend) and F (experiment harness) run in the cloud against fixtures and fakes, each on its own `stream/<name>` branch, with no Docker or sandbox required. Stream A (infra, Compose app, Prometheus, logs) runs on this machine, where Docker is available. **Merging stream branches into `main` waits for the user.**

**Still needed from the user when awake:**
1. Install Docker Sandboxes (needs the `sudo` password) and run `sbx login` — until then the Compose stack runs on plain Docker, which is reversible.
2. Run `tools/nim_smoke_test.py` with `NVIDIA_API_KEY` in their own shell — needed only for the last (AI) phase.
3. Power plan (UPS or battery?) — unanswered; assume interruptions.
4. Decide on merging the stream branches.
