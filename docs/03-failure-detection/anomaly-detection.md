# Anomaly Detection

## Abstract

Whether Cloud Doctor needs statistical or learned anomaly detection, and what the sources say about doing it safely. Conclusion so far: **simple rules, trend functions and absence checks first; learned detectors only as an evaluated comparison**.

## Research Findings (RESEARCH FINDING)

- **Simplicity preference.** Google's monitoring chapter is wary of "magic" systems that learn thresholds or infer causality and wants critical-path rules simple and predictable [S-002].
- **Prometheus primitives** available without ML: `deriv` and `predict_linear` (linear regression on gauges), `absent`/`absent_over_time`, `histogram_quantile` (interpolated estimate), and an experimental double exponential smoothing function [S-044, part via summary].
- **Evaluation pitfalls.** Kim et al. (AAAI 2022, abstract-level via search) report that point-adjusted evaluation can inflate time-series anomaly results so much that random scores look strong [S-062, unopened].
- **Contaminated training data.** A deep collaborative-autoencoder method trains two autoencoders to exchange low-error samples so anomalies in the training set are not memorized; evaluated on 18 ODDS benchmark datasets by AUC and with missing values; needs an anomaly-ratio parameter, with ±5%/±10% mis-specification tested [S-067, full read]. This is evidence that learned detectors are sensitive to what "normal" data contains — relevant because a sandbox baseline period may contain latent faults. It is **not** evidence about microservice telemetry.
- **Uncertainty-aware Bayesian detection** (BADAC) marginalizes over measurement error, demonstrated on simulated Gaussian-noise curves, and notes higher computational cost [S-069, pp. 1–10 read].
- **Bayesian online change-point detection** appears in BARO [S-047, search-level only].
- **Explanation of an anomaly** by per-feature likelihood influence on error-log counts is shown qualitatively in S-065.

## Comparison

| Method | Detects | Cost/complexity | Explainable | Risk | Fit (HYPOTHESIS) |
|---|---|---|---|---|---|
| Static threshold + `for` | Hard failures, saturation | Minimal | Yes | Mis-tuning (precision) | Resource evidence/warnings |
| SLO burn-rate (multiwindow) | User-visible degradation | Low | Yes | Needs traffic [S-003] | **Primary** |
| Linear trend (`deriv`, `predict_linear`) | Gradual leaks | Low | Yes | Non-linear growth | EXP-04 |
| `absent`/freshness checks | Telemetry gaps | Minimal | Yes | — | Health `UNKNOWN` |
| Baseline deviation (z-score/EWMA) | Latency/throughput shifts | Low–medium | Yes | Contaminated baseline, seasonality | Optional |
| Learned (autoencoder, change-point) | Unknown patterns | High; tuning | Low | Contamination, evaluation inflation | Comparison only |
| LLM | — | — | — | Not for detection | **Excluded** |

## Design (DESIGN DECISION, provisional)

1. Detection layer = SLO burn + thresholds + trend + absence, each with hysteresis.
2. Baseline definition: steady-state window recorded with the load generator, **validated by a control run** to ensure it contains no injected or latent fault; baseline versioned in run metadata.
3. Score detection **per injected incident** (opened? when?), never with point-adjust; include a trivial baseline detector in every comparison.
4. Any learned detector is a separate experiment arm, not part of the safety-critical path.

## Limitations / Open Questions

- Whether linear extrapolation is adequate for non-linear memory growth (EXP-04).
- Seasonality is absent in a short synthetic workload, so baseline-deviation methods are under-tested.
- S-062 and S-047 need full-text reads.

## References

S-002, S-003, S-044, S-047, S-062, S-065, S-067, S-069.
