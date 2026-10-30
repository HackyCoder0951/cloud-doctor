# Future Research

Candidate directions, not commitments. Each is a HYPOTHESIS or OPEN QUESTION.

1. **Does the LLM add measurable value?** Paired LLM-on/off runs on ambiguous scenarios (H-AI-1).
2. **Learned vs. rule-based detection/RCA** on the same scenarios, using methods surveyed in S-020/S-021 (e.g., BARO-style scoring, S-047) as comparison points. Prerequisite: full-text reads.
3. **Kubernetes variant** (Kind): probes, rollouts, RBAC and NetworkPolicy enforcement; verify CNI behaviour in Kind (unconfirmed).
4. **Tracing** via OpenTelemetry to test whether latency attribution improves.
5. **Policy-as-code with OPA**, including decision-log-based audit.
6. **Window scaling for burn-rate alerting** in short simulations: validity unknown.
7. **Confidence calibration** of ranked hypotheses with enough runs.
8. **Adversarial evaluation**: larger poisoning/injection corpora; adaptive attackers.
9. **Cost study**: telemetry volume, cardinality, token cost per incident.
10. **Larger/more realistic topologies** and replayed real incident data (if available), testing generalisation limits flagged by S-021.
