# backend-1: queue backlog is invisible while the worker is dead (contracts/telemetry.md)

**Stream:** B (backend). **Status:** request; the backend works around it with a documented assumption.

## What is wrong
`contracts/telemetry.md` says `queue_depth{service="worker",queue="jobs"}` is exposed **by the worker**. When the worker
process is dead (EXP-02, worker crash) the series disappears at the next scrape, so the very symptom the experiment relies on
("queue depth rising while the API is healthy") cannot be observed from Prometheus. It also disappears while Redis is unreachable
(documented), so the backlog is invisible in exactly the two failures where it matters.

## Proposed change
Have the probe sidecar (which already talks to Redis for `cd_service_up{service="redis"}`) also export the length of the `jobs` list,
for example `cd_queue_length{service="worker",queue="jobs"}` (absent only when Redis itself is unreachable).

## Impact
Stream A (probe sidecar), Stream B (detector `queue_growth`, RCA worker-crash evidence), Stream F (harness expectations).

## Workaround used by the backend
The synthetic fixtures keep publishing `queue_depth{service="worker"}` after the worker dies (as if exported from the Redis side), and
the detector/RCA treat an *ended* series as a signal (`queue_absent`). Without this change the worker-crash diagnosis loses its
"backlog grows" claim and its confidence drops (the claim becomes an unknown), but it is still ranked first from the down signal.

## Resolution (coordinator, 2026-10-31)
**Applied (partly).** `cd_queue_length` exported by the probe sidecar, added to `contracts/telemetry.md`, smoke-checked, observed once on the sandbox. **Not applied:** the backend detector and RCA still read `queue_depth`, so `queue_growth` cannot fire for a dead worker; switching them to `cd_queue_length` (and adding it to the fixtures) is follow-up backend work.
