# Failure Modes (FMEA) and Degraded-Mode Design

**Status:** Draft analysis (hypotheses; not validated by experiments). Severity: H/M/L by potential harm to the sandbox or the integrity of results.

## FMEA

| ID | Failure | Cause | Impact | Sev | Detection | Mitigation | Recovery |
|---|---|---|---|---|---|---|---|
| FM-01 | False positive incident | Over-sensitive rule, noise, low traffic [S-003] | Unneeded investigation or action | M | Control runs, precision metric | Hysteresis, multiwindow rules, synthetic traffic | Close incident, tune rule |
| FM-02 | False negative | Signal not covered (e.g., worker backlog), long windows | Missed outage | H | Recall in experiments, black-box probes [S-002] | Symptom coverage per service, synthetic probes | Add rule, postmortem |
| FM-03 | Wrong RCA | Spurious correlation [S-015], decoy event | Wrong action | H | EXP-09, verification failure | Contradicting-evidence field, confidence limits, alternatives | Escalate; update rules |
| FM-04 | Wrong remediation | Wrong cause, wrong action choice | No recovery or harm | H | Verification, regression check | Catalogue restricted by cause type; approval for medium | Rollback/escalate |
| FM-05 | Failed remediation | Fault persists | Continued outage | M | Verification | Bounded attempts | Escalate |
| FM-06 | Repeated remediation (loop) | No budget/cooldown | Self-inflicted outage | H | Action counter | Loop guards, circuit breaker [S-039] | Breaker open, human reset |
| FM-07 | Partial recovery | Some SLIs OK, others degraded | False "recovered" | M | Multi-criteria verification | AND of all criteria, stability window | Continue incident |
| FM-08 | Telemetry failure | Scrape/log pipeline down | Blind or misled | H | `absent()` checks [S-044], freshness | `UNKNOWN` state, no action from missing data | Alert, restore pipeline |
| FM-09 | LLM unavailable | Provider/network | No AI explanation | L | Health check on adapter | Deterministic report | Retry later |
| FM-10 | LLM hallucination | Model error, poor context [S-026] | Misleading explanation | M | Evidence-ID validator | Reject uncited claims; show raw evidence | Regenerate/deterministic fallback |
| FM-11 | Prompt injection | Malicious log content [S-036, S-038] | Misleading output, attempted action | H | Injection test corpus; policy denials | Untrusted-data handling; no AI→executor path | Quarantine evidence |
| FM-12 | Policy bypass | Bug, missing rule | Unauthorized action | H | Adversarial tests; audit review | Default deny, typed catalogue, tests | Disable executor |
| FM-13 | Sandbox escape / over-privileged executor | Daemon access [S-030, S-031] | Host compromise | H | Hardening review | Minimal executor, rootless daemon [S-043], no privileged containers | Rebuild host/VM |
| FM-14 | Dependency (DB) failure of Cloud Doctor | PostgreSQL down | No evidence/audit persistence | H | Health check | Fail closed: no execution without audit write | Restore DB |
| FM-15 | Verification failure | Probe wrong, window too short | False recovery or false failure | M | Cross-checks, repeated probes | Independent synthetic checks | Re-verify |

## Degraded-mode behavior (DESIGN DECISION)

Principle: **safety-critical dependency failure ⇒ remediation fails closed.**

| Down component | Behavior |
|---|---|
| Prometheus / Loki | Affected signals `UNKNOWN`; detection from remaining sources; no remediation justified only by missing data; self-alert |
| LLM | Deterministic diagnosis and templated report |
| Policy engine | All execution denied |
| Evidence store / DB | No execution (cannot audit); read-only view if possible |
| Executor / sandbox | Plan recorded, not executed |
| Alertmanager | Detector evaluates rules directly (if designed so) or incident detection degraded — to decide in ADR-002 |

## Open items

Severity ratings are judgments; likelihood and detectability scores omitted until experiments provide data.
