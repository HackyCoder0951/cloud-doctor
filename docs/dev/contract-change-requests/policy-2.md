# policy-2: the actuator cannot re-check I-05 and I-07, and the audit hash for events without an incident is unspecified

**Stream:** C (policy and actuator). **Status:** proposal; workarounds are implemented.

## What is wrong
1. `docs/dev/streams.md` says the actuator re-runs Layer 1. Rules I-05 (evidence ids exist, diagnosis validated) and I-07
   (top cause service is down) need control-plane state, and `signed_plan.json` (additionalProperties: false) has no
   field to carry it. The circuit-breaker state of I-04 is control-plane state too.
2. `audit_event.json` hashes `{seq, incident_id, actor, event, detail, prev_hash, created_at}` but `incident_id` is
   optional; the contract does not say whether an absent key is hashed as null or omitted.

## Proposed change
1. Add an optional, signed `attestations` object to the envelope, for example
   `{"evidence_ids": [...], "diagnosis_validated": true, "top_cause_service": "redis", "down_services": ["redis"]}`,
   so the actuator can evaluate I-05 and I-07 on signed data instead of trusting the signature alone.
2. State that an absent key is omitted from the hashed object (what the actuator does).

## Impact
Backend would fill `attestations` when signing. The DB verifier in Stream B must hash events without an incident the same way.

## Workaround used
The actuator accepts the plan's own `evidence_refs`, treats `diagnosis_validated` as true and skips I-07, because only a
holder of the signing key (the control plane, which ran these checks) can produce the envelope. It keeps its OWN attempt,
cooldown and failure counters (rebuilt from the audit file), so I-04 is enforced locally in addition to the control plane.
Audit events without an incident omit the key from the hashed object.

## Resolution (coordinator, 2026-10-31)
**Not applied (deferred, needs a decision).** Signed `attestations` change the envelope schema, the signing code, the actuator and the backend, and weaken or strengthen the trust model depending on design; it needs a decision and a test plan, not a quick edit. Until then I-05 and I-07 are checked by the control plane only, and a compromised control plane holding the key can bypass them (stated in policy STATUS).
