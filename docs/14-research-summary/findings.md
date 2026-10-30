# Research Findings Summary

**Status as of 2026-10-31.** Every item cites a source ID from `docs/_sources/register.md`. The strength column states the reading depth.

| # | Finding (RESEARCH FINDING) | Source | Strength |
|---|---|---|---|
| F-01 | SLI/SLO/SLA are distinct; percentiles preferred over means; error budgets express acceptable unreliability | S-001 | Page read |
| F-02 | Golden signals are latency, traffic, errors, saturation; separate failed and successful latency | S-002 | Page read |
| F-03 | Pages should be symptom-oriented, actionable, low-noise; rote responses are candidates for automation | S-002 | Page read |
| F-04 | Google reports limited success with complex dependency-based alert suppression | S-002 | Page read |
| F-05 | Multiwindow, multi-burn-rate alerting is the workbook's recommended SLO alerting approach; low-traffic services need synthetic traffic or other measures | S-003 | Page read |
| F-06 | Prometheus `for` delays firing; `keep_firing_for` suppresses flapping; Alertmanager groups, inhibits, silences | S-004, S-005 | Page read |
| F-07 | Prometheus is not suited to 100%-accurate data; high-cardinality labels create series explosion | S-006, S-007 | Page read |
| F-08 | Loki indexes labels only; low-cardinality labels, structured metadata for high-cardinality fields | S-016, S-017 | Page read |
| F-09 | Incident handling: declare early, one actor changes the system, keep a living record, stop the bleeding and preserve evidence | S-013, S-015 | Page read |
| F-10 | Troubleshooting warns about spurious correlations and shared causes | S-015 | Page read |
| F-11 | No single causal-inference RCA method wins across settings; synthetic results may not transfer | S-021 | Abstract + partial text |
| F-12 | LLM RCA studies show promise on historical incidents; reasoning failures exist and are the subject of a 2026 taxonomy | S-023–S-026 | Abstracts only |
| F-13 | Liveness probes can cause cascading failures when misdesigned; readiness may check dependencies | S-018 | Final slice verbatim, rest summary |
| F-14 | Docker daemon control is root-level in effect; rootless mode runs daemon and containers as non-root | S-030, S-031, S-043 | Page read (docker.sock claim unsourced) |
| F-15 | OPA decouples decisions from enforcement; supports default values | S-034 | Page read |
| F-16 | OWASP 2025 lists prompt injection, improper output handling, excessive agency | S-036 | Page read |
| F-17 | Untrusted content should be passed as tool results, labelled and encoded; least privilege limits damage | S-038 | Page read (model-extracted) |
| F-18 | Circuit breakers have closed/open/half-open states; changes should be logged | S-039 | Page read |
| F-19 | Toxiproxy's API is unauthenticated by default | S-028 | Page read |
| F-20 | Prometheus provides `absent`, `deriv`, `predict_linear`, histogram quantile estimation (interpolated) | S-044 | Partial |

## Design consequences (DESIGN DECISIONs)

1. Symptom-based SLO detection plus supporting saturation signals (F-02, F-03, F-05).
2. Synthetic traffic generator is required (F-05).
3. Small, declared topology and rule-based ranking; no learned causal discovery initially (F-11).
4. LLM advisory only, evidence-ID validated, no path to execution (F-12, F-16, F-17).
5. Minimal executor, default-deny policy, rootless or VM-isolated daemon (F-14, F-15).
6. Loop guards with circuit breaker (F-18).
7. Telemetry gaps produce `UNKNOWN`, not healthy (F-20).
8. Fault-injection control plane isolated from Cloud Doctor (F-19).

## What is *not* established

Whether the LLM adds value (H-AI-1); whether rule-based ranking suffices on ambiguous cases; stability window length; detection latency in practice; cost. All pending experiments.
