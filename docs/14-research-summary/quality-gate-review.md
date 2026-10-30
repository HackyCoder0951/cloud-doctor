# Phase 0 Quality-Gate Review

**Date:** 2026-10-31 · **Scope:** the checklist in the master prompt §33 and the Gate G1 condition in `00-research-plan.md`. **Verdict: Phase 0 is not complete.** The research base is broad and the design is coherent, but ADR acceptance is blocked by specific gaps below.

Mechanical checks run today: 91 sources registered; every source ID cited in the docs exists in the register; no broken relative links; three registered sources are uncited (S-012, S-046, S-077; S-046 is superseded by S-054, S-077 is deliberately unused). Mermaid diagrams are **not rendered or validated** (validation needs an npm download that has not been approved).

## Checklist

Legend: **Met** (evidence in docs) · **Partial** · **Open**.

### Architecture

| Question | Status | Evidence / gap |
|---|---|---|
| All major components justified? | Partial | Component choices have rationale; sandbox (ADR-004) and policy (ADR-005) still provisional |
| Alternatives considered? | Met | `architecture-options.md`, ADR-001…006 list options |
| Trust boundaries clear? | Met (design) | `threat-model.md` zones and 12 threats; unverified by tests |

### SRE

| Question | Status | Evidence / gap |
|---|---|---|
| SLI/SLO applied appropriately? | Met (design) | `sli-slo-sla.md`; window scaling for short simulations **unverified** |
| MTTD/MTTR measurable? | Partial | Project definitions tied to ground-truth timestamps; primary-source definitions absent, vendor sources disagree (S-071, S-072); Google incident-metrics report unread |
| Recovery actually verified? | Met (design) | `recovery-verification.md`; thresholds TBD |

### Observability

| Question | Status | Evidence / gap |
|---|---|---|
| Metrics, logs, events correlated? | Partial | Design in place (`alert-correlation.md`, evidence/timeline model); correlation window untuned |
| Telemetry limitations documented? | Met | Prometheus sampling, Loki limits, Alertmanager delays, gaps → `UNKNOWN` |

### AI

| Question | Status | Evidence / gap |
|---|---|---|
| Grounded in evidence? | Met (design) | `evidence-grounding.md` validator rules; effectiveness unmeasured |
| Hallucination risk addressed? | Met (design) | Same; seeded-error test planned |
| AI boundaries explicit and technical? | Met (design) | ADR-003, threat model; enforcement untested |
| System works without AI? | Met (design) | C0 channel, FR-006; to verify in experiments |
| Channels/cost understood? | Partial | `llm-channels.md`, `cost-performance.md`; C2/C4 pricing, local-model quality unknown |

### Automation

| Question | Status | Evidence / gap |
|---|---|---|
| Remediation bounded? | Met (design) | Catalogue, risk classes |
| Policy engine? | Partial | In-process validator proposed; OPA deployment/logging facts read; fail-closed must be built by caller (no doc statement) |
| Execution sandboxed? | Partial | Compose vs. Kind not decided; NetworkPolicy enforcement in kind is an inference |
| Circuit breaker? | Met (design) | `remediation-loops.md` |

### Security

| Question | Status | Evidence / gap |
|---|---|---|
| Least privilege enforced? | Partial | Minimal executor, rootless option; docker.sock root-equivalence has only Tier 3 support; rootless CPU limits need cgroup delegation |
| Credentials isolated? | Partial | Gateway-only keys by design; secrets management doc not written |
| Malicious telemetry can't drive actions? | Met (design) | No AI→executor path, typed catalogue; **to be proven by the injection test suite** |

### Research integrity

| Question | Status | Evidence / gap |
|---|---|---|
| Claims sourced? | Partial | Most claims cite sources; many Tier-1 reads are partial or model-extracted (see register levels); exact wording must be re-verified before quoting |
| Assumptions labelled? | Met | DESIGN DECISION / HYPOTHESIS / ASSUMPTION labels used |
| Experiments reproducible? | Met (design) | Run protocol and metadata defined; none run |
| Results separated from expectations? | Met | All results sections say pending; README states no results |

### Portfolio quality

| Question | Status |
|---|---|
| Another engineer can understand the system? | Largely, from README → system-architecture → final-architecture |
| Architecture implementable from docs? | Partly: data model, API, state machines exist; Compose/Kind details, scenario scripts, topology specifics do not |
| Decisions defensible in an interview? | Mostly; weakest points are the AI-value hypothesis (untested) and sandbox choice |

## Gate G1 status (RQ-01…RQ-18)

| RQ | Topic | Status |
|---|---|---|
| 01 | SRE measures | Findings + design; MTTR primary source missing |
| 02–03 | Telemetry set; tracing need | Findings; tracing need untested (deferred) |
| 04 | Health model | Design |
| 05–06 | Detection; dedup/flap | Findings + design; anomaly literature partly search-level (S-062, S-047 unopened) |
| 07–08 | Symptom/cause; RCA family | Findings; probabilistic RCA has no validation on microservice telemetry |
| 09–10 | LLM role; evidence model | Findings (abstract-level papers) + design |
| 11 | Timelines/clock skew | **Thin**: only data model; no clock-skew source read |
| 12 | Risk/blast radius | Design; little external sourcing (runbook-automation literature unread) |
| 13 | Policy | Findings + design |
| 14 | Sandbox | Findings; decision open |
| 15 | Fault injection | Findings (Toxiproxy, Docker limits); stress tooling, Chaos Mesh/Litmus unread |
| 16–17 | Recovery; loops | Findings + design |
| 18 | Untrusted telemetry | Findings + design |

## Blockers to accepting ADRs

1. **ADR-004 (sandbox):** decide Compose-in-VM/rootless vs. Kind; test (not assume) kindnet NetworkPolicy behavior if Kind is kept; confirm rootless CPU-limit delegation works for EXP-03.
2. **ADR-005 (policy):** decide in-process vs. OPA; confirm Python integration if OPA is chosen.
3. **ADR-002:** pin Alertmanager version and test webhook retry behavior; confirm Loki ingestion/ordering behavior for the chosen version.
4. **ADR-001/003/006:** acceptable to accept *as hypotheses with falsification conditions* once the user agrees; AI value is explicitly untested.
5. **Cross-cutting:** user decision on client-facing scope (which channels are in the prototype; recommended: C0, C1, C3).

## Update — user decisions (2026-10-31)

| Decision | Effect |
|---|---|
| LLM channels in the prototype: **C0 and C1** | ADR-006 scope narrowed; C2/C3/C4 stay designed, unimplemented |
| Policy engine: **hybrid** (invariant guard + OPA client policy) | ADR-005 rewritten; blockers reduced to verification items (OPA health/bundle semantics, Rego test workflow, signing) |
| Sandbox: **MicroVM with private Docker daemon** (Docker Sandboxes / Freestyle) | ADR-004 updated; vendor claims checked against docs; **spikes S1–S7 required** before acceptance; observation path from host into the VM is unresolved |

**Tech stack finalised (2026-10-31):** `docs/10-architecture/tech-stack.md` consolidates every layer; ADR-007 (languages) is Accepted and its framework-documentation verification is done (Next.js, FastAPI, Pydantic, pip, subprocess, mypy, Bandit, pip-audit, PostgreSQL, SQLAlchemy, Alembic: S-101–S-121). Open stack items: test/CI tooling, version pins, Pydantic `extra='forbid'`, static-export CSP (F1), hash-generation tooling.

Remaining blockers for ADR acceptance: spikes S1–S7 (ADR-004); OPA verification items (ADR-005); Alertmanager retry test and Loki behavior (ADR-002).

## Remaining Phase 0 work (prioritised)

1. Open and read the unopened papers that carry design weight: S-062 (evaluation pitfalls), S-047 (BARO), S-020/S-021 full text, S-069 remainder, Google "Incident Metrics in SRE".
2. Timeline and clock-skew source; stress-test tooling sources; Kubernetes-vs-Compose health check equivalence.
3. Secrets-management, IAM/RBAC and telemetry-security notes (consolidated security addendum).
4. Re-verify quoted wording of high-use Tier-1 claims against live pages.
5. Render and validate all Mermaid diagrams.
6. User decisions: sandbox, policy engine, prototype channels; then mark ADRs Accepted or revise.
7. Re-run this review; then finalise `final-architecture.md`.

## What this review does not show

It does not show the system works, that the AI helps, or that any metric meets a target. No code exists and no experiment has run.
