# Grafana Loki

## Abstract

Assessment of Loki as Cloud Doctor's log store, from the Loki overview, label best-practice and cardinality pages [S-016, S-011, S-017].

## Research Findings (RESEARCH FINDING)

- Loki is a log aggregation system inspired by Prometheus; logs are pushed. It **indexes only labels per stream, not log content**; content is compressed in chunks [S-016].
- Static, bounded labels (cluster, app, namespace, environment) are fine. Dynamic labels should be low-cardinality — "single digits, or maybe 10's of values". Don't label ephemeral IDs (trace, order, request IDs); timestamps are high-cardinality [S-011, S-017].
- Default limit of 15 index labels [S-017]; per-tenant guidance of under 100,000 active streams applies to tenants over 10 TB/day and scales down for smaller ones [S-011].
- Filter expressions (`|= "level=error"`) are described as often about as fast as a dynamic label for many applications [S-011]. Query pattern: label matchers select streams, then line filters narrow.
- **Structured metadata** stores high-cardinality fields without enlarging the index [S-017].
- Loki "was not designed … to support high cardinality label values" [S-017]. The best-practice page references old Loki versions (1.4.0/1.6.0) — treat as possibly dated.

## Additional findings (RESEARCH FINDING; S-050, S-051 — `limits_config` read verbatim)

- Label limit: `max_label_names_per_series`, default 15, per-tenant and overridable via runtime config. Label value length default 2048.
- Out-of-order writes: `unordered_writes` default `true` (marked deprecated on the page); `increment_duplicate_timestamp` default `false`, with a note that it is imperfect because Loki accepts out-of-order writes.
- Sample age: `reject_old_samples` default `true`; `reject_old_samples_max_age` default 1 week; `creation_grace_period` default 10 minutes.
- Structured metadata: queried with a label filter expression and **no parser needed**, e.g. `{job="example"} | trace_id="0242ac120002"`; it is added to the labels of each returned line; metric queries may need `keep`/`drop` to avoid series-limit errors. Requires chunk format V4 (schema ≥ 13) and the `tsdb` index; defaults: 64 KB size and 128 entries per line, over-limit lines rejected with HTTP 400.

## Not verified

`out_of_order_time_window` (not found in the portions read); LogQL pipeline details; the unread ~60% of the configure page.

## Cloud Doctor Application (DESIGN DECISION, provisional)

- Labels: `service`, `env=sandbox`, optionally `level`. Request/correlation IDs stay in the log body or structured metadata.
- Retrieval pattern for evidence: query by `{service=...}` and time window, then filter. Each query is stored with its evidence record (provenance).
- Log content is **untrusted**; it passes a sanitiser before reaching any LLM (see threat model, pending).

## Alternatives

Direct container log scraping into PostgreSQL; OpenSearch/Elasticsearch. Not yet researched. For a 5-service sandbox, Loki's main benefit is Grafana integration; a justified simpler option may exist (**OPEN QUESTION**, feeds ADR-002).

## Risks

- Another service to run and fail; log-pipeline loss must register as telemetry gap.
- Time sync: ingestion ordering behavior unverified.

## References

- [S-016] https://grafana.com/docs/loki/latest/get-started/overview/
- [S-011] https://grafana.com/docs/loki/latest/get-started/labels/bp-labels/
- [S-017] https://grafana.com/docs/loki/latest/get-started/labels/cardinality/
