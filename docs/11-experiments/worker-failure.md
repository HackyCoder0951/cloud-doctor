# Experiment: Worker Failure (EXP-02)

**Status: designed, NOT executed. Results: pending.**

## Objective
Verify detection and bounded recovery of a crashed background worker whose symptom (queue backlog) is indirect.

## Hypothesis (HYPOTHESIS)
Queue depth grows and throughput of queued jobs drops while API request SLIs stay healthy; the incident is detected from a queue-depth/job-latency signal, ranked `worker down`, and `restart_service(worker)` recovers with the backlog draining.

## Initial State
Steady load; queue depth near baseline.

## Fault Injection
Kill the worker process (exit non-zero) at `t_inject`.

## Expected Telemetry
Worker `up=0` or container exited; queue depth rising; no API 5xx (key contrast with EXP-01); worker logs end abruptly.

## Expected Detection / RCA / Remediation / Verification
Detection depends on a queue or job-completion SLI, not API errors — tests whether symptom coverage extends beyond HTTP. RCA: worker unavailable; alternatives: Redis problem (contradicted by healthy API cache hits), DB problem. Remediation: restart worker (low risk). Verification: worker ready, backlog below threshold and draining, no job loss beyond defined tolerance, window stable.

## Metrics
TTD, top-1 accuracy, TTR, jobs lost/duplicated (measured).

## Results
Pending.

## Failure Cases
Detection by API-only SLIs misses it (FN); restart while jobs in flight causes duplicates; restart policy already restarts worker (action redundant — policy should detect).

## Conclusion
Pending.
