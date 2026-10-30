# Glossary

Definitions are project working definitions; those with a source are marked.

| Term | Meaning |
|---|---|
| SLI | Carefully defined quantitative measure of some aspect of service level [S-001] |
| SLO | Target value or range for an SLI [S-001] |
| SLA | Contract with consequences for missing SLOs [S-001] |
| Error budget | Allowed rate of missing the SLO [S-001] |
| Burn rate | Observed error rate ÷ (1 − SLO target) (standard arithmetic; see `sli-slo-sla.md`) |
| Golden signals | Latency, traffic, errors, saturation [S-002] |
| Symptom / cause | "What's broken" vs. "why" [S-002] |
| Observability | Understanding a system from the outside by asking questions without knowing its internals [S-008] |
| Evidence (EV-###) | Stored observation with source, query, event time and collection time |
| Hypothesis | Candidate cause with confidence, supporting and contradicting evidence |
| Confirmed root cause | Hypothesis validated by verification or experimental ground truth — never by temporal order alone |
| Catalogue action | Typed, pre-defined remediation the executor can run |
| Policy engine | Component that evaluates proposals against rules; default deny |
| Executor | Minimal component that performs approved catalogue actions in the sandbox |
| Verification | Post-action check of readiness, dependencies, SLIs, synthetic transaction, regression |
| Stability window | Period recovery criteria must hold continuously (length TBD) |
| Blast radius | Set of services/data an experiment or action can affect [S-027] |
| Fail closed | On failure of a safety dependency, deny action |
| MTTD / MTTR | Project definitions in `mttd-mttr.md` (primary-source definitions pending) |
| Hysteresis / flapping | Persistence requirements that stop alerts oscillating; Prometheus `for` and `keep_firing_for` [S-005] |
| Recording rule | PromQL expression pre-evaluated and stored as its own series so dashboards/alerts query a cheap precomputed value (project definition) |
| Exemplar | Sample attached to a metric point that links to the trace that produced it (project definition) |
| Tail sampling | Deciding which traces to keep after seeing the whole trace, e.g., keep all errors and slow spans (project definition) |
| RPO / RTO | How much data loss is tolerable / how long recovery may take (project definition) |
| Expected-down state | A declared, time-limited condition (maintenance, intentional fault, drained target) in which missing data is not an incident |
| Missing-signal states | *No data (expected)*, *no data (unexpected)*, *collection failed* |
| Untrusted telemetry | Log or metric content that may be attacker- or fault-controlled |
