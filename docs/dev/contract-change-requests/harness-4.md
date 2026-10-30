# harness-4: telemetry contract has no CPU, memory, disk or DB-connection signals

**What is wrong.** `contracts/telemetry.md` defines no metric for container or process CPU, memory, filesystem usage, database connections or query duration, nor client-side dependency call duration.
Scenarios EXP-03 (CPU), EXP-04 (memory), EXP-05 (connection exhaustion), EXP-06 (server vs client latency), EXP-09 (CPU) and the draft EXP-11 (disk) assume such signals to distinguish their causes.

**Proposed change.** Either add the metrics (for example cAdvisor/process collectors, a postgres exporter on the app-db probe sidecar, `db_call_duration_seconds` on the api) to the telemetry contract, or accept that these causes are only inferable by exclusion.

**Impact.** Infra (A), Backend (B) rules, Harness (F) expectations.

**Workaround used.** The affected required signals are declared `unavailable_in_mvp` in the scenario files, so `python -m harness check-recoverability` reports those scenarios as `not_recoverable` (a design-time finding, not a result). The scenarios stay runnable.
