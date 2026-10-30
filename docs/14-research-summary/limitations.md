# Limitations and Open Gaps

Living document. Status as of 2026-10-31: **research in progress; no implementation; no experiments run.**

## Evidence-quality limitations

| ID | Limitation |
|---|---|
| L-01 | Page content was extracted by a fetch tool that converts pages through a model. Wording can differ from the live page. Quote only after verifying against the page. |
| L-02 | Several sources were read partially (see `_sources/register.md`: V-partial). Claims drawn from summaries are flagged where used. |
| L-03 | arXiv papers S-022…S-026 were read at abstract level only; S-020 and S-021 partially. No claim goes beyond what those reads support. |
| L-04 | Docker pages did not state that mounting `/var/run/docker.sock` or `docker` group membership is root-equivalent; this is not directly sourced yet. |
| L-05 | Kubernetes pod-lifecycle restart/back-off values came from a summary. |

## Research gaps (blocking Gate G1 or specific ADRs)

| Gap | Blocks |
|---|---|
| kind-specific statement on NetworkPolicy enforcement (minikube docs say Kindnet does not enforce, kind uses kindnetd — an inference, S-079/S-057; verify by test); local-VM option; kind rootless guide | ADR-004 |
| Tier 1 source for docker.sock / docker-group root-equivalence (Tier 3 sources now agree: S-075, S-076); socket proxy products | ADR-004, TM-04 |
| Webhook retry behavior of the pinned Alertmanager version (only a 2019 forum answer, S-073) — test in Phase 3 | ADR-002 |
| ~~Bayesian/probabilistic RCA background~~ partly closed (S-065–S-070); **no source validates probabilistic RCA on microservice telemetry**; S-069 pp. 11–29 unread | Domain F |
| ~~Anomaly detection document~~ written (`anomaly-detection.md`); S-062 and S-047 still unopened | Domain D |
| ~~MTTR definitions~~: vendor sources show the ambiguity (S-071, S-072); Google "Incident Metrics in SRE" (2021) not yet read | `mttd-mttr.md` |
| Unreadable sources (blocked or 403): two Stack Overflow questions, three Medium posts, vmheaven post — paste their text if they matter | — |
| ~~Loki ordering / label limit~~ closed in part (S-050, S-051); `out_of_order_time_window` not found; unread ~60% of configure page | ADR-002 |
| ~~OPA deployment/decision logs~~ closed (S-052, S-053); no fail-open/closed statement exists in docs read; Python integration still unresearched | ADR-005 |
| ~~Alertmanager config/HA~~ closed (S-060, S-061); webhook retry/backoff not found | ADR-002 |
| ~~Anthropic strict tool use~~ closed (S-054); structured-outputs schema limits via summary only (S-055); `tool_choice` restrictions unconfirmed | OQ-02 |
| Statistical/baseline anomaly detection beyond Prometheus functions; alert-correlation literature | Domain D completion |
| Bayesian/probabilistic RCA and causal reasoning background | Domain F completion |
| Formal definitions of MTTD/MTTR/MTBF from a primary source | `mttd-mttr.md` |
| Alertmanager config reference; Prometheus HA | ADR-002 |
| OPA deployment modes and Python integration; decision logging | ADR-005 |
| ~~LLM provider options / pricing / local option~~ addressed by hybrid channel design (ADR-006, S-083–S-091); still open: C2/C4 pricing, Microsoft Foundry terms, Bedrock training-use and inference encryption statements, local-model quality and hardware sizing, Anthropic standard retention periods (policy pages unread) | ADR-006 |
| Telemetry cost/cardinality quantification (cost model written with illustrative token assumptions only) | Domain Z |
| Full-text reads of S-020…S-026 | RCA and AI docs |

## Design limitations (known, deliberate)

- Sandbox only; no claim about production behavior.
- Small known topology; results will not generalise to large systems (cf. S-021 on synthetic-vs-real gaps).
- Injected faults are cleaner than natural ones.
- Scenarios and rules by the same author → circular-evaluation risk.
- Redaction and injection mitigations are imperfect; safety relies on technical separation instead.

## Not claimed

Production readiness, autonomous production remediation, guaranteed RCA accuracy, hallucination-free AI, zero false positives.
