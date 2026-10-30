# Requirements Specification

**Status:** Draft v0.1. Derived from the challenge text (authoritative) and design decisions recorded in the research documents. Requirements are DESIGN DECISIONs, not findings.

Priority: **M**ust / **S**hould / **C**ould.

## Functional requirements

| ID | Requirement | Pri | Rationale | Acceptance criteria |
|---|---|---|---|---|
| FR-001 | Detect service failures and degradation in the simulated application. | M | Challenge deliverable 2 | For each of the 10 experiments, an incident opens within the experiment's detection deadline; control runs open none |
| FR-002 | Collect metrics, logs and events from all simulated services. | M | Evidence base | Each signal type queryable per service for any incident window |
| FR-003 | Build an incident timeline from alerts, metric anomalies, logs, deploy/container events, actions and verification results. | M | Deliverable 2 | Timeline ordered by event time, with collection time retained and duplicates marked |
| FR-004 | Record every observation as evidence with ID, source, query, event and collection time. | M | Provenance (Domain H) | Every diagnosis claim resolves to existing evidence IDs |
| FR-005 | Generate ranked root-cause hypotheses with confidence, supporting and contradicting evidence, alternatives, unknowns. | M | Deliverable 3 | Report contains all five fields for each incident |
| FR-006 | Operate without the LLM (deterministic diagnosis and report). | M | Core principle | Experiments pass the pipeline end-to-end with LLM disabled |
| FR-007 | Produce an LLM explanation grounded in evidence IDs, validated mechanically. | S | AI-assisted layer | Unsupported-claim validator rejects uncited claims in tests |
| FR-008 | Recommend remediation from a fixed catalogue with typed parameters. | M | Deliverable 4 | Recommendations are catalogue IDs; free text is not executable |
| FR-009 | Evaluate each recommendation against policy (allowlist, risk, limits, evidence precondition). | M | Safety | Out-of-policy actions are denied and audited in tests |
| FR-010 | Execute approved actions only in the sandbox. | M | Challenge constraint | Executor refuses non-sandbox targets (negative test) |
| FR-011 | Require human approval for medium-risk actions; never execute high-risk actions. | M | Risk model | Verified by policy tests |
| FR-012 | Verify recovery with health, dependency, SLI and synthetic-transaction checks over a stability window. | M | Deliverable 4 | Container-running-but-unhealthy case is classified not recovered |
| FR-013 | Bound repetition: max attempts, cooldown, circuit breaker, escalation. | M | Remediation loops | Persistent-fault scenario ends in escalation without exceeding the limit |
| FR-014 | Generate a human-readable and machine-readable recovery report. | M | Deliverable 4 | JSON schema-valid report and rendered view per incident |
| FR-015 | Dashboard: service health, active incidents, alerts, metrics, logs, timeline, dependencies, RCA, evidence, remediation, approval, verification, audit. | M | Deliverable 1 | Each listed panel present and linked to evidence |
| FR-016 | Fault-injection interface to trigger the 10 experiments reproducibly. | M | Experiments | Scenario defined by config; injection timestamps recorded |
| FR-017 | Append-only audit log of detection, diagnosis, policy decisions, actions and approvals. | M | Auditability | Every action traces to a policy decision and approver/auto rule |
| FR-018 | Evaluation harness computing the defined metrics from ground truth. | S | Domain Y | Metrics emitted per run, with run metadata |

## Non-functional requirements

| ID | Category | Requirement | Pri | Acceptance criteria |
|---|---|---|---|---|
| NFR-001 | Safety | Fail closed: if policy, evidence store, or sandbox target validation is unavailable, no action executes. | M | Dependency-down tests show zero executions |
| NFR-002 | Security | LLM process has no executor access, credentials, or Docker socket. | M | Network/process separation verified by test |
| NFR-003 | Security | Telemetry is treated as untrusted; injection test corpus produces no unauthorized action. | M | Zero unauthorized actions in the corpus run |
| NFR-004 | Reliability | Missing telemetry yields `UNKNOWN` health and an alert, not `HEALTHY`. | M | Telemetry-gap experiment |
| NFR-005 | Explainability | Every output traceable to evidence and rule/policy IDs. | M | Spot audit of reports |
| NFR-006 | Reproducibility | Experiments scripted with pinned versions, seeds and configs; run metadata stored. | M | A second machine reproduces scenario runs |
| NFR-007 | Performance | Detection-to-diagnosis latency target set from baselines (pending measurement). | S | Measured, not assumed |
| NFR-008 | Observability | Cloud Doctor emits its own metrics/logs and alerts on its own failure. | S | Self-health panel |
| NFR-009 | Scalability | Designed for ≤ ~10 services; no claims beyond this scope. | C | Documented limit |
| NFR-010 | Cost | LLM token and call budgets per incident. | S | Budget enforced; usage recorded |
| NFR-011 | Honesty | Reports distinguish observed facts, correlations, hypotheses and confirmed causes. | M | Schema fields separate them |

## Traceability

FR-001/002 ← Domain B, D; FR-004 ← H; FR-005 ← F; FR-006/007 ← G; FR-009/011 ← L; FR-010 ← M; FR-012 ← O; FR-013 ← P; NFR-002/003 ← Q.
