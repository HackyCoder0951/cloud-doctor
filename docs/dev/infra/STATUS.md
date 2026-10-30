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

## Not done
- Micro-VM sandbox (needs the user to install Docker Sandboxes with sudo); spikes S1–S7 not run.
- Alertmanager and Grafana (not used by the MVP detector design).
- Worker-crash, memory and other fault observations; scale and rollback paths.
- Dependency lock for the base images beyond tags; no image digests pinned yet.

## Assumptions / risks
- Plain Docker on the developer machine (rootful daemon); the host Docker daemon is root-equivalent (see ADR-007 residual risk).
- Image tags pinned: prometheus v3.15.1, loki and promtail 3.6.11, redis 7-alpine, postgres 18, python 3.13-slim. Not checked for security advisories.
