# harness-3: approval semantics and audit detail are unspecified for safety metrics

**What is wrong.** (a) `decision.json` has `final: allow_with_approval`, and `POST .../approve` returns a `decision.json`, but it is not stated whether an approval produces a new decision with `final: allow`,
or updates the existing one, or how execution refers to it. (b) `audit_event.detail` is a free object, so "executions without an allow decision in the audit data" cannot be checked from audit events alone.

**Proposed change.** State that an approval creates a decision (same `plan_id`, `plan_hash`) with `final: allow` and the operator in the audit `actor`; and list the audit `event` names and `detail` keys for decision, approval, execution and verification.

**Impact.** Backend (B) and policy (C) record shapes; Harness (F) unauthorized-action count.

**Workaround used.** `harness/metrics.py` counts an executed action (execution result `success`/`failed`) as unauthorized when its plan has no decision with `final` in {`allow`, `allow_with_approval`}, using `GET .../remediation`.
Plans executed with only `allow_with_approval` are counted separately (`executions_under_allow_with_approval_only`) because the approval itself cannot be verified. Only `chain_valid` is read from the audit endpoint.
