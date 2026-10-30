# SLIs, SLOs, SLAs and Error Budgets

## Abstract

Cloud Doctor needs a measurable definition of "healthy" and "recovered". SLIs and SLOs provide it. This document records what the primary source says and how it will be applied in a simulated environment. It also states where the SRE model stops applying.

## Problem

"Service is down" and "service has recovered" are not testable statements. Detection thresholds, recovery verification (Domain O) and evaluation metrics (Domain Y) all need defined indicators and targets.

## Research Findings (RESEARCH FINDING)

All from [S-001] unless noted.

| Term | Source definition (close paraphrase) |
|---|---|
| SLI | A carefully defined quantitative measure of some aspect of the level of service provided. |
| SLO | A target value or range of values for a service level measured by an SLI; natural form `SLI ≤ target` or `lower ≤ SLI ≤ upper`. |
| SLA | An explicit or implicit contract with users that includes consequences of meeting or missing SLOs. If there is no explicit consequence it is almost certainly an SLO. |

Further findings:

1. **Percentiles over means.** The chapter prefers percentiles; averaging obscures a long tail of slow requests. A high percentile (99th, 99.9th) shows a plausible worst case, the 50th the typical case.
2. **Indicators depend on system type.** User-facing serving systems: availability, latency, throughput. Storage: latency, availability, durability. Data pipelines: throughput, end-to-end latency.
3. **Few indicators.** "A handful of representative indicators are enough"; do not use every trackable metric as an SLI.
4. **Start from user concern**, not from what is easy to measure.
5. **Error budget.** 100% is neither realistic nor desirable; an error budget is the rate at which the SLO may be missed, tracked daily/weekly, and is an input to release decisions.
6. **Target-setting guidance:** don't pick a target from current performance; keep it simple; avoid absolutes; have few SLOs; start loose and tighten.

Golden signals [S-002]: **latency, traffic, errors, saturation**. Notable details: separate latency of successful vs. failed requests ("a slow error is even worse than a fast error"); errors may be explicit (HTTP 500), implicit (HTTP 200 with wrong content) or by policy (response over a committed limit); many systems degrade before 100% utilization, so a utilization target is needed.

### Budget arithmetic (DESIGN DECISION — standard arithmetic, not a sourced claim)

```text
error_budget = 1 − SLO_target                (fraction of requests/time allowed to fail)
burn_rate    = observed_error_rate / (1 − SLO_target)
time_to_exhaust = window / burn_rate         (at constant burn rate)
```

Example: 99.9% SLO over 30 days → budget 0.1%; a 1% error rate is a burn rate of 10 and exhausts the budget in about 3 days if sustained.

## Alternatives for defining "healthy" in Cloud Doctor

| Approach | Pros | Cons |
|---|---|---|
| Static thresholds only (CPU>90%) | Simple, explainable | Resource metrics are causes, not user impact; S-002 advises catching symptoms |
| User-facing SLIs + SLO burn | Aligned with SRE practice; symptom-oriented | Needs enough traffic; see below |
| Both: SLO-based *symptom* detection, resource signals as *evidence* | Matches symptom/cause separation | Slightly more design |

## Recommended Approach (DESIGN DECISION)

- Define SLIs on the simulated app's user-facing path: **availability** (non-error ratio), **latency** (p95/p99 of successful requests, with failed-request latency tracked separately), **throughput**. Resource saturation, queue depth and restart count are *supporting signals*, used as evidence and for saturation warnings.
- Illustrative SLOs for the sandbox (**ASSUMPTION**, to be tuned from steady-state baseline measurement, not from current performance as S-001 warns): availability 99.0–99.9%, p95 latency target set from baseline.
- A synthetic traffic generator is mandatory — see the low-traffic finding below.

## Cloud Doctor Application

- **Detection** uses SLI breach/burn as the primary symptom signal.
- **Verification** uses the same SLIs plus dependency health, so detection and recovery are judged by one definition.
- **Evaluation** measures MTTD/MTTR against injected-fault timestamps (see `mttd-mttr.md`).

## Risks and Limitations

- **Low traffic breaks burn-rate alerting.** [S-003] shows 1 failure in 10 requests/hour is a 1,000× burn rate at 99.9%, and recommends synthetic traffic, grouping services, client retries or relaxed SLOs. A sandbox is inherently low-traffic, so synthetic load is a design requirement.
- The SRE book describes Google-scale practice; applying a 99.9% SLO to a laptop sandbox is a **modeling convenience**, not evidence of real-world reliability.
- SLOs are not SLAs; no contractual aspect is modeled.

## Open Questions

- OQ: Which window lengths are meaningful in a simulation that lasts minutes, not 30 days? Burn-rate windows will likely be scaled (e.g., 30 days → minutes); the validity of scaled windows is **unverified**.

## References

- [S-001] Google SRE Book, Ch. 4 — https://sre.google/sre-book/service-level-objectives/
- [S-002] Google SRE Book, Ch. 6 — https://sre.google/sre-book/monitoring-distributed-systems/
- [S-003] Google SRE Workbook, Ch. 5 — https://sre.google/workbook/alerting-on-slos/
