# ADR-004: Sandbox Environment

## Status
Proposed — **partially updated 2026-10-31**: kind, RBAC, NetworkPolicy and Docker rootless pages now read (S-040–S-043); Minikube and local-VM options remain unresearched (OQ-01).

## New findings since first draft (RESEARCH FINDING)

- kind runs Kubernetes "nodes" as Docker containers; "primarily designed for testing Kubernetes itself, but may be used for local development or CI"; requires docker, podman or nerdctl [S-040]. The pages do not say whether kind is unsuitable for production, nor give general resource needs.
- RBAC permissions are purely additive (no deny rules); least privilege and application-specific service accounts are recommended [S-041; read via summary — verify].
- Pods are non-isolated by default; NetworkPolicy has no effect without a CNI that enforces it [S-042; summary]. **Whether kind's default CNI enforces NetworkPolicy is not confirmed.**
- Docker rootless mode runs the daemon and containers inside a user namespace as a non-root user and avoids setuid binaries other than `newuidmap`/`newgidmap` [S-043]. The page has no limitations section (linked troubleshooting page unread).

### Further findings (S-056–S-059, pages read)

- kind ships a simple default CNI (kindnetd); `disableDefaultCNI: true` allows installing another (e.g., Calico is mentioned). **Neither kind page states whether kindnetd enforces NetworkPolicy.** Combined with S-042 (policies have no effect without an enforcing CNI), NetworkPolicy isolation in kind must be tested or a different CNI installed.
- kind known issues: inotify limits (Ubuntu defaults 8192 watches / 128 instances noted as insufficient for many nodes), cgroup-namespace requirement on older kernels, disk and memory needs [S-056].
- Rootless Docker: supported storage drivers limited (overlay2 needs kernel ≥ 5.11, fuse-overlayfs, btrfs, vfs); cgroup resource limits work **only with cgroup v2 and systemd**, and typically only `memory` and `pids` controllers are delegated by default — `--cpus` limits are ignored unless `cpu` delegation is configured; AppArmor, overlay networks and SCTP port exposure not supported; privileged ports (<1024) need configuration; user-mode networking is slower [S-058, S-059].
- **Consequence for experiments:** EXP-03 (CPU limit) and EXP-04 (memory limit) depend on Docker resource constraints [S-029]; under rootless Docker, CPU limits require explicit cgroup delegation. This is a concrete design constraint for the rootless option, not an obstacle to the VM option.

### NetworkPolicy enforcement findings (user-supplied sources: S-079–S-082)

- The official minikube handbook states: a vanilla `minikube start` "does not support any NetworkPolicies, since the default CNI, Kindnet, does not support Network Policies, by design"; adding `--cni calico` enables enforcement [S-079, Tier 1, verbatim].
- kind's configuration page says kind ships "kindnetd" as its default CNI [S-057]. Combining S-079 and S-057 gives the **inference** that kind's default also does not enforce NetworkPolicy; a consultancy blog states "Policies are accepted but never enforced" for kindnet [S-081, Tier 3]. **No kind-specific document that I could read states this outright**, and the kind-specific Medium article and Stack Overflow question could not be fetched. The `disableDefaultCNI` + Calico/Cilium workaround is documented only as "install a different CNI" in S-057; step-by-step instructions are unconfirmed.
- Default-deny patterns agree across sources: a policy selecting all pods with no rules denies; deny-all egress also blocks DNS, so a DNS allow rule is needed; policies are additive (no explicit deny rules in core NetworkPolicy); in `from:` clauses a leading dash creates an OR rather than an AND; ingress-only policies leave egress open [S-079, S-080, S-081]. Sources disagree on namespace labelling (automatic `kubernetes.io/metadata.name` label vs. manual `name=<ns>`) — verify against Kubernetes docs before use.
- KEP-6313 (network-isolated Pod sandboxes, alpha, target v1.38) concerns pods with no pod network and says NetworkPolicy does not apply to them; it is **not** relevant to enforcement in kind/minikube [S-082].

**Implication:** a kind or minikube sandbox cannot be assumed network-isolated by NetworkPolicy unless a policy-enforcing CNI is installed and tested. For the Docker Compose option, `internal: true` networks [S-033] are the isolation mechanism instead. This lowers Kind's advantage over Compose for *network* isolation and leaves RBAC/probes/rollouts as its remaining advantages.

**Interpretation:** rootless Docker reduces the host impact of a compromised executor (TM-04) and is a credible default for the Compose option; Kind gives RBAC and probes but NetworkPolicy enforcement needs verification. Neither is shown to be sufficient on its own.

## Context
Recovery must occur only in isolated infrastructure. Docker daemon control is powerful [S-030, S-031]; Compose offers network isolation [S-033]; Docker limits support CPU/memory faults [S-029]; Toxiproxy supports network faults [S-028].

## Problem
Which environment makes production action structurally impossible while allowing realistic recovery?

## Options
### Option A — Docker Compose on dedicated project networks
Simple; no probes/rollouts/RBAC; executor needs Docker access.
### Option B — Kind (Kubernetes in Docker)
Realistic probes, rollouts, namespaces, RBAC; heavier. Not yet researched.
### Option C — Local VM running either
Stronger boundary around the daemon. Not yet researched.

## Update 3 — MicroVM option (user direction, 2026-10-31; sources S-092–S-096)

The user proposed MicroVM-based sandboxes with a private Docker daemon (Docker Sandboxes, Freestyle VMs) as the most robust option, running Compose natively without host socket mounting or privileged mode. Checked against what could be read:

**Documented by Docker (vendor docs/blog, model-extracted reads):**
- Each sandbox is a dedicated microVM with its own Docker Engine, a separate kernel, and "no path to the host daemon"; Docker's comparison table rates it "Full (hypervisor)" isolation versus "Partial (namespaces)" for a socket-mounted container and "Partial (privileged)" for Docker-in-Docker [S-093]. The blog states agents can build and run containers with "no socket mounting, no host-level privileges" [S-092, marketing]. An explicit statement that the sandbox never uses a privileged mode was **not found**.
- Requirements: macOS 14+ on Apple silicon; Windows 11 with Windows Hypervisor Platform; Ubuntu 24.04+ with KVM and the user in the `kvm` group (nested virtualization needed inside a VM); `sbx login` (Docker OAuth) is required; Docker Desktop is not required; the CLI and local compute are stated to be free, organisation governance and the API need paid subscriptions; cloud compute is pay-as-you-go [S-093, S-094].
- Network: all outbound TCP passes a host-side proxy; deny-by-default policy with presets (default allowlists "include broad wildcards"); UDP and ICMP blocked unless an experimental feature is enabled; sandboxes cannot talk to each other directly [S-093].
- Credentials are injected by the host-side proxy and "never enter the VM" [S-093].
- File sharing: the workspace is a **read-write virtiofs passthrough** of a host directory by default (same absolute path); `--clone` mode mounts the repo read-only and works in a private clone; mountless sandboxes exist from sbx 0.42.0 [S-093]. Docs warn that an agent in direct mode can edit Git hooks, CI config and build scripts that later run on the host.
- Programmatic use: local sandboxes are driven by the `sbx` CLI (a service can shell out); JSON output and exit codes were not verified; cloud sandboxes have a REST API and TypeScript SDK needing a subscription [S-093, S-094].
- Not found: general known-issues list, cold-start numbers, hypervisor naming in the pages read beyond the blog's claim of a custom VMM, a GA/beta label (some sub-features are labelled experimental).

**Documented by Freestyle (vendor docs; marketing for scale claims):**
- "Freestyle sandboxes are microVMs with a full Linux kernel, so the Docker Engine runs inside one natively"; Docker, `compose` and `buildx` are preinstalled in base snapshots; overlayfs, cgroup v2 and bridge networking work [S-095]. Snapshots capture memory and disk including the running daemon.
- **Not found:** the hypervisor technology, any statement about host Docker sockets, privileged mode or rootless operation, any self-hosting option (it appears to be a hosted service, so data runs on the vendor's infrastructure), prices, and a stability label. "Full KVM support" appears only in marketing [S-096]. The SDK is an npm package (`freestyle`) [S-095].

**Assessment of the user's claim:** supported for Docker Sandboxes by the vendor's own documentation (private daemon in a microVM, no host socket, hypervisor-level isolation); for Freestyle the microVM and in-VM Docker are documented but the "no socket / no privileged" part is an inference, not a stated fact. "Most robust" is a vendor/practitioner judgment that I have **not independently verified**; no isolation testing was done.

**Effect on the design:**
1. **TM-04 improves:** the executor no longer needs the *host* Docker daemon; its reach is the microVM's private daemon. It still needs a control channel into the VM (the `sbx` CLI or a vendor API). That channel is the new privileged path and must be restricted to the fixed action catalogue.
2. **Workspace exposure:** use clone or mountless modes, never a read-write mount of a directory that holds the Cloud Doctor repo, secrets or policy files.
3. **Observation path is unresolved:** Cloud Doctor on the host must read Prometheus/Loki and send probes to services inside the VM; the documents read describe outbound policy from the VM and do not say how a host-side client reaches services inside it. Needs a spike.
4. **Dependencies and reproducibility:** `sbx login` and proprietary tooling become dependencies; keep the Compose files portable so the same stack runs on plain Docker in a dedicated VM (the fallback).
5. **Hosted variants (Docker cloud sandboxes, Freestyle) send workload and telemetry to a third party**: acceptable for the synthetic prototype, but a client with data-sovereignty needs would need the local variant.
6. **CPU/memory-limit experiments (EXP-03/04):** the rootless limitation (CPU limits need delegation) does not directly apply to a rootful in-VM daemon, but limit behavior inside Docker Sandboxes is **unverified**; Freestyle documents cgroup v2 support.

**Spikes required before acceptance:** (S1) drive `sbx` non-interactively from a script; (S2) host-side access to in-VM Prometheus and a gateway endpoint; (S3) run Compose + Toxiproxy + a CPU/memory hog with limits inside, **and bring up the observability-infra stack in the microVM — checking `network_mode: host` behaviour, whether `/dev/kmsg` exists for cAdvisor, and the Docker data-root path for Promtail** (risks noted in that project's own troubleshooting docs); (S4) measure startup time and resource overhead; (S5) confirm no host mounts beyond the clone; (S6) confirm network policy blocks unintended egress; (S7) check CI feasibility (login, KVM).

## Decision
**Option D — MicroVM sandbox (proposed):** primary target is a MicroVM with a private Docker daemon — Docker Sandboxes locally (Linux/macOS/Windows) — with Freestyle VMs as a hosted alternative; fallback is the same Compose stack in a plain dedicated VM with rootless or rootful Docker. The decision is **provisional until spikes S1–S7 pass**. Options B (Kind) and Minikube are not pursued for the prototype: their NetworkPolicy behavior is unconfirmed and a Kubernetes-specific advantage is not needed.

## Rationale
Lowest complexity for a single developer; meets challenge; isolation of the executor handled by design (fixed catalogue, no socket exposure to AI).

## Tradeoffs
Weaker realism for "rollback deployment"; weaker least-privilege than Kubernetes RBAC.

## Consequences
Health checks defined in Compose; recovery verification built on Cloud Doctor's own probes rather than kubelet.

## Reconsideration Conditions
If bad-deployment/rollback realism or RBAC demonstration is required → Kind.

## References
S-028–S-033.
