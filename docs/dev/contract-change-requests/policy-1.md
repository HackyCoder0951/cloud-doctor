# policy-1: validate_response.rule_ids cannot name actuator envelope failures

**Stream:** C (policy and actuator). **Status:** proposal; the workaround below is implemented.

## What is wrong
`contracts/schemas/actuator.json#/$defs/validate_response` requires `rule_ids` items to match `^I-[0-9]{2}$`.
The actuator also rejects plans for reasons that are not Layer 1 invariants: bad signature, unknown `key_id`,
expired or not-yet-valid envelope, nonce replay, `plan_hash` mismatch, approval bound to another plan, malformed
envelope, non-executable action. These have no `I-xx` id.

## Proposed change
Relax the item pattern to `^(I-[0-9]{2}|A-[A-Z-]+)$` (the actuator uses A-ENVELOPE, A-KEY, A-SIGNATURE, A-EXPIRED,
A-NOT-YET-VALID, A-LIFETIME, A-HASH, A-REPLAY, A-APPROVAL, A-UNSUPPORTED, A-IDEMPOTENCY, A-AUDIT, A-DEGRADED).
`execution.refusal_rule_ids` already accepts arbitrary strings.

## Impact
Backend (Stream B) would see `A-*` ids in `/v1/validate` responses. No other stream is affected.

## Workaround used
`/v1/validate` maps every `A-*` failure to `I-08` (fail closed) and puts the precise `A-*` id in `reasons`.
`/v1/execute` returns the precise ids in `execution.refusal_rule_ids`.
