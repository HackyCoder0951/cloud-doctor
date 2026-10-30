# Chaos Engineering Fundamentals and Failure Injection

## Abstract

Principles from the chaos-engineering canon and the capabilities of two injection mechanisms available for a Docker-based sandbox: Toxiproxy (network) and Docker resource limits (CPU/memory).

## Research Findings (RESEARCH FINDING)

### Principles [S-027, page last updated March 2019]

- Definition: experimenting on a system to build confidence in its ability to withstand turbulent conditions.
- Experiment steps: define a measurable steady state; hypothesize it continues in control and experimental groups; introduce real-world-event variables (crashed servers, severed connections…); try to disprove the hypothesis.
- Advanced principles: hypothesis on measurable output (throughput, error rate, latency percentiles); vary real-world events; run in production (preferred by the source); automate; **minimize blast radius**.
- **Interpretation:** Cloud Doctor deliberately departs from "run in production": it runs only in a sandbox (challenge constraint). Results will therefore show tool behavior, not production confidence.

### Toxiproxy [S-028]

- Framework for simulating network conditions for testing/CI/development; a TCP proxy plus an HTTP-controlled client API.
- Toxics: latency (+jitter), bandwidth, slow_close, timeout, reset_peer, slicer, limit_data, packet_loss. "Down" is not a toxic but disabling the proxy.
- The application must connect through the proxy's listen port.
- **Security:** the API is unauthenticated by default and can create proxies to arbitrary upstreams; never expose it to an untrusted network (a bearer token can be enabled). Implication: the fault-injection control plane must sit in a trust zone unreachable by Cloud Doctor's AI/executor.
- Proxy changes (listen/upstream) restart the proxy and drop connections.

### Docker resource constraints [S-029]

- By default, a container has no resource constraints.
- `--memory` sets a hard limit (minimum 6m); `--cpus` is shorthand for CFS period/quota; `--memory-swap` controls swap.
- On OOM the kernel kills processes; Docker adjusts the daemon's OOM priority, not the container's. Disabling the OOM killer without a memory limit risks host memory exhaustion.
- **Not on the page (unverified):** the container's exit code/state after an OOM kill.

## Failure-model mapping (HYPOTHESIS)

| Experiment | Injection mechanism | Source |
|---|---|---|
| EXP-01 Redis outage | stop container, or disable Toxiproxy proxy | S-028 |
| EXP-02 Worker crash | kill container process | generic Docker |
| EXP-03 CPU saturation | load generator inside container under `--cpus` limit | S-029; stress tool not yet researched |
| EXP-04 Memory exhaustion | memory-hungry process under `--memory` limit → OOM kill | S-029 |
| EXP-05 DB connection exhaustion | connection-hogging client against a low `max_connections` | not yet researched |
| EXP-06 Network latency | Toxiproxy `latency` toxic | S-028 |
| EXP-07 Bad deployment | start a deliberately faulty image version | design |
| EXP-08 Dependency outage | stop/disable downstream | S-028 |
| EXP-09 False correlation | concurrent unrelated events | design |
| EXP-10 Failed remediation | fault persists after restart | design |

**DESIGN DECISION (provisional):** Chaos Mesh and LitmusChaos presuppose Kubernetes and are not needed under a Compose sandbox (neither has been read yet; this is a hypothesis).

## Experiment design requirements (DESIGN DECISION)

Each experiment declares: steady-state metrics and thresholds, injected fault, ground-truth cause, blast radius (services affected, duration cap), abort condition, and control run without fault. The harness records injection timestamps as ground truth for MTTD/MTTR.

## Limitations

- Injected faults are cleaner than natural ones.
- Principles page is dated 2019 and only high-level.
- The injection harness is itself a privileged component (see threat model).

## References

S-027, S-028, S-029 in `docs/_sources/register.md`.
