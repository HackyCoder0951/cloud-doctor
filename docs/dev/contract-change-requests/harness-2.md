# harness-2: `cause_id` vocabulary is not frozen

**What is wrong.** `diagnosis.json` only constrains `cause_id` to `^[a-z][a-z0-9_]{2,60}$`; the only example is `redis_unavailable` (and decoy `api_bug`, `network_partition`).
The evaluation framework requires a scenario-specific equivalence class defined in advance, which needs the ids the RCA engine will emit.

**Proposed change.** Publish the cause-id vocabulary (a list or enum, e.g. in `contracts/` or `docs/04-root-cause-analysis/`) and a stable mapping per catalog service and fault kind.

**Impact.** Backend (B) RCA; Harness (F) scenario files; evaluation validity (a wrong guess scores a correct diagnosis as wrong).

**Workaround used.** `experiments/scenarios/exp-*.yaml` list plausible ids, for example `redis_unavailable` and `redis_container_stopped` for EXP-01, `bad_deployment` and `api_bad_deployment` for EXP-07. These are ASSUMPTIONS written
before any run. They must be reconciled with the RCA ids before measuring top-1/top-3; until then diagnosis accuracy is not meaningful.

## Resolution (coordinator, 2026-10-31)
**Applied.** `contracts/cause_ids.md` published from the RCA engine's real output; EXP-05 and EXP-12 expected ids reconciled. EXP-06 and EXP-11 expect causes no RCA rule can emit.
