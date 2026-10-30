# Experiment: False Correlation (EXP-09) and Failed Remediation (EXP-10)

**Status: designed, NOT executed. Results: pending.**

These are the scenarios most likely to falsify the design.

## EXP-09 — False correlation

### Objective
Test whether the system avoids "A happened before B, so A caused B" [S-015 warns of spurious correlations and shared causes].

### Hypothesis (HYPOTHESIS)
When a harmless event (deploy of an unrelated service, config touch, log-noise burst) occurs just before a real fault elsewhere, the ranker lists it as an alternative with contradicting evidence rather than top-1; the confidence is reduced when temporal order is the only support.

### Fault Injection
Real fault: EXP-03 CPU saturation in `api`. Decoy: deploy of `worker` v-next (healthy) 20 seconds before. Variant: shared hidden cause (host-level contention affecting two services).

### Expected Telemetry / Detection
Worker deploy event precedes the api latency rise; worker metrics healthy.

### Expected RCA
Top-1 `api CPU saturation`; decoy listed with contradicting evidence (worker healthy, no dependency edge from worker to api latency path). For the shared-cause variant, the unknown is recorded rather than asserting one service as cause.

### Metrics
Top-1 accuracy, decoy-top-1 rate (FP-RCA), calibration of confidence, unsupported-claim rate with LLM on.

### Failure cases
Rules weight recency too much; LLM explanation narrates the decoy as cause (misinformation).

## EXP-10 — Failed remediation

### Objective
Test loop guards and escalation when the recommended action does not work.

### Hypothesis (HYPOTHESIS)
With a persistent fault (injector re-applies it after restart), the first restart fails verification, a cooldown applies, the planner may not repeat the same action without new evidence, the circuit breaker opens at the attempt limit, and the incident escalates with a report. Number of executed actions ≤ configured max.

### Fault Injection
Redis outage where the injector keeps redis unreachable even after restart; variant: restart worsens health (regression abort).

### Expected Verification
Verification fails; regression detected → RolledBack/Escalated states ([remediation-loops.md](../06-self-healing/remediation-loops.md)).

### Metrics
Actions executed vs. limit, loop count, time to escalation, correctness of final report.

### Results (both)
Pending.

### Conclusion
Pending.
