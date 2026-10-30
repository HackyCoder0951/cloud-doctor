# Remediation Catalogue and Risk Classification

**Status:** Design. Sourcing is thin: the catalogue is derived from the experiment designs and from restart/probe semantics read in S-018/S-019. Industry runbook-automation and rollout documentation is **not yet researched** (OPEN).

## Risk classes (DESIGN DECISION)

| Class | Definition | Examples | Execution rule |
|---|---|---|---|
| Low | Reversible, scoped to one sandbox service, no data mutation, fast to verify | restart worker, restart stateless api | Auto-execute if policy allows |
| Medium | Changes version/capacity/traffic, or restarts a stateful dependency | rollback api, scale api, restart redis (state loss) | Human approval |
| High | Data mutation, infrastructure change, multi-service blast radius, anything outside catalogue | DB modification, delete volumes, network reconfiguration | Never executed; escalate |

Redis restart is classed medium if it holds queue state (EXP-01), because loss of queued jobs is possible — a design choice to review once the topology fixes whether Redis is a cache or a queue.

## Catalogue (typed actions)

| Action | Params | Class | Trigger | Preconditions | Verification | Rollback | Failure modes |
|---|---|---|---|---|---|---|---|
| `restart_service` | service | Low (stateless) / Medium (stateful) | Service unhealthy, cause local | Evidence snapshot taken; not in cooldown; dependency not the confirmed cause | Readiness, SLIs over window | None (stateless) | Fault recurs; state loss; load spike on restart |
| `rollback_service` | service, version | Medium | Change event precedes symptom, new error signatures | Previous version exists; approval | SLIs, version label, synthetic transaction | Redeploy forward | Older bug returns |
| `scale_service` | service, replicas ≤ cap | Medium | Saturation without errors | Capacity cap; Compose support (limited) | Latency/CPU back within target | Scale back | Masks leak; shifts load downstream |
| `clear_cache` | cache name | Low–Medium | Corrupt/stale cache evidence | Safe-to-clear flag | Hit rate recovers, errors normal | None | Thundering herd on DB |
| `isolate_dependency` | service, edge | Medium | Dependency failing and callers blocked | Circuit breaker support in app | Callers degrade gracefully | Re-enable edge | Hidden failures |
| `escalate` | reason | Low | No safe action, attempts exhausted | — | Human acknowledgement | — | — |

Considered and **not planned** for the sandbox prototype: failover, instance replacement, traffic shifting, feature-flag rollback (need infrastructure the simulation does not model). Retry and circuit breaking are application-level patterns [S-039], not Cloud Doctor actions.

## Selection rules (DESIGN DECISION)

1. Prefer the least invasive action that addresses the *cause*; mitigating symptoms is acceptable per Google guidance to "stop the bleeding" first [S-015], but must be labelled mitigation.
2. Do not restart a service whose failure is caused by a down dependency unless the plan also addresses the dependency, since the liveness-cascade caution [S-018] shows restarts can add load.
3. "No action" and "escalate" are valid outputs.

## Open questions

Which actions Compose can actually support (scale, rollback); rollout semantics if Kind is chosen; sources for failover and traffic-shifting if scope expands.

## References

S-015, S-018, S-019, S-039.
