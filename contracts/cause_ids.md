# Cause-id vocabulary (diagnosis.hypotheses[].cause_id)

Added after contract freeze v1 as an **additive, descriptive** contract (change request harness-2). The schema `contracts/schemas/diagnosis.json` is unchanged (`^[a-z][a-z0-9_]{2,60}$`); this file says which values the deterministic RCA (`backend/rca/engine.py`) emits, so the experiment harness can define correct-answer sets in advance.

## Form
`<service>_<kind>` where `<service>` is the catalogue service name with `-` replaced by `_` (`app-db` -> `app_db`), and `<kind>` is one of (eight kinds):

| kind | meaning | emitted when (summary; the exact conditions are in `backend/rca/engine.py`) |
|---|---|---|
| `unavailable` | the service is down (container or process) | `cd_service_up`/`up` is 0 for the service |
| `bad_deployment` | a recent version change precedes the symptoms | build/version change event with symptoms after it |
| `memory_exhaustion` | memory grows to its limit; OOM kills | sustained memory growth or `oom_kill` event |
| `cpu_saturation` | CPU-bound: latency up, errors low | latency above SLO, CPU high, no error ratio |
| `connection_exhaustion` | running but out of connections | database service reachable but clients cannot connect |
| `network_latency` | the path to a dependency is slow while the dependency itself is not | client-side call p95 high on dependents, server-side probe time normal (database only) |
| `disk_full` | the filesystem used by the service is full | `fs_used_ratio` at or above 0.95 |
| `local_fault` | defect local to the service, not explained by a dependency (capped confidence) | symptoms on a service that is up and has no failing dependency |

Two ids have no service prefix:
- `telemetry_collection_failed` — part of the telemetry could not be collected; the state of the affected scope is unknown, not healthy.
- `undetermined_cause` — no candidate is supported by the evidence.

## Ids observed from the engine on the synthetic fixtures (`python -m backend.demo_replay`, 2026-10-31)
`redis_unavailable`, `worker_unavailable`, `loadgen_unavailable`, `app_db_unavailable`, `app_db_connection_exhaustion`, `app_db_network_latency`, `api_disk_full`, `api_bad_deployment`, `worker_bad_deployment`, `api_memory_exhaustion`, `api_cpu_saturation`, `api_local_fault`. These came from **synthetic fixtures, not sandbox runs**; the set of possible ids is the form above.

## Not emitted by any rule
Server-versus-client latency attribution is covered only for databases (`network_latency`); there is no rule for latency toward Redis, and the network path itself is not measured (the cause is inferred by exclusion).
