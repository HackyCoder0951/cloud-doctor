# Experiment: Memory Exhaustion (EXP-04)

**Status: designed, NOT executed. Results: pending.**

## Objective
Test predictive/gradual detection and recognition that a restart is only a temporary mitigation.

## Hypothesis (HYPOTHESIS)
A memory leak in `api` under a `--memory` limit shows steady growth (positive derivative), then an OOM kill and restart. A trend rule (`deriv` / `predict_linear` over a gauge [S-044]) warns before the OOM; after restart, memory grows again, the incident reopens, and the loop guard escalates instead of restarting repeatedly.

## Initial State
Steady load; memory flat.

## Fault Injection
Allocate memory at a fixed rate in api until the limit. Docker kills processes on OOM [S-029].

## Expected Telemetry
Memory gauge rising; container restarts; restart count increases; logs may end abruptly (no clean error message).

## Expected Detection / RCA
Saturation warning from trend, then availability SLI breach at OOM. RCA: memory exhaustion (supported by trend and restart events); alternative: crash bug (contradicted by memory trend).

## Expected Remediation / Verification
Restart api (low risk) gives temporary recovery; verification passes once; recurrence is tracked; escalation recommending rollback or fix (human). Tests the "mitigated ≠ root cause confirmed" distinction.

## Metrics
Warning lead time, number of restarts before escalation, loop-guard behavior.

## Results
Pending.

## Failure Cases
Linear extrapolation poor for non-linear growth; evidence lost on restart unless snapshotted first; OOM exit state details not documented in sources read (**unverified**).

## Conclusion
Pending.
