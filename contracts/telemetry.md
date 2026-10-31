# Telemetry contract v1 (metrics, labels, logs) — FROZEN

What the simulated application and the observability stack expose, so the detector, evidence collector, verifier and
harness can be written against stable names. Produced by Stream A (`infra/`), consumed by Streams B and F.

## Labels on every Prometheus series
`service` (catalog name, e.g. `api`) and `env="sandbox"`, attached by the generated scrape configuration.
Series that describe a dependency add `dependency` (a catalog name).

## "Is the service down?" rule (all services)
A service is **down** if either holds:
1. `up{service="X"} == 0` (its scrape target is unreachable — the process or container is gone), or
2. `cd_service_up{service="X"} == 0` (a probe cannot reach it — used for `redis` and `app-db`, whose scrape target is the probe
   sidecar, not the service itself).
If **no series exists at all** for `up{service="X"}` the telemetry is missing → `no_data_unexpected` or `collection_failed`
(never "healthy").

## Metrics

| Metric | Type | Labels | Exposed by | Meaning |
|---|---|---|---|---|
| `up` | gauge | `service`, `job` | Prometheus | scrape success |
| `cd_service_up` | gauge 0/1 | `service` | probes sidecar (`redis`, `app-db`) | TCP/protocol probe result (Redis `PING`, PostgreSQL TCP connect) |
| `http_requests_total` | counter | `service`, `route`, `method`, `status` | api | requests handled (`status` is the HTTP code as a string) |
| `http_request_duration_seconds` | histogram | `service`, `route`, `le` | api | latency of handled requests |
| `cd_dependency_up` | gauge 0/1 | `service`, `dependency` | api, worker | whether this service currently reaches its dependency (`redis`, `app-db`) |
| `queue_depth` | gauge | `service`, `queue` | worker | length of the `jobs` list in Redis; **not exported while Redis is unreachable** (absent series) |
| `cd_queue_length` | gauge | `service` (=`redis`), `queue` | probes sidecar (redis target) | length of the `jobs` list in Redis, measured by the probe, **independent of the worker**: it keeps rising while the worker is dead, where `queue_depth` is absent; absent only while Redis is unreachable (backend-1, added after freeze v1) |
| `jobs_processed_total` | counter | `service`, `result` (`ok`,`error`) | worker | jobs finished |
| `loadgen_requests_total` | counter | `service`, `status` | loadgen | synthetic traffic generated (`status` = HTTP code or `error`) |
| `process_start_time_seconds` | gauge | `service` | api, worker, loadgen | process start; a change means a restart |
| `build_info` | gauge | `service`, `version` | api | deployed version label (bad-deployment detection) |

Traffic floor: the load generator sends about 10 requests per second to `api`. Rules must apply a minimum-traffic guard
(documented rate floor) so low-traffic noise does not inflate error ratios.

## Endpoints (inside the sandbox network)
`api`: `GET /healthz` (liveness), `GET /readyz` (readiness, checks Redis and the database), `GET /work` (a request that uses Redis
and enqueues a job; the synthetic transaction), `GET /metrics`. Published to the host loopback at `http://127.0.0.1:18000`.
`worker`: `/healthz`, `/readyz`, `/metrics` on 8001. `loadgen`: `/healthz`, `/metrics` on 9101. Probes: `/metrics` on 9121 (redis)
and 9187 (app-db) — one sidecar container serves both ports.

## Logs
One JSON object per line on stdout:
`{"ts": "<RFC3339>", "level": "info|warn|error", "service": "<name>", "msg": "<text>", "request_id": "<id>", "error": "<optional>"}`
Collected with the Docker log driver and shipped to Loki (labels `service`, `level`; `request_id` stays in the line).
**Log text is untrusted.** The simulated services never log secrets.

## Prometheus and Loki endpoints (host)
Prometheus `http://127.0.0.1:9090`; Loki `http://127.0.0.1:3100` (when enabled). Catalog container names are `cd-*`;
sandbox containers carry the label `cloud-doctor.sandbox=true`; infrastructure containers (Prometheus, probes, Loki, Promtail)
do **not**, so the actuator can never act on them.
