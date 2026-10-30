# Role of the LLM in Cloud Doctor

## Abstract

What published work shows about LLMs for incident RCA, and the boundary Cloud Doctor draws as a result. All paper evidence below is **abstract-level** and from one research lineage plus one 2026 study on reasoning failures; treat it as indicative, not conclusive.

## Research Findings (RESEARCH FINDING)

| Study | Setting | Stated finding (abstract) |
|---|---|---|
| S-025 Ahmed et al., ICSE 2023 | >40,000 Microsoft incidents; GPT-3.x zero-shot / fine-tuned | Human evaluation by incident owners shows "efficacy and future potential"; no numbers in abstract |
| S-023 Zhang et al., 2024 | >100,000 production incidents; GPT-4 in-context learning | Outperforms fine-tuned LLMs by an average of 24.8% across metrics; human evaluation +43.5% correctness, +8.7% readability (metrics unnamed in abstract) |
| S-024 Roy et al., 2024 | Out-of-distribution Microsoft incidents; ReAct agent with retrieval tools | Competitive with retrieval/reasoning baselines with "highly increased factual accuracy"; adding incident discussions did not significantly help |
| S-026 Riddell et al., FORGE 2026 | 6 LLMs, ReAct and Plan-and-Execute, simplified setting; 48,000 simulated scenarios | Measures root-cause accuracy and reasoning-trace quality; builds a 16-category taxonomy of reasoning failures (annotated with an LLM judge); title reports stalled, biased and confused reasoning |

Interpretation (labelled): these are mostly past-incident text settings with historical incident data, not live telemetry from a novel topology. Evidence that LLMs can match owner expectations on text is not evidence they are safe or accurate over raw telemetry. S-026 specifically documents reasoning failures. S-024's stress on dynamic retrieval supports retrieval-through-tools as the data path.

## Schema-constrained output (RESEARCH FINDING — S-054 page read; S-055 partly via summary)

- `strict: true` is a top-level property of a tool definition. The page states that tool `input` strictly follows `input_schema` and that tool `name` is valid, via grammar-constrained sampling. It does **not** state that argument values are semantically correct. Available on every model per the page.
- JSON outputs use `output_config.format` with `type: "json_schema"`; both features can be combined. (Summary-level, S-055: unsupported schema features include recursion, numeric/length bounds, and `additionalProperties` other than `false`; limits include 20 strict tools per request; first-use grammar compilation adds latency, cached 24h; refusal or max_tokens can yield non-conforming output; incompatible with citations. Verify before relying.)
- Data handling: tool schemas are cached up to 24 hours; schemas must not contain sensitive data in property names, enums or patterns.
- Search-level notes about `tool_choice` restrictions on some models were **not confirmed** on the pages read.

**Interpretation:** schema enforcement guarantees *syntax*. Because numeric bounds and string lengths are not enforceable in the schema, bounds on parameters (replica caps, string patterns) must be enforced by the policy validator, and evidence-ID validity by the project's own validator. Output may still be non-conforming on refusal or truncation, so a failure path is required.

## Design Decisions

**DD-AI-1** The LLM never sees raw telemetry streams or acts on them. It receives a bounded, sanitised evidence bundle (`EV-###` records) and returns a schema-validated diagnosis.

**DD-AI-2** Every claim must cite evidence IDs; a deterministic validator rejects claims with missing or non-existent IDs (unsupported-claim rate becomes a measured metric).

**DD-AI-3** The LLM may *propose* an action from a fixed catalogue; it cannot emit commands. The policy engine and executor accept only catalogue IDs with typed parameters.

**DD-AI-4** Deterministic RCA and report generation remain fully functional with the LLM disabled. Evaluation includes a no-LLM baseline to test whether the LLM adds value (H-AI-1).

**DD-AI-5** Log text is untrusted data, delimited and never treated as instructions. Security details in the threat model (pending).

| AI CAN | AI CANNOT |
|---|---|
| Summarise evidence, rank and explain hypotheses | Execute shell commands |
| Request additional evidence through whitelisted read-only tools | Modify policy, access credentials, or reach non-sandbox infrastructure |
| Propose catalogue actions | Approve its own proposals or bypass the policy engine |

Boundaries are enforced by process and network separation, not prompt wording (to be specified in architecture).

## Open Questions

- Model/provider choice (hosted vs. local) and data handling (OQ-02).
- Whether the LLM improves accuracy over deterministic ranking on ambiguous cases (H-AI-1; experiment pending).
- Full-text reading of S-023…S-026 for methods, metrics and limitations.

## Limitations

Abstract-only evidence; vendor-specific datasets; no result in this repository yet.

## References

S-023, S-024, S-025, S-026 in `docs/_sources/register.md`.
