# Experiment: Database Connection Exhaustion (EXP-05)

**Status: designed, NOT executed. Results: pending.**

## Objective
Test diagnosis when the dependency process is "up" but saturated, and when restarting the victim does not fix the cause.

## Hypothesis (HYPOTHESIS)
A connection leak (client holding connections) exhausts Postgres `max_connections`: api and worker log connection-limit errors, DB process stays up, DB health probe may still pass. Naive "dependency down" logic would miss it; saturation evidence (connections near max) should rank first. Restarting api temporarily frees connections; restarting the leaking client fixes it.

## Initial State
Steady load; connection count well under the limit.

## Fault Injection
Open and hold connections from a test client until the limit is hit; variant: leak inside worker.

## Expected Telemetry
DB connection gauge near max; "too many connections" errors in logs; rising latency and 5xx.

## Expected Detection / RCA
SLI breach grouped with DB saturation. Candidates: DB down (contradicted: process up, accepting connections from monitor), leaking client (supported by per-client connection counts), slow queries (contradicted: low query time).

## Expected Remediation / Verification
Restart the leaking service (identified by connection attribution) — medium confidence; policy may require approval. Verification: connection count back to baseline and stable. Restarting DB is high risk (denied).

## Metrics
RCA accuracy among ambiguous candidates, wrong-action rate, TTR.

## Results
Pending.

## Failure Cases
Leaker not identifiable from available metrics; restart of victim only delays recurrence; monitoring connection itself fails at the limit (telemetry gap).

## Conclusion
Pending.
