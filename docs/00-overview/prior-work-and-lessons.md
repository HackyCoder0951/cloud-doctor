# Prior Work and Lessons from the User's Project Documentation

**Status:** analysis of documentation in two sibling repositories. These are the user's own project docs, so they are *project inputs*, not external sources, and are not in the source register. Nothing here is a research finding about the outside world; claims are limited to what the documents say.

## Documents read (in full unless noted)

**Linux-RCA-Platform:** `docs/Phase-1.md` (693 lines), `docs/Phase-1-Review-Plan.md` (400), `docs/Phase-1-Research-Review-Plan.md` (424).

**observability-infra:** `README.md` (239), `docs/README.md`, `docs/learning/00` through `09` (10 modules), `deploy/vps/README.md`, the product-pack README.

**Not available:** the first consumer product's observability design record (documents 00–14, in a separate repository), which `observability-infra/docs/README.md` names as the full design record (architecture, alerting, dashboards, security, DR, capacity, roadmap). That repository was not among the folders shared with this session.

## 1. Important correction: the observability stack is configured, not verified

The observability-infra learning curriculum states plainly that its phases P1–P5 are marked "done" but that "done" so far "means *the config exists*; it has never actually been brought up and checked end-to-end" (`00-overview.md`). Every module checklist in the repo is unticked. My earlier statement that the repository "already implements the chosen stack" should therefore read: **configuration for the stack exists and is pinned, but its authors' own documentation says it has not been verified end-to-end.** Reusing it means running its curriculum (or equivalent checks) first. This changes the Phase 3 estimate and is now recorded in ADR-002 and the reuse analysis.

## 2. Alignment with decisions already made in Cloud Doctor

| Their document says | Cloud Doctor position |
|---|---|
| Research → Architecture → Prototypes → Validation → Implementation; Phase 1 is research only, "not the implementation phase" | Same gate (Phase 0 research, implementation after ADRs accepted) |
| "Research Decision Framework": problem, options, prototype, tradeoffs, recommendation, reason alternatives were rejected | Equivalent to our ADR template |
| "RCA begins as deterministic rule-based correlation, not machine learning"; ML, eBPF, tracing are future scope unless justified | Same as ADR-001 (deterministic core) and the deferral of tracing and learned detectors |
| "Never blindly trust AI … NOT for unvalidated architecture decisions" | Consistent with the AI boundary (ADR-003) |
| Validation gate: "Another engineer can start Phase 2 without redoing Phase 1 research" | Same as the portfolio criterion in our quality-gate review |
| Output "explainable, not a black box"; "RCA output explains why a cause was suspected" | Same as the evidence model and grounding validator |
| Product contract: bounded-cardinality labels, JSON logs with `traceId`/`requestId` | Same label and correlation-ID rules we derived from the Prometheus/Loki docs |
| "Backend can be Go or FastAPI until Month 6, but API contracts must be language-neutral" | Supports making our API **contract-first** (OpenAPI/JSON Schema) so the backend/frontend language choice does not block design (decided in ADR-007: Python backend, Next.js/TypeScript UI) |

## 3. Gaps their docs reveal in Cloud Doctor's plan

### 3.1 Missing scenarios
Their Phase 1 validation list and failure-scenario list include conditions our ten experiments do not cover:

| Their scenario | Why it matters for us | Proposed addition |
|---|---|---|
| **Disk full** / high disk I/O (also `DiskFilling` in their infra alert rules) | A common failure; restart does nothing; correct action may be "escalate" or a catalogued cleanup | **EXP-11 Disk full** (design only) |
| **Backend/pipeline outage with agent buffering and retry, no data loss** | Our design treats telemetry loss as `UNKNOWN`; we have no numbered experiment for it | **EXP-12 Telemetry pipeline outage** (Prometheus/Loki unavailable) |
| **High-cardinality labels rejected or normalized** | Tests data-quality guards and Loki's label limits [S-051] | A negative test in the observability phase, not a fault scenario |
| **Journald/error-burst** as a detection signal | Our design lists log signatures but no burst detector | Add "log error-burst rate" as an evidence/detection signal |
| Their example chain "CPU spike → DB queue increase → API timeout → **service restart** → disk I/O errors; root cause: failing SSD" | The restart sits mid-chain and is a *symptom*, not the cause; the true cause is the last link | Use as a template for EXP-09/EXP-10: restarts must not be ranked as root causes merely because they precede recovery or failure |

These are **proposals**; they are recorded in `experiment-framework.md` as candidates and are not counted as designed scenarios until written.

### 3.2 "Empty because no data" vs "broken"
The learning modules repeatedly teach the same distinction: "tell 'empty because there's no data yet' apart from 'broken'" and "down because nothing is enabled/running yet is a correct, expected state, not a bug." This is exactly the `UNKNOWN`-vs-`HEALTHY`-vs-`EXPECTED_DOWN` distinction our health model needs. It should be formalized as three states for a missing signal: **no data (expected)**, **no data (unexpected)**, and **collection failed**. The existing RCA agent code does not preserve this distinction (see the reuse analysis).

### 3.3 Declarative config vs enabled components causes false incidents
`00-overview.md` and `deploy/vps/README.md` document that Prometheus scrape fragments are always loaded, even when their component is disabled, so the target shows **down** and `InstanceDown` fires. That is a documented false-positive generator. For Cloud Doctor this argues for a **single declarative service catalog ("topology as code")** from which the scrape configuration, dependency graph, health probes and expected-state registry are all generated, so that monitored targets can never diverge from the real topology. Their "product pack" (targets + dashboards + alerts under `products/<name>/`) is a working precedent.

### 3.4 Expected states and silences
Module 06 says not every firing alert is a problem and recommends a **silence with a comment and a duration** for understood noise, rather than ignoring it. Cloud Doctor needs a matching mechanism: an *expected-state registry* (maintenance windows, intentional faults, drained targets) with owner, reason and expiry, recorded in the timeline. This parallels Google's guidance to filter drained traffic and test deployments from alerts [S-002].

### 3.5 Test the pipeline with real faults, not only synthetic alerts
Module 06 contrasts `amtool alert add` (a synthetic alert that skips Prometheus rule evaluation, proving only routing/delivery mechanics) with stopping a real container to drive the whole path `pending → firing → resolved`. Adopt both, with distinct roles: synthetic alerts for webhook-plumbing tests; real injected faults for detection, correlation, and recovery acceptance tests. Their docs also show that a flapping target can reset a `for:` timer and that regex silences need `=~`.

### 3.6 Honest status convention
Module 07 labels every checklist line ✅ verified here, 🚫 not applicable here (deferred, not skipped), or ❌ gap found, and explicitly forbids pretending a VPS-only item passed locally. Cloud Doctor's quality-gate and security checklists should use the same three states.

### 3.7 State beyond git, and restore drills
Module 08 separates configuration (in git, "RPO 0") from runtime state (Grafana DB, Prometheus TSDB, Loki chunks), and insists a backup is proven by a **restore drill into a separate volume**, not by the archive existing. For us: evidence store and audit log are runtime state to back up; experiment runs need deterministic **reset** between repetitions. The same module warns that Compose volume names derive from the project directory name (so the project name must be pinned) and that cron scripts do not see the repo's env file — both are concrete traps for our run harness.

### 3.8 Risks for the MicroVM sandbox from their troubleshooting notes
- The stack uses `network_mode: host` throughout, which the docs say "behaves differently — and worse — on Docker Desktop for Mac/Windows" and for which **"running inside a Linux VM is the clean fix."** A MicroVM with a private Linux kernel is such a VM, but whether `network_mode: host` behaves as expected inside Docker Sandboxes is **unverified**; add to spike S3.
- cAdvisor needs `/dev/kmsg`, which "some minimal VMs" do not expose; it may degrade or crash-loop. A microVM kernel may lack it. Add to spike S3.
- Promtail's Docker log mount depends on the actual Docker data root (they use a snap path on the VPS); inside a microVM it may differ and must be configured.
- Node exporter and cAdvisor use `pid: host` and privileged mode; inside the MicroVM those apply to the VM only, which is the intended boundary.

### 3.9 Tracing notes (deferred, recorded for later)
The trace module notes tail sampling keeps all errors and slow spans (>1 s) but only 10% of the rest, with a 10-second decision wait, so a healthy fast span has about a 10% chance to survive and a trace may take over 10 s to appear. If tracing is added later, injected faults must produce error or slow spans or evidence will be missing, and evidence collection must tolerate that delay. The documents also point out that log→trace linking depends on three components agreeing on the `traceId` field name and format (app, Promtail, Grafana datasource) — a correlation contract Cloud Doctor's services must honor.

### 3.10 Agent/collector failure modes
Their Month 4 plan lists failure modes for a host agent: backend down, network loss, bad config, high CPU usage. Cloud Doctor's collectors and gateway have analogous modes; FM-08 (telemetry failure) covers the first two, and "bad config" (e.g., a rule file that does not validate) is addressed by adding `promtool`/`amtool` checks to CI.

## 4. Terms worth adding to the glossary
Recording rule, exemplar (metric→trace link), tail sampling, span metrics, RPO/RTO, expected-down state. Definitions follow the user's `09-glossary-and-research-prompts.md`; they are project definitions and should be cross-checked against primary documentation before being quoted as facts.

## 5. Mapping to the roadmap

| Roadmap phase | Contribution from prior work |
|---|---|
| 1 Sandbox | Run curriculum modules 01–02 inside the MicroVM as the first smoke test |
| 2 Service simulation | Product-pack contract as the service contract; service catalog as code |
| 3 Observability | Reuse config; add promtool/amtool CI; use modules 03–06 as verification steps |
| 4 Failure injection | Real-fault procedure (module 06); add EXP-11/12 |
| 5 Detection | Infrastructure alert rules; expected-state registry; burn-rate rules replace threshold "SLO" rules |
| 14 Evaluation | Honest ✅/🚫/❌ reporting; restore/reset drills for reproducibility |

## 6. Open items

- Access to the first consumer product's observability design record (documents 00–14, in a separate repository) to mine capacity planning, SLO definitions, security and DR design — not read.
- Decide whether to port prior-work concepts to Cloud Doctor's document tree or reference them from here.
