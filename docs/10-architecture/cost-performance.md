# Cost and Performance Model

**Status:** model and *illustrative* calculations. Prices are as listed on Anthropic's pricing page when read on 2026-10-31 (the page shows no "last updated" date) [S-083]; they change. Token counts below are **assumptions**, not measurements.

## Cost drivers (RESEARCH FINDING where cited)

| Driver | Source/notes |
|---|---|
| LLM tokens: input, output, cache writes/reads, batch | Pricing structure and multipliers [S-083, S-085] |
| Telemetry storage | Prometheus local storage; cardinality [S-006, S-007]; Loki label limits [S-017, S-051] — **not quantified** |
| Compute for sandbox and Cloud Doctor | Not measured |
| Self-hosted model hardware and operations (C3) | Not found in sources; measure |
| Engineering/ops effort | Out of scope |

## Per-token prices read (USD per million tokens) [S-083]

| Model | Input | Output | Cache read | 5-min cache write |
|---|---:|---:|---:|---:|
| Haiku 5.5 (prompt ≤ 100k tokens) | 0.10 | 0.50 | 0.01 | 0.125 |
| Sonnet 5.5 | 2 | 10 | 0.10 | 2.50 |
| Opus 5.5 | 4 | 20 | 0.20 | 5 |
| Fable 5.1 | 10 | 50 | 0.25 | 12.50 |

Other stated modifiers: Batch API gives a 50% discount on input and output; caching multipliers stack with batch and data-residency pricing; a 1.1× multiplier applies for US data residency (Claude 4.6+); Haiku 5.5 prompts over 100k tokens cost more. Minimum cacheable prompt is 512 tokens for the 5.5 models [S-085]. Newer tokenizers produce about 30% more tokens for the same text, so **recount against the target model** with the token-counting endpoint (an estimate; free but rate-limited) [S-084]. Fable 5.1 is a "Covered Model" requiring 30-day retention [S-086].

## Measuring instead of assuming

The existing `rca-agent` supports `-dry-run`, which prints the exact prompt it would send (see `reuse-from-existing-projects.md`). Running it against real netmon data, then passing the printed prompt to the token-counting endpoint for the target model [S-084], gives a **measured** input size to replace the assumed 8,000 tokens below. Note that the agent's prompt is a compact summary of nine signals plus up to 200 log lines; Cloud Doctor's bundle will differ (evidence IDs, time structure), so re-measure with the real bundle.

## Formula

```text
cost_per_incident = Σ_calls [ in_tokens × p_in + out_tokens × p_out ] / 1e6
                    (− savings from cache reads on repeated prefix tokens)
monthly_cost      = incidents_per_month × cost_per_incident
```

## Illustrative calculation (ASSUMPTION — to be replaced by measured token counts)

Assume per incident: 3 LLM calls, 8,000 input tokens each (evidence bundle + instructions + schema), 1,500 output tokens each → 24,000 input and 4,500 output tokens.

| Model | Input cost | Output cost | Per incident |
|---|---:|---:|---:|
| Haiku 5.5 | $0.0024 | $0.00225 | **≈ $0.0047** |
| Sonnet 5.5 | $0.048 | $0.045 | **≈ $0.093** |
| Opus 5.5 | $0.096 | $0.090 | **≈ $0.186** |
| Fable 5.1 | $0.24 | $0.225 | **≈ $0.465** |

At 100 incidents a month these would be roughly $0.47, $9.30, $18.60 and $46.50 respectively **under the assumed token counts**. The point is the ratio between tiers and that cost scales linearly with incident count and bundle size — not the absolute figures. Caching the static prefix (system prompt, schema, tool definitions) would reduce input cost on repeated calls; the saving was not computed because the cacheable share is unknown.

## Other channels

- **C3 local:** no per-token fee; costs are hardware, power and operations. Not quantified (no sizing source read); benchmark throughput and latency on the client's hardware.
- **C2 cloud-hosted and C4 gateways:** per-token prices may differ from the vendor's; **not read**.
- **C0:** zero LLM cost.

## Latency and performance (HYPOTHESIS; to measure)

- Detection latency is bounded by scrape interval, rule `for`, and Alertmanager `group_wait` (30 s default) and `group_interval` (5 min default) [S-060]; the simulation will override these and report them.
- LLM latency per call (and first-use grammar compilation for strict schemas, cached 24 h [S-055, summary]) adds to time-to-diagnosis but **not** to detection or recovery, because the deterministic path does not wait for the LLM (design rule: LLM calls are asynchronous and time-boxed; the deterministic report is published first).
- Overhead of Cloud Doctor's own scraping and queries on the sandbox: unmeasured.

## Controls (DESIGN DECISION)

Token and call budgets per incident and per day; bundle size cap; model tier per task (cheap tier for summarisation, higher tier only on ambiguity — whether this improves accuracy is a hypothesis); prompt caching for static prefix; batch mode for offline evaluation runs; cost recorded in the audit log per incident; hard stop to C0 when the budget is exceeded.

## What will be measured

Tokens in/out per incident, cache hit share, LLM latency percentiles, cost per incident per channel and model, telemetry volume per hour, Prometheus/Loki resource use, evidence-store growth. **All pending.**

## References

S-006, S-007, S-017, S-051, S-055, S-060, S-083–S-086.
