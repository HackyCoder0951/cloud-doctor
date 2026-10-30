# Failure Detection Methods (initial findings)

## Abstract

Initial sourced findings on alerting strategy, drawn from the SRE book and workbook and Prometheus/Alertmanager docs. Statistical/ML detection and academic literature are **not yet researched**; this document is incomplete by design.

## Research Findings (RESEARCH FINDING)

### What should alert [S-002]

- Page only when something is broken and needs action now, or is about to break. Don't alert because something "seems a bit weird."
- Effective alerting has "good signal and very low noise"; frequent pages cause people to skim or ignore them.
- A page that merits only a robotic response shouldn't be a page (candidate for automation — directly relevant to Cloud Doctor).
- Prefer catching symptoms to causes; alert on causes only when "very definite, very imminent".
- Keep monitoring rules simple and predictable; the source is wary of "magic" systems that learn thresholds or infer causality.
- Dependency-based alert suppression: the source reports only limited success with complex dependency hierarchies, since infrastructure is constantly refactored; such rules fit stable parts of the system.

### Evaluating alert strategies [S-003]

Four criteria: **precision**, **recall**, **detection time**, **reset time**.

| Strategy | Stated weakness |
|---|---|
| Error rate ≥ SLO over short window | Low precision (could alert many times a day while still meeting SLO) |
| Longer window | Very poor reset time (alert keeps firing long after recovery); costly to compute |
| Incrementing duration (`for:`) | Poor recall/detection time: duration doesn't scale with severity; timer resets on brief recovery. Chapter does not recommend it for SLO alerting |
| Burn rate | Low recall for moderate burn; long reset time |
| Multiple burn rates | Many parameters; needs suppression because one incident triggers several rules |
| **Multiwindow, multi-burn-rate** | Many parameters; chapter calls it most appropriate in most cases |

Recommended values for a 99.9% SLO (Table 5-8): page at burn 14.4 (1h/5m, 2% budget) and burn 6 (6h/30m, 5%); ticket at burn 1 (3d/6h, 10%). Short window ≈ 1/12 of long window. A source discrepancy (SD-01) exists for the ticket rule.

### Prometheus/Alertmanager mechanics [S-004, S-005]

- `for` → pending then firing; `keep_firing_for` → prevents flapping and false resolution on missing data.
- Alertmanager groups, deduplicates, inhibits (suppress when a related alert fires), silences.

## Comparison (initial, qualitative)

| Approach | Strength | Weakness | Cloud Doctor fit (HYPOTHESIS) |
|---|---|---|---|
| Static threshold | Simple, explainable [S-002] | Low precision/recall if poorly tuned; causes not symptoms | Resource-saturation evidence and warnings |
| SLO burn rate (multiwindow) | Symptom-oriented, tunable precision/recall [S-003] | Needs traffic; parameter-heavy | Primary symptom detector, with window scaling and synthetic traffic |
| Statistical baseline / ML | **Not yet researched** | — | Open question |
| LLM-assisted | **Not yet researched**; S-002 warns against magic | — | Not for detection (DESIGN DECISION: detection stays deterministic) |

## Cloud Doctor implications (DESIGN DECISION, provisional)

1. Detection is deterministic and explainable: SLO-burn symptom alerts + threshold/health-check rules, with hysteresis (`for`/`keep_firing_for`-style behavior) against flapping.
2. Group alerts into one incident by time window and static topology; keep suppression rules few and based on the declared dependency graph, given S-002's warning.
3. Every alert rule carries its precision/recall evidence from experiments (EXP-09 false-correlation targets precision).
4. Low-traffic mitigation: synthetic load generator (S-003).

## Available statistical primitives in Prometheus [S-044; part via summary]

| Function | Documented behavior | Use in Cloud Doctor (HYPOTHESIS) |
|---|---|---|
| `rate`, `increase` | Per-second / total increase over a window for counters; adjust for counter resets; take `rate()` first, then aggregate | Error and request rates |
| `deriv` | Per-second derivative via simple linear regression; gauges only; needs ≥2 float samples | Memory growth trend (EXP-04) |
| `predict_linear` | Linear-regression prediction `t` seconds ahead; gauges only (summary) | "Memory/disk exhausted in N minutes" saturation warning |
| `absent`, `absent_over_time` | Return 1 when no series exist (now / for a period) | Telemetry-gap detection → `UNKNOWN` health |
| `histogram_quantile` | Interpolated estimate from buckets; assumes uniform distribution within a classic bucket; no stated numeric error bound | p95/p99 latency (estimate, not exact) |
| `double_exponential_smoothing` | **Experimental**, feature-flagged; formerly `holt_winters` | Not planned |

**Interpretation:** simple linear trend and absence checks cover the gradual-fault and telemetry-gap cases without ML, consistent with S-002's preference for simple, predictable rules. Whether linear extrapolation is adequate for non-linear leaks is untested.

## Limitations / Open Questions

- Is baseline/statistical detection needed for gradual faults (memory growth, latency drift)? Test in EXP-03/04/06.
- Whether window scaling preserves the burn-rate guidance is unverified.
- Remaining sources: alert-correlation and anomaly-detection literature, Alertmanager configuration reference.

## References

- [S-002] https://sre.google/sre-book/monitoring-distributed-systems/
- [S-003] https://sre.google/workbook/alerting-on-slos/
- [S-004] https://prometheus.io/docs/alerting/latest/alertmanager/
- [S-005] https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
