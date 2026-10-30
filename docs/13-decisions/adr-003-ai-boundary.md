# ADR-003: AI Boundary

## Status
Proposed.

## Context
Logs are untrusted text [S-038]; OWASP lists prompt injection and excessive agency [S-036]; tool calls are executed by the application, not the model [S-037]; LLM RCA shows promise on historical incidents [S-023, S-025] but with documented reasoning failures [S-026].

## Problem
What may the LLM see, say and do?

## Options
### Option A — LLM advisory only, schema output, no tools
### Option B — LLM advisory + read-only evidence-request tools (budgeted, allowlisted)
### Option C — LLM with execution tools gated only by prompts

## Decision
Option B. Option C rejected.

## Rationale
Read-only retrieval matches findings on dynamic evidence collection [S-024] while keeping state changes outside the AI zone. Boundaries enforced by process/network separation and typed validators, not prompt wording.

## Tradeoffs
More tool-call surface than A; more cost/latency; need tool-call auditing.

## Consequences
LLM zone has no credentials, no Docker socket, no executor path. Output validated for evidence IDs and catalogue actions. Evaluation includes poisoned-log suite.

## Reconsideration Conditions
If read-only tools bring no accuracy benefit → Option A. Never move to C.

## Update 2026-10-31
Channel delivery (hosted, cloud-hosted, local, none) is now specified in ADR-006 and `docs/05-ai/llm-channels.md`. The boundary in this ADR applies **identically to every channel**; local models get no extra privileges.

## References
S-023–S-026, S-036–S-038.
