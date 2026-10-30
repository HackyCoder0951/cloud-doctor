# Evaluation Framework

**Status:** Design. Targets are not results. Any number below is a *definition*, not a measurement. Measurement is pending.

## Ground truth

The harness logs the injected fault and its timestamp. A hypothesis is **correct** iff its cause identifier matches the scenario's ground-truth cause (scenario-specific equivalence classes defined in advance, e.g., `redis unavailable` ≡ `redis container stopped`).

## Metrics

### Detection

- **MTTD** (per scenario, then summarised): `t_detect − t_inject`; also `t_detect − t_impact`.
- **Precision** = TP incidents / (TP + FP); **Recall** = TP / (TP + FN), over experimental and control runs; **FP rate** from control runs per hour.
- Report distribution (median, min, max), not only means.

### Diagnosis

- **Top-1 / top-3 accuracy**: fraction of runs with correct cause ranked 1st / within 3.
- **Evidence coverage**: fraction of claims in the diagnosis backed by ≥1 valid evidence ID.
- **Unsupported-claim rate**: claims with missing, non-existent, or irrelevant evidence IDs ÷ all claims (irrelevance requires a rubric; mark human-judged items).
- **Confidence calibration**: bin confidences and compare to empirical accuracy (e.g., expected calibration error); meaningful only with enough runs — state N.

### Recovery

- **Remediation success rate**: runs where verification passes ÷ runs where an action executed.
- **TTR (verified)**: `t_recover − t_inject` with stability window included.
- **Failed remediation rate**, **rollback rate**, **escalation rate**.

### Safety

- **Unauthorized action count** (target 0): executed actions without a matching allow decision.
- **Policy violations**, **remediation loops** (attempts above configured max), **max blast radius** (services affected by any action).
- Adversarial suite: injection corpus, malformed proposals, non-sandbox targets, dependency-down cases.

### AI

- **Hallucination rate**: claims contradicted by evidence ÷ claims (judged against stored evidence).
- **Evidence-grounding rate**, **tool-call accuracy** (valid, authorized, relevant calls), **action-recommendation accuracy** (matches scenario's accepted-action set).
- **Value-add**: paired comparison of LLM-on vs. LLM-off on identical runs. This answers H-AI-1.

## Statistics

Report N, ranges, and confidence intervals where N allows; avoid claiming differences from small samples; pre-register scenarios and success criteria before running. Note nondeterminism: fix model ID, temperature and prompts, and repeat runs.

## Lessons from evaluation critiques (search-level — S-062, S-063; unopened)

- Kim et al. (AAAI 2022) report that the **point-adjust** protocol — crediting a whole anomalous segment if any point is flagged — can inflate time-series anomaly detection results so much that even random scores look state-of-the-art, and that an untrained model matched published methods. **Consequence:** Cloud Doctor scores detection per injected incident (was an incident opened for each fault, and when), never with point-adjusted segments, and reports an untrained/trivial baseline (e.g., fixed threshold) next to any sophisticated detector.
- OpenRCA (ICLR 2025) is an LLM RCA benchmark (335 failures, >68 GB telemetry in search snippets), with reported low absolute accuracy for the baseline agent and with a vendor critique arguing labels are not always recoverable from the data. **Consequence:** report a trivial/deterministic baseline, and check that each scenario's ground truth is actually recoverable from the telemetry Cloud Doctor can see (add a per-scenario "recoverability check").
- These are secondary readings; confirm in the original papers before citing numbers.

## Threats to validity

Circular evaluation; synthetic fault cleanliness; LLM-as-judge bias if used (cf. S-026 used LLM judging for failure taxonomy); human-judged rubrics need a second rater.

## Reporting rule

Until a metric has been measured the report says: "Target metric defined; experimental measurement pending."

## References

S-026, S-027 in `docs/_sources/register.md`.
