# Experiment: Redis Failure (EXP-01)

**Status: designed, NOT executed. Results: pending.**

## Objective

Test whether Cloud Doctor distinguishes a failed dependency (cause) from downstream symptoms, restores service via a bounded action, and verifies recovery beyond "container running".

## Hypothesis (HYPOTHESIS)

- H1: An incident opens from a user-facing SLI breach (symptom) within the detection deadline.
- H2: Topology plus evidence ranks `redis` first with api/worker errors as symptoms, using connection-refused log evidence and redis down state.
- H3: Restarting `redis` (low risk) recovers service; verification passes after the stability window.
- H4 (to falsify): the deterministic baseline already reaches the correct top-1 cause, so the LLM adds no accuracy here.

## Initial State

All services healthy under synthetic load; SLIs within baseline; no open incidents.

## Fault Injection

At `t_inject`, stop the redis container (harness records time). Variant: disable via proxy to simulate a network-level outage.

## Expected Telemetry

| Signal | Expectation |
|---|---|
| Metrics | api error rate ↑, latency ↑ (possibly failed-fast), queue depth ↑ / worker throughput ↓, redis target `up=0` |
| Logs | api and worker: connection refused/timeout to redis |
| Events | redis container stopped (injector event not visible to Cloud Doctor as cause — only the container event is) |

## Expected Detection / RCA

Detection: symptom-based SLI breach, grouped with redis `up=0` into one incident. RCA: top-1 `redis unavailable`; alternatives (api bug, network) with contradicting evidence recorded; unknowns noted (cause of redis stopping).

## Expected Remediation and Verification

Recommend `restart_service(redis)` (low risk; allowed). Verification: redis ready; api/worker error rate within SLO; queue drains; synthetic transaction succeeds; stable for the window; no regression in postgres.

## Metrics

TTD, time to diagnose, top-1 accuracy, evidence coverage, unsupported-claim rate (LLM on), remediation success, TTR (verified), actions executed (expect 1), unauthorized actions (expect 0).

## Results

Pending. No data collected.

## Analysis / Failure Cases to examine

Redis restarts but loses data; api retries storm after restart; worker needs restart too; alert fires on worker before redis (ordering ambiguity); telemetry gap during outage.

## Conclusion

Pending.
