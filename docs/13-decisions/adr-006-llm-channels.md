# ADR-006: Hybrid LLM Delivery Channels

## Status
Proposed. Resolves OQ-02 in principle (channel model chosen; specific models and vendors left to client policy).

**Prototype scope (user decision, 2026-10-31): C0 (no LLM) and C1 (vendor API) only.** C2 (cloud-hosted), C3 (self-hosted/local) and C4 (gateway) remain in the design for clients but are **not implemented in the prototype**. The gateway interface is still written channel-neutral so C2/C3 can be added without changing the validators or policy. Consequences: no local-model quality or hardware measurements will be produced in the prototype; any claim about C3 stays a hypothesis; the C1 model class must be chosen so that retention terms suit the demo data (note the 30-day retention for "Covered Models" in `llm-channels.md`).

## Update 2026-10-31 — C1 provider is NVIDIA NIM (hosted)
The user has NVIDIA NIM API access, so the prototype's C1 channel uses an OpenAI-compatible adapter against the NIM hosted endpoint rather than a different vendor. Verified facts and unknowns (structured-output enforcement, tool calling, rate limits, data-handling terms) are in `docs/05-ai/llm-channels.md` [S-122–S-126]. Consequences: schema enforcement and citation checks stay entirely client-side; evidence is pre-fetched, not tool-called; data sent is limited to synthetic/redacted evidence until the terms are read; the cost model uses credits/rate limits rather than the per-token prices read for another vendor (`cost-performance.md` must be treated as an illustration of method only for NIM). The decision itself (channel model, C0/C1 in the prototype) is unchanged.

## Context
Clients differ on data sensitivity, cost and connectivity. Retention and training terms differ by vendor, cloud, and model class [S-086, S-087, S-089]. Self-hosted serving exists with schema-constrained output but with security caveats [S-090, S-091]. The AI layer must remain optional (ADR-001, FR-006).

## Problem
How is the LLM delivered so that one product serves air-gapped, cloud-contract and vendor-API clients without weakening safety?

## Options
### Option A — single hosted vendor
Simplest, but excludes data-sovereign clients and creates vendor lock-in.
### Option B — local only
Maximum data control, but unmeasured quality and high ops burden.
### Option C — hybrid channels behind one gateway (C0–C4)
Client policy selects channels; same validators and policy for all.

## Decision
Option C. Channels C0–C4 as defined in `docs/05-ai/llm-channels.md`. C4 (third-party gateway) is listed but **not researched** and is not part of the prototype.

## Rationale
Matches client variability; keeps safety logic channel-independent; makes the value of the AI layer measurable per channel against C0.

## Tradeoffs
More integration work (adapter per channel); capability differences (tool calling, structured output) require flags and fallbacks; more test matrix; legal/compliance terms must be re-checked per client.

## Consequences
- LLM gateway with a single interface and capability flags.
- Per-tenant channel policy; failover never moves data to a less restrictive channel.
- Audit records channel, model, version, parameters, token counts.
- Evaluation harness runs per channel.
- README and client documentation present the channel table and decision guide.

## Reconsideration Conditions
Drop channels that evaluation shows add no value over C0; add C4 only on a concrete client need; revisit if provider terms change materially.

## References
S-054, S-055, S-083–S-091.
