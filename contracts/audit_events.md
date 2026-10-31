# Audit event names and approval semantics

Added after contract freeze v1 as an **additive, descriptive** contract (change request harness-3). It records what the backend (`backend/`) writes today; `contracts/schemas/audit_event.json` is unchanged (`event` is a string, `detail` a free object). Consumers (the harness safety metrics) may rely on the names and keys below; a change here needs a change request.

## Approval semantics
1. A medium-risk plan first gets a decision with `final: allow_with_approval` and the plan state `AwaitingApproval`.
2. `POST /incidents/{incident}/remediation/{plan}/approve` (operator role) must carry the plan's current `plan_hash`; a mismatch or a plan not awaiting approval is `409`.
3. The backend then **re-evaluates policy with the approval attached** and records a **new decision** for the same `plan_id` and `plan_hash` with `final: allow` (the earlier decision is kept). If the result is not `allow`, nothing is recorded as approved and the call is refused.
4. The approval is bound to the plan hash and is part of the signed envelope sent to the actuator, which re-checks it.
5. Reject (`.../reject`) records the rejection and escalates; no allow decision is created.
So "an executed plan has an `allow` decision" holds for every plan: low risk gets `allow` directly, medium risk gets `allow` only after approval.

## Event names (`event`) and `detail` keys
| actor | event | detail keys |
|---|---|---|
| `detector` | `incident.opened` | `services`, `rule` |
| `<actor>` | `incident.state_changed` | `from`, `to`, `reason` |
| `rca` | `evidence.collected` | `phase`, `count` (and others) |
| `rca` | `diagnosis.created` | `top`, `confidence`, `status` |
| `planner` | `plan.created` | `plan_id`, `action`, `risk` |
| `planner` | `plan.state` | `plan_id`, `state` |
| `planner` | `evidence.pre_action_snapshot` | `evidence_ids` |
| `policy` | `decision.recorded` | `plan_id`, `final`, `rules` |
| `operator:<name>` | `plan.approved` | `plan_id`, `plan_hash` |
| `operator:<name>` | `plan.rejected` | `plan_id` |
| `operator:<name>` | `circuit.reset` | (empty) |
| `actuator` | `execution.finished` | `execution_id`, `result` |
| `verifier` | `verification.finished` | `verdict`, `checks` (name -> passed) |
| `planner` | `remediation.escalated` | `plan_id`, `reason` |
| `planner` | `circuit.opened` | `failures`, `attempts` |
| `api` | `login.ok`, `login.failed`, `diagnose.requested` | (empty) |

There is **no** `execution.started` event today: an execution is recorded when it finishes. The actuator keeps its own hash-chained log (`actuator` package) with its own event names; this table is the backend's chain only.

## Checking "no execution without an allow decision" from audit data
For every `execution.finished` with a `result` of success or failure, the same incident must contain a `decision.recorded` event with `final: allow` for the same `plan_id` earlier in the chain. The harness may use this instead of reading `GET .../remediation`.
