# Implementation Roadmap (PLAN — nothing implemented)

> **Superseded in detail by `development-plan.md`**, which reorders phases (foundation first, AI after the closed loop, incremental dashboard), adds milestones, scope tiers, effort assumptions, gates and traceability. The table below is kept as the original outline.

Gate: no implementation starts until ADR-001…005 are Accepted. Acceptance requires closing the open questions in `limitations.md`.

| Phase | Objective | Prerequisites | Deliverables | Tests / acceptance | Risks |
|---|---|---|---|---|---|
| 0 Research | Complete research and decisions | — | Docs, ADRs Accepted | Quality gate checklist passes | Scope creep |
| 1 Sandbox | Isolated environment | ADR-004 | Compose/Kind definition, network isolation | Non-sandbox target rejected; no host mounts | Daemon privilege |
| 2 Service simulation | Gateway, API, Redis, worker, Postgres, load generator | 1 | Services with health endpoints, metrics, structured logs | Steady state stable under load | Unrealistic behavior |
| 3 Observability | Prometheus, Loki, Grafana, Alertmanager | 2, ADR-002 | Dashboards, scrape/log pipelines | Signals queryable per service | Cardinality, Loki limits |
| 4 Failure injection | Harness for 10 scenarios | 2, 3 | Scenario configs, ground-truth log | Reproducible injection; abort works | Injector exposure |
| 5 Detection | SLI/burn-rate + threshold rules with hysteresis | 3, 4 | Detector, alerts | Control runs: no FP; EXP detection within deadline | Low-traffic sensitivity |
| 6 Correlation | Incident grouping, timeline | 5 | Incident manager, timeline | Cascade grouped into one incident | Clock/ordering errors |
| 7 RCA | Evidence store and deterministic ranking | 6 | EV-### store, ranker | Evidence coverage 100% in reports | Circular evaluation |
| 8 AI integration | Sanitised bundle, LLM explanation, validator | 7, ADR-003 | LLM adapter, validator | LLM-off parity; unsupported-claim check; injection suite | Cost, nondeterminism |
| 9 Policy | Validator, risk classes, limits | ADR-005 | Policy module | Deny tests; fail-closed tests | Policy bugs |
| 10 Remediation | Catalogue, separate Python actuator process (invariants + executor), state machine | 9 | Actuator, loop guards | Loop test; non-sandbox refusal | Executor privilege |
| 11 Verification | Before/after checks, stability window | 5, 10 | Verifier | Running-but-unhealthy ≠ recovered | Window tuning |
| 12 Dashboard | Incident-centric UI (Next.js/TypeScript; escaped evidence rendering, CSP, typed client from the OpenAPI contract) | 6–11 | Frontend | All panels linked to evidence | Over-design |
| 13 Security hardening | Threat-model tests | 8–12 | Test report | Zero unauthorized actions in suite | Residual gaps |
| 14 Evaluation | Run experiments, compute metrics | 4–13 | Results documents | Metrics with N and ranges | Small N |
| 15 Portfolio docs | README, final architecture, limitations | 14 | Final docs | Another engineer can reproduce | Overclaiming |

Definition of Done: see prompt §28; every unchecked item stays unchecked until demonstrated.
