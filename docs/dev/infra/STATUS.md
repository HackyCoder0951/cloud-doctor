# Stream A (infra and sandbox) — status

Branch `stream/infra`. Updated 2026-10-31. Honest summary; nothing here is an experiment result.

## Done (verified by running the commands shown)
- Simulated application (api, worker, loadgen, probe sidecar) on stdlib + three pinned libraries; JSON logs to stdout and to a shared log volume.
- Compose stack: sandbox network is **internal**; only api (127.0.0.1:18000), Prometheus (127.0.0.1:9090) and Loki (127.0.0.1:3100) are published, loopback only; no host paths and no Docker socket mounted; sandbox containers carry `cloud-doctor.sandbox=true`, infrastructure containers do not; restart policy `no`.
- Prometheus scrape configuration **generated from the service catalog** (`infra/tools/gen_prometheus.py`).
- Loki + Promtail log path through a shared named volume (no Docker socket, no host paths).
- `make up`, `make smoke`, `make down`, `make reset`.
- `make smoke`: **PASS** on 2026-10-31 (all 17 checks: targets up, probes up, ~9.9 requests/s, no 5xx at steady state, queue depth present, required metrics present, Loki returns api logs).
- `infra/tools/fault_check.py` — one observation (N=1) of a Redis stop and restart: `cd_service_up{service="redis"}` fell to 0 about 6 s after the stop, `cd_dependency_up{service="api",dependency="redis"}` to 0 at about 9 s, `queue_depth` disappeared at about 12 s, the api 5xx ratio reached about 1.0 at about 15 s (15 s rate window), the api error logs were queryable in Loki; after the restart the probe returned to 1 within 3 s and the api error ratio fell below 1% by about 15 s. **Single observation; not an experiment result.**
- Finding confirmed: `up{service="redis"}` stays 1 while Redis is down (the scrape target is the probe sidecar), so detectors must use `cd_service_up` (as `contracts/telemetry.md` states).

- Cloud re-run (2026-10-30, plain Docker daemon started inside the cloud container; image builds needed the environment's proxy CA via a local, uncommitted compose override): `make smoke` **PASS**, 17 checks again.
- `infra/tools/fault_worker.py` — one observation (N=1) of `docker kill cd-worker` and restart: `up{service="worker"}` fell to 0 within about 3 s of the kill, processing rate dropped below 0.1 jobs/s by about 9 s; after `docker start`, `up` was 1 at about 3 s, processing resumed at about 9 s, and the backlog (855 jobs at restart) drained to 0 by about 24 s. **Single observation; not an experiment result.**
- Finding: `queue_depth` is exported by the worker, so while the worker is dead the series is **absent** instead of growing; the backlog is only visible after restart. Detectors for a worker crash must rely on `up`/absence of worker series, not on a rising `queue_depth`. (Candidate addition to `contracts/telemetry.md`; contract not changed here.)

- `cd_queue_length{service="redis",queue="jobs"}` added to the probe sidecar (change request backend-1; `contracts/telemetry.md` updated, additive). One N=1 observation after the change: steady value 3; with the worker killed it rose to 195 in 24 s while `queue_depth` was absent; after the restart it fell to 2; with Redis stopped it was absent and returned when Redis did. `make smoke` has one more check (18 total). **The backend does not use this metric yet** (its detector still reads `queue_depth`).

## Not done
- Micro-VM sandbox (needs the user to install Docker Sandboxes with sudo); spikes S1–S7 not run.
- Alertmanager and Grafana (not used by the MVP detector design).
- Memory and other fault observations; scale and rollback paths.
- Dependency lock for the base images beyond tags; no image digests pinned yet.

## Assumptions / risks
- Plain Docker on the developer machine (rootful daemon); the host Docker daemon is root-equivalent (see ADR-007 residual risk).
- Image tags pinned: prometheus v3.15.1, loki and promtail 3.6.11, redis 7-alpine, postgres 18, python 3.13-slim. Not checked for security advisories.
