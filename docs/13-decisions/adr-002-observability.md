# ADR-002: Observability Stack

## Status
Proposed (Loki/OTel parts provisional).

## Context
Need metrics, logs and events for ten fault classes. Prometheus read in full [S-004–S-007]; Loki read [S-016, S-017, S-011]; OpenTelemetry primer and logs signal read [S-008, S-009]; no head-to-head alternatives researched.

## Problem
Which tools, and does the project need tracing?

## Options
### Option A — Prometheus + Alertmanager + Loki + Grafana, no tracing
Metrics pull model fits a small static topology; Loki is label-indexed with cardinality constraints; Grafana as secondary view.
### Option B — Option A + OpenTelemetry Collector and tracing
Adds correlation across requests; more moving parts.
### Option C — Minimal custom collection (scrape/health endpoints, container logs to PostgreSQL)
Fewer services; reimplements capabilities and is less recognisable to SRE reviewers.

## Decision
Option A, with structured logs carrying a request/correlation ID. Tracing deferred; reconsider after EXP-06/08.

## Rationale
Covers golden signals [S-002]; Alertmanager grouping/inhibition [S-004] avoids reimplementation; ecosystem recognisable for portfolio.

## Update 2026-10-31 (RESEARCH FINDING)

- Alertmanager route defaults: `group_wait` 30s, `group_interval` 5m, `repeat_interval` 4h [S-060]. These add delay to notification; for a fast simulation Cloud Doctor must override them, and the effect on MTTD must be reported with the configuration.
- Inhibition mutes target alerts when a matching source alert exists, with `equal` labels; the docs advise avoiding rules where an alert matches both sides [S-060]. This is compatible with S-002's caution about complex dependency suppression if used sparingly.
- The webhook payload (version "4") carries `groupKey`, `status`, `alerts[]` with labels, annotations, `startsAt`, `endsAt`, `fingerprint` [S-060]. Retry count/backoff for the alert webhook were **not found**.
- HA: at-least-once delivery, "fail open" under split-brain, duplicates possible, cluster traffic unencrypted by default [S-061]. Cloud Doctor's webhook consumer must therefore be **idempotent** (dedupe on `groupKey`/`fingerprint`).
- Loki limits: see `loki.md` (S-050, S-051).

## Update 2 — notification semantics and webhook retries (S-060, S-073, S-074)

- `group_interval` is a recurring timer starting after `group_wait`; at each tick Alertmanager sends if alerts newly fired or resolved, otherwise checks `repeat_interval`. `repeat_interval` is rounded up to a multiple of `group_interval`. `group_interval` also sets the **context timeout for each send**: a send longer than `group_interval` is cancelled [S-060, verbatim].
- Webhook retry behavior is **not stated in the configuration docs read**. A 2019 forum reply says Alertmanager retries on 5xx (treated as transient) and does not retry on 4xx; reloads re-send but restarts do not [S-073, Tier 3, dated; unverified for current versions]. A 2025 maintainer-labelled answer says Alertmanager tracks the last notification per group in a file and, if the alert did not resolve across restarts, will not re-send until `repeat_interval` [S-074].
- **Design consequences:** (1) Cloud Doctor's webhook endpoint must respond quickly (well under `group_interval`); (2) it should return 2xx once the alert is durably recorded, 4xx for permanently invalid payloads, and 5xx only for transient failures, accepting that retries/duplicates are possible; (3) processing must be idempotent on `groupKey`/`fingerprint` (also required by HA at-least-once delivery [S-061]); (4) the effect of `group_wait` (30 s) and `group_interval` (5 min) on MTTD must be configured for the simulation and reported with each result; (5) test the actual retry behavior against the pinned Alertmanager version as part of Phase 3.

## Update 3 — reuse of observability-infra (project analysis)

The user's `observability-infra` repository already implements the chosen stack (Prometheus, Alertmanager, Loki, Promtail, Grafana, Tempo, OTel Collector, exporters) with pinned image versions and a flag-driven wrapper. Proposal: use it as the sandbox observability base, run inside the MicroVM. Required changes and the issues found (threshold-style "SLO" rules, low-traffic recording rule, Alertmanager grouping by alertname, missing promtool/amtool checks in CI, credential fallbacks in the tracked compose file) are in `docs/10-architecture/reuse-from-existing-projects.md`. This does not change the decision; it removes build effort and supplies the pinned versions the ADR needed.

## Tradeoffs
Prometheus data is sampled and not exact [S-007]; Loki label discipline required [S-017]; Grafana does not replace an incident-centric UI.

## Consequences
Telemetry-gap detection needed (health `UNKNOWN`); Cloud Doctor owns incident model even if consuming Alertmanager webhooks.

## Reconsideration Conditions
Loki ingestion/ordering issues (unverified); experiments showing latency attribution needs traces; Option C if operational overhead dominates.

## References
S-002, S-004–S-009, S-011, S-016, S-017.
