# Experiment: Bad Deployment (EXP-07)

**Status: designed, NOT executed. Results: pending.**

## Objective
Test change-aware diagnosis ("what touched it last" [S-015]) and the rollback action.

## Hypothesis (HYPOTHESIS)
A deployment event shortly before the symptom, a version label change, and new error signatures in logs make `bad deploy` the top hypothesis; rollback to the previous image (medium risk) restores health after approval; restarting alone would not.

## Initial State
api v1 healthy; previous version retained.

## Fault Injection
Deploy api v2 that returns errors for one endpoint (or crashes under a condition).

## Expected Telemetry
Deployment/container-recreate event; error rate ↑ from the moment of change; error messages absent before; other services normal.

## Expected Detection / RCA
SLI breach correlated with a change event. Contradicting evidence checked: concurrent unrelated event, load change.

## Expected Remediation / Verification
`rollback_service(api, previous)`: medium risk, requires approval. Verification: error SLI normal over window; version label equals previous; synthetic transaction passes.

## Metrics
Top-1 accuracy with/without the change event, approval latency, TTR, wrong-action rate.

## Results
Pending.

## Failure Cases
Deploy timing coincides with unrelated fault (see EXP-09); no previous version available; rollback reintroduces an older bug.

## Conclusion
Pending.
