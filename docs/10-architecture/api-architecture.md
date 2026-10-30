# API Architecture

**Status:** Design (nothing implemented). Endpoints derive from requirements FR-001…FR-018, not from the prompt's example list.

## Contract-first

The API contract (OpenAPI plus JSON Schema for evidence, diagnosis and report payloads) is authored independently of the implementation language, so the Python backend and the Next.js/TypeScript dashboard (ADR-007) are decoupled: a typed client is generated from the contract and contract tests run in CI. The user's Linux-RCA planning docs take the same position ("API contracts must be language-neutral").

## Principles

1. Reads are cheap and side-effect-free; **execution is separated** from diagnosis and planning.
2. No endpoint accepts free-form commands. Remediation requests carry catalogue `action_id` plus typed params.
3. Every mutating call is authenticated, authorised by role, idempotent via `Idempotency-Key`, and audited.
4. The LLM adapter has **no public API**; it is an internal component.
5. Fault injection lives on a separate service/port with its own credentials; it is not part of this API.

## Roles

`viewer` (read), `operator` (approve medium-risk), `admin` (config, policy read-only view). No role can approve high-risk actions (they cannot be executed).

## Endpoints

| Method & path | Purpose | Auth | Notes |
|---|---|---|---|
| `GET /services` | Services with current health state | viewer | Includes `UNKNOWN` |
| `GET /services/{id}/health` | SLIs, saturation, dependency states, freshness | viewer | |
| `GET /incidents?state=` | List incidents | viewer | Paginated |
| `GET /incidents/{id}` | Incident summary and state | viewer | |
| `GET /incidents/{id}/timeline` | Ordered events (event time, collection time) | viewer | |
| `GET /incidents/{id}/evidence` | Evidence records (`untrusted` flag on log payloads) | viewer | Payloads escaped for UI |
| `GET /incidents/{id}/diagnosis` | Hypotheses with supporting/contradicting evidence, unknowns | viewer | `origin` rule/llm |
| `POST /incidents/{id}/diagnose` | Re-run diagnosis (deterministic, optional LLM) | operator | Idempotent; budgeted |
| `GET /incidents/{id}/remediation` | Plans, policy decisions, status | viewer | |
| `POST /incidents/{id}/remediation/plans/{plan}/approve` | Approve a medium-risk plan | operator | Body: reason; one-time; policy re-evaluated at execution time |
| `POST /incidents/{id}/remediation/plans/{plan}/reject` | Reject | operator | |
| `GET /incidents/{id}/verification` | Pre/post comparison, verdict, window | viewer | |
| `GET /incidents/{id}/report` | Machine-readable (JSON) and rendered report | viewer | `Accept` header |
| `GET /audit?incident=` | Audit entries | admin | Append-only |
| `GET /healthz`, `GET /status` | Self-health, dependency status | none/viewer | Reports degraded mode |

Planning and execution are system-initiated (policy → executor), not directly callable; a human can only approve or reject an existing plan. This is a deliberate reduction relative to the prompt's example `POST .../remediation/execute`.

## Example: approval request/response

```http
POST /incidents/INC-0007/remediation/plans/PL-0002/approve
Idempotency-Key: 6f1c...
Content-Type: application/json

{ "reason": "Rollback matches change event EV-004" }
```

```json
{
  "plan_id": "PL-0002",
  "status": "approved",
  "policy_decision": {"decision": "allow_with_approval", "rule_ids": ["R-RISK-MED", "R-TARGET-SANDBOX"], "policy_hash": "…"},
  "execution": {"state": "queued"}
}
```

## Validation and errors

- Strict schemas; unknown fields rejected; IDs matched by pattern; `422` on invalid input.
- `403` policy denial returns rule IDs, never internals; `409` if state changed or plan already executed; `429` for rate limits; `503` with `degraded` detail when a safety dependency is down (fail closed).
- Idempotency: the same key returns the original result and never re-executes.

## Authentication and authorisation (OPEN)

Mechanism not selected (token with roles for the prototype is the minimum). Threat TM-09 requires per-action authorisation checks and audit of the approver.

## Open questions

Report schema versioning; pagination limits; whether evidence endpoints should paginate payloads to avoid huge log content.
