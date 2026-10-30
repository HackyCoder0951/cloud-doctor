# Experiment: Network Latency (EXP-06)

**Status: designed, NOT executed. Results: pending.**

## Objective
Test detection and diagnosis of latency with no hard failures, where restarts are useless.

## Hypothesis (HYPOTHESIS)
Adding a Toxiproxy `latency` toxic [S-028] on the api→postgres link raises api latency and queue time with few errors, while DB-side query time stays normal (contradicting a slow-DB hypothesis). Correct recommendation: remove the fault/escalate; restarts are not helpful. Policy has no catalogue action to remove an injected toxic (it is outside Cloud Doctor's control plane), so the expected outcome is **escalation with a clear diagnosis**, not automatic recovery.

## Initial State
Steady load; traffic routed through the proxy.

## Fault Injection
`latency` toxic (e.g., hundreds of ms plus jitter) on the downstream direction; variant: packet loss.

## Expected Telemetry
Client-side call duration ↑, server-side query duration unchanged, timeouts if retries exhaust.

## Expected Detection / RCA
Latency SLI burn alert. Hypotheses: network path degradation (supported by client/server latency gap); DB slowness (contradicted); CPU (contradicted).

## Expected Remediation / Verification
No safe automatic remedy; planner proposes "no action / escalate" with evidence. If a sandbox-owned `reset_network_fault` action is added later, verification compares latency to baseline.

## Metrics
RCA accuracy, harmful-action rate (expected 0), escalation correctness.

## Results
Pending.

## Failure Cases
Direction-of-latency ambiguity [S-028: latency applies downstream by default]; proxy itself becomes a bottleneck.

## Conclusion
Pending.
