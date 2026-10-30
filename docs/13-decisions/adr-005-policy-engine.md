# ADR-005: Policy Engine — Hybrid (Invariant Guard + Client Policy)

## Status
Proposed. Direction chosen by the user on 2026-10-31 ("make policy engine hybrid suitable architecture"); details in `docs/06-self-healing/policy-engine.md`. Supersedes the earlier "in-process first" proposal.

## Context
OPA decouples decisions from enforcement and returns structured output [S-034, S-052]. An undefined OPA decision returns HTTP 200 without a `result` key [S-098]; bundle activation failures keep the previous bundle and unsigned bundles still activate unless a `signing` block is set [S-099]; decision logs are best-effort [S-053]. OWASP flags excessive agency [S-036]. Clients need editable rules, but some safety properties must never be editable.

## Problem
How can clients customise policy without being able to weaken core safety, while keeping fail-closed behavior if the policy service fails?

## Options
### Option A — in-process validator only
Few failure modes; no client-editable rules.
### Option B — OPA only
Editable policy; the safety floor then depends on bundle correctness and service availability.
### Option C — OPA embedded as Wasm in Python
In-process; Python SDKs are community-maintained and one looked stale; Wasm lacks some built-ins [S-097, S-100].
### Option D — hybrid: Layer 1 invariant guard (code) + Layer 2 client policy (OPA REST sidecar)
Layer 1 is non-overridable; Layer 2 may only tighten; any Layer 2 problem denies.

## Decision
Option D. Prototype runs OPA as a localhost REST sidecar with signed, persisted bundles; Layer-1-only mode is the default for clients without custom rules.

## Rationale
- Separates *what must never change* (safety invariants, owned by engineering) from *what clients tune* (Rego, owned by clients).
- Conjunction composition guarantees Layer 2 cannot loosen Layer 1.
- Avoids dependence on unverified Python Wasm SDKs.
- Mirrors the hybrid pattern used for LLM channels: one interface, replaceable parts, same safety floor.

## Tradeoffs
Two layers to test and document; an extra service (OPA) in the Layer-2 path; Rego skills needed by clients; fail-closed behavior must be implemented in our caller.

## Consequences
- Decision records carry both layers' results, bundle revision and signature status, and invariants version.
- Approvals bind to plan hash; re-check at execution time.
- Audit log (not OPA decision logs) is authoritative.
- Evaluation adds policy-bypass and failure-injection suites.
- Verification work: OPA health/bundle endpoint semantics, Rego test tooling, signing workflow.

## Reconsideration Conditions
Drop Layer 2 for the prototype if no client rule is needed (Layer-1-only remains valid); move to in-process Wasm if a maintained Python SDK is verified; consider Kubernetes admission control only if the sandbox moves to Kubernetes.

## References
S-034, S-036, S-052, S-053, S-097–S-100.
