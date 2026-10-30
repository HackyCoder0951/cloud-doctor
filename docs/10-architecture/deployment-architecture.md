# Deployment Architecture

**Status:** Design, provisional on ADR-004. Nothing deployed.

## Environments

| Environment | Purpose |
|---|---|
| Developer workstation / dedicated VM | Runs the sandbox stack and Cloud Doctor |
| CI (GitHub) | Lint, unit tests, policy tests, schema tests, container builds; may run a reduced scenario smoke test |

No production or cloud environment is used.

## Delivery pipeline

```mermaid
flowchart LR
    DEV[Developer] --> GH[GitHub repo]
    GH --> CI[CI: lint, unit, policy and injection-corpus tests]
    CI --> IMG[Container images - pinned digests]
    IMG --> SBX[Sandbox stack]
    SBX --> RUN[Experiment runs]
    RUN --> RES[Results + run metadata]
```

## Runtime layout (provisional, Option A sandbox)

```mermaid
flowchart TB
    subgraph NETC[net: control - internal]
      API[Cloud Doctor API] --- DB[(PostgreSQL)]
      CORE[Detector / RCA / policy]
      EXE[Executor]
    end
    subgraph NETA[net: ai - egress only to LLM provider]
      LLM[LLM adapter]
    end
    subgraph NETS[net: sandbox - internal]
      SVC[Simulated services]
      PROM[Prometheus]
      LOKI[Loki]
    end
    subgraph NETI[net: injection - separate]
      INJ[Injector / Toxiproxy]
    end
    CORE --> PROM
    CORE --> LOKI
    CORE --> LLM
    EXE --> SVC
    INJ --> SVC
```

Rules: networks are separate Compose networks; sandbox network is `internal: true` so workloads have no external egress [S-033]; the LLM adapter is the only component with outbound internet access, and has no route to the sandbox or executor; the injector API is not reachable from Cloud Doctor components; the executor reaches the container runtime through a rootless or VM-isolated daemon (open, see ADR-004) and never from the AI network.

Caveat: Compose network semantics beyond those read (published ports, host reachability on internal networks) are unconfirmed [S-033].

## Runtime layout update — MicroVM sandbox (provisional, ADR-004 Update 3)

```mermaid
flowchart TB
    subgraph HOST[Host: Cloud Doctor control plane]
      API[API] --- DB[(PostgreSQL)]
      CORE[Detector / RCA / grounding validator]
      L1[Policy Layer 1: invariant guard]
      OPA[OPA sidecar: Layer 2, signed bundles]
      GWY[LLM gateway: C0 / C1]
      EXE[Executor: fixed catalogue]
    end
    subgraph VM[MicroVM: private Docker daemon and kernel]
      SVC[Simulated services via Compose]
      PROM[Prometheus]
      LOKI[Loki]
      INJ[Injector - separate credentials]
    end
    CORE -. read telemetry / probes: path TBD, spike S2 .-> VM
    EXE -- restricted control channel: spike S1 --> VM
    L1 --> OPA --> EXE
    CORE --> GWY
```

Rules: no host Docker socket anywhere; the VM workspace uses clone or mountless mode (no read-write host mount); the VM's network policy is deny-by-default; the LLM gateway is the only component with outbound access to an LLM vendor (C1) and holds the key; the injector is not reachable from Cloud Doctor components. The Compose stack stays portable so it can run in a plain dedicated VM as the fallback. How the host reaches in-VM Prometheus/Loki and the gateway endpoint is **unresolved** and is spike S2.

## Configuration and secrets

Secrets only in environment/secret files outside the repository; none in the sandbox; LLM key accessible only to the adapter. A secrets-management document is pending.

## Reproducibility

Pinned image digests, versioned scenario configs, recorded run metadata (NFR-006). One-command bring-up and teardown targets are planned.

## Open questions

Dedicated VM vs. rootless daemon; Kind alternative; persistent volumes policy for Postgres/Prometheus in experiments (reset between runs).
