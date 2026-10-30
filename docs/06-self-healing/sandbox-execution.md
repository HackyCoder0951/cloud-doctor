# Sandbox Execution

## Abstract

Where remediation runs, and what the Docker documentation actually supports claiming about isolation. Key finding: **Docker-daemon access is a powerful capability**, so the executor design matters more than the choice of Compose versus Kubernetes.

## Research Findings (RESEARCH FINDING)

### Docker daemon [S-030, S-031]

- The daemon requires root unless rootless mode is used; "only trusted users should be allowed to control your Docker daemon" (verbatim).
- A container can be started with the host `/` bind-mounted and then alter the host filesystem without restriction (S-030, verbatim in substance).
- Daemon API keys give "root access to the machine hosting the daemon" (S-031, verbatim warning on TLS-protected access).
- The API uses a Unix socket governed by Unix permissions; exposing it over HTTP without TLS is not permitted.
- **Tier 1 gap remains:** the Docker pages read (S-030, S-031, S-032) do not explicitly state that mounting `/var/run/docker.sock` into a container, or `docker` group membership, is root-equivalent.
- **Tier 3 sources now agree (user-supplied):** a monitoring vendor guide says a container with the socket has a "root-equivalent" boundary and that docker-group membership is equivalent to passwordless root [S-075, ~68% read verbatim, remainder summarized]; a personal blog describes the mechanism in prose (the daemon runs as root and listens on the socket; a user able to talk to it can start a container with the host filesystem mounted) and says docker group membership "is equivalent to having passwordless root" [S-076]. Neither is authoritative; **the claim is now supported at Tier 3 and consistent with the Tier 1 statements that the daemon needs root and can bind-mount the host `/` [S-030]**. I would still cite it as "widely reported; vendor and practitioner sources", not as Docker's own statement.
- **Mitigation findings:** a read-only socket mount is described as only a marginal improvement because API calls remain possible [S-075 claim; not independently verified]. A community thread shows a `socat` relay exposing the socket over TCP, but the relay itself runs as root with the socket mounted, so it concentrates rather than removes the privilege [S-078]. Rootless mode is described as limiting the worst case to the user's own access [S-076; consistent with S-043].
- **Rootless practicalities** (S-076, personal experience on one machine; S-058, S-059 official): needs `loginctl enable-linger` for the daemon to survive logout, a user-level `DOCKER_HOST`, and has cleanup quirks for images owned by subordinate UIDs. Official limits (cgroup v2 + systemd for resource limits, privileged ports, no AppArmor) are in ADR-004.
- **Unreadable sources:** two Medium posts and a troubleshooting post returned HTTP 403, so nothing is drawn from them.

### Container isolation [S-030, S-032]

- Namespaces isolate processes and give each container its own network stack; cgroups limit resources but "do not play a role" in preventing cross-container access.
- Default: restricted capability set (allowlist). `--privileged` grants all capabilities and all devices. Default-kept capabilities include NET_RAW.
- User namespaces are available but not enabled by default.
- Not found: `--read-only` and `no-new-privileges` in the pages read; seccomp default profile contents not read.

### Compose networks [S-033]

- Default network uses the bridge driver. `internal: true` creates a network without gateway to external connectivity. A service attached to both an internal and a non-internal network can still reach the outside via the latter. Services that share no network cannot talk. `network_mode: host` exposes all host ports and traffic.
- Not confirmed: behavior of published ports and host reachability on internal networks.

## Environment comparison (initial; Kubernetes/Kind not yet researched)

| Option | Isolation | Realism | Complexity | Notes |
|---|---|---|---|---|
| Docker Compose on dev host | Container-level; host shares kernel and daemon | Moderate (no rollouts/RBAC/probes) | Low | Executor needs daemon access → dangerous if over-privileged |
| Kind/Minikube | Cluster in containers/VM; RBAC and namespaces available | Higher (probes, rollouts, NetworkPolicy) | Medium–high | Docs not yet read |
| Local VM | Stronger isolation boundary | Moderate | Medium | Not yet researched |
| Separate cloud account | Strong blast-radius boundary | High | High, cost | Out of scope for a lab |

## MicroVM sandbox (user direction; see ADR-004 Update 3)

Environment comparison addition:

| Option | Isolation | Docker daemon | Realism | Complexity | Notes |
|---|---|---|---|---|---|
| **MicroVM with private daemon** (Docker Sandboxes local; Freestyle hosted) | Hypervisor, separate kernel [S-093, S-095] | Private, inside the VM; no host socket path [S-093] | Moderate (no K8s features) | Medium; vendor tool and login dependency | Docker documents this model; Freestyle's isolation specifics undocumented in pages read; **spikes S1–S7 pending** |

Key points: the host Docker daemon is no longer in the executor's reach, which lowers the TM-04 risk; the executor's remaining privilege is the control channel into the VM; the default read-write workspace mount and broad default network allowlist need tightening (clone/mountless mode, deny-by-default policy) [S-093]; the hosted variants move workload and telemetry to a third party.

## Design implications (DESIGN DECISION, provisional)

1. **Never give an AI or LLM-facing process the Docker socket.** Only a small, separate executor implements a fixed action catalogue (restart service X, scale Y within bounds) against a named allowlist of sandbox containers.
2. The executor has no free-form command interface; inputs are typed (action ID + service ID) and validated against policy before use.
3. The sandbox stack lives in its own Compose project and networks; Cloud Doctor's control plane is reachable from the sandbox only via explicit endpoints; the injection control plane is separate from both.
4. Prefer a rootless or dedicated-VM Docker daemon for the sandbox if feasible (**OPEN QUESTION**; rootless mode page not read).
5. A hard guard: the executor refuses any target not labelled as sandbox. A label is a convenience, not a security boundary, so combine with daemon scoping.

## Risks

- Executor compromise → host compromise via daemon.
- Containers are not VMs; kernel-level escapes are outside this document's scope.
- The Docker security page contains old references; some statements may be dated.

## Open Questions

- Kind vs. Compose decision (OQ-01, ADR-004) needs Kubernetes RBAC/NetworkPolicy sources.
- Docker socket proxy / rootless mode sources.

## References

S-029–S-033 in `docs/_sources/register.md`.
