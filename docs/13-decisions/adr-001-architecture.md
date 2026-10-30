# ADR-001: Overall Architecture

## Status
Proposed (not accepted until Gate G1: RQ-01…RQ-18 each have a sourced finding or recorded gap; remaining gaps listed under Reconsideration).

## Context
Challenge 08 requires detection, evidence-backed RCA, recommended recovery, and sandboxed recovery with verification. Requirements: `docs/10-architecture/requirements.md`. Evidence: S-021 (causal RCA does not generalise reliably), S-026 (LLM reasoning failures), S-036 (excessive agency / improper output handling).

## Problem
How much of the pipeline should depend on an LLM, and where does autonomy end?

## Options
### Option A — deterministic only
Pros: simplest, most testable, safest. Cons: limited novelty handling; weaker "AI" contribution; high circular-evaluation risk.
### Option B — rule detection + AI-assisted RCA
Pros: better hypotheses. Cons: no RCA when LLM is down; injection exposure.
### Option C — agent-based investigation
Pros: flexible. Cons: largest attack surface, cost, nondeterminism, documented reasoning failures.
### Option D — hybrid
Deterministic core always completes; optional AI layer explains and recommends within evidence and policy limits.

## Decision
Option D.

## Rationale
Satisfies FR-006 (works without LLM), makes AI contribution measurable (LLM-on vs. off), bounds agency technically. See `architecture-options.md`.

## Tradeoffs
More components than A; two RCA paths to maintain; AI value unproven (H-AI-1).

## Consequences
Evidence store and validator are mandatory; evaluation must include a no-LLM baseline; executor and policy are independent of the AI.

## Reconsideration Conditions
Drop to A if LLM adds no measured benefit; revisit C only if bounded read-only tools prove insufficient and security tests pass.

## References
S-021, S-026, S-036.
