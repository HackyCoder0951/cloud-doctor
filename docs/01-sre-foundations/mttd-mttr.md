# MTTD, MTTR and Recovery Timing

## Abstract

Cloud Doctor must report detection and recovery speed credibly. No authoritative definition has been read yet, so this document sets **project definitions** and marks sourcing as pending.

## Sourcing status

**Unverified / requires validation:** formal definitions of MTTD, MTTR (including the ambiguity between repair, recovery, respond, resolve), and MTBF have not yet been read from a primary source. Candidate sources to fetch: Google SRE book/workbook incident and postmortem chapters; vendor incident-management documentation. Until then the definitions below are DESIGN DECISIONs, not cited facts.

## What secondary sources say (Tier 3, search snippets only — S-049)

- MTTD is commonly described as average delay between failure start and detection; MTTR as time from failure start to restoration; MTTA acknowledgment; MTBF time between failures.
- Sources **disagree** on what "R" means (recovery/restore vs. resolve/repair): restoration stops the clock when service returns; a stricter reading waits until the root cause is fixed. One suggests tracking restoration and root-cause resolution separately.
- Claims about DORA renaming (e.g., "Failed Deployment Recovery Time") and benchmark tiers conflict across sources and were **not verified** against DORA's own publications.
- One source recommends median and p90 over the mean because incident durations are skewed; this agrees with S-001's preference for percentiles but is not independent evidence.

### Update: two vendor articles read in full (Tier 3: S-071, S-072)

- **ClickHouse** [S-072]: MTTR = total downtime ÷ number of incidents; the "R" "is read at least four ways" (repair, recovery/restore, respond, resolve) and the page uses recovery/restore; MTTD = Σ detection delays ÷ incidents; MTTA = Σ acknowledgement delays ÷ incidents; MTBF = total operating time ÷ incidents. Caveats it lists: the mean is noise-dominated at typical incident counts; durations are skewed so use medians and split by severity; cross-company benchmarks are unreliable because incident definitions differ; MTBF is a poor fit for software failures clustered around deploys. It quotes a Google report ("Incident Metrics in SRE", Davidovič, 2021) as calling the mean "poorly suited for decision making or trend analysis" — **that report has not been read; the citation is unconfirmed** and is a to-fetch item.
- **OneUptime** [S-071]: similar formulas, but its MTBF definition says it *includes* repair time while its formula uses operational time only, and it states MTBF = MTTF + MTTR; it also presents unsourced benchmark tiers. **The two vendors define MTBF differently** and the OneUptime page is internally inconsistent, so neither is adopted as a definition.
- Both are vendor marketing pages. They show the *ambiguity* of the terms, which is the finding that matters here.

**Consequence:** the project must define its terms explicitly and report *verified-recovery time* (restoration confirmed by the verifier), kept separate from any root-cause resolution. Primary-source definitions remain a gap.

## Project definitions (DESIGN DECISION)

In experiments, ground-truth timestamps are known because the fault is injected.

```text
t_inject   fault injection begins (experiment harness, ground truth)
t_impact   first SLI breach in telemetry (first user-visible symptom)
t_detect   Cloud Doctor opens an incident
t_diagnose first ranked hypothesis published
t_action   remediation executed in sandbox
t_recover  verification passes and holds for the stability window

MTTD_run  = t_detect  − t_inject
TTD_impact = t_detect − t_impact
TTR_run   = t_recover − t_inject         (recovery time as defined by verified recovery)
```

Reported figures are **means (and distributions) over repeated runs**; "mean" in MTTD/MTTR only makes sense across many incidents, so single-run values are labelled "time to detect / time to recover".

Note: `t_recover` requires a stability window, so TTR includes verification time by construction. A restart that makes a container run again is *not* recovery (Domain O).

## Why this matters

- Averages hide tails [S-001 on percentiles]; report median and max alongside means.
- Detection delay is partly set by the detector's own design (e.g., a `for:` duration delays firing [S-005]); MTTD must be reported with the detector configuration.

## Limitations

- Injected faults start abruptly and are clean; real incidents have fuzzy onset, so MTTD in the sandbox is optimistic.
- Small N: with ~10 scenarios × few runs, report ranges, not point claims.

## Open Questions

- Source-backed definitions of MTTD/MTTR/MTBF to adopt or contrast.
- Stability window length (OQ-06).

## References

- [S-001] https://sre.google/sre-book/service-level-objectives/
- [S-005] https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
