# Integrating with the policy stack (for the backend stream)

Packages: `invariants` (stdlib only, Layer 1 and signing), `actuator` (separate process), `cd_policy` (Layer 2 client).
Layout: `invariants/invariants/`, `actuator/actuator/`, `policy/cd_policy/`; install each directory with
`pip install ./invariants ./actuator ./policy`, or put the three directories on `PYTHONPATH`.

## 1. Build and sign a plan

```python
import invariants as inv

plan = {...}                                  # every plan.json field except plan_hash
plan["plan_hash"] = inv.plan_hash(plan)       # hash of the plan WITHOUT plan_hash

envelope = {
    "plan": plan,
    "key_id": "mvp-1",                        # must equal the actuator's key id (CD_SIGNING_KEY_ID, default mvp-1)
    "issued_at": "2026-11-02T09:00:28Z",
    "expires_at": "2026-11-02T09:02:28Z",     # at most 15 minutes after issued_at; keep it short
    "nonce": "n8Qx2vLk0pTzR4mW",              # 16..64 chars [A-Za-z0-9_-], NEVER reused
}
if approval:                                  # medium risk only; MUST be bound to this plan's hash
    envelope["approval"] = {"approver": "alice", "approved_at": "...", "plan_hash": plan["plan_hash"]}
key = open(os.environ["CD_SIGNING_KEY_FILE"], "rb").read().rstrip(b"\r\n")   # mode 0600, >= 16 bytes
envelope["signature"] = inv.sign_envelope(envelope, key)   # HMAC-SHA256 hex over canonical JSON without `signature`
```

Rules of thumb: the signature covers the optional `approval` too, so sign AFTER attaching it; omit `approval`
instead of sending `null`; any change to the plan changes `plan_hash` and invalidates signature and approval.
`actuator.client.build_signed_plan(plan, key, nonce=..., approval=...)` does the above.

## 2. Decide (Layer 1 + optional Layer 2)

```python
ctx = inv.PolicyContext(catalog=inv.Catalog.load(path), now=datetime.now(timezone.utc),
        attempts_used=..., last_attempt_at=..., circuit_open=..., known_evidence_ids=set(...),
        diagnosis_validated=True, top_cause_service="redis", down_services={"redis"},
        container_labels=catalog.declared_labels)    # in-process stand-in; the actuator checks the REAL labels
l1 = inv.validate_plan(plan, ctx)                    # never raises; ok / rule_ids / reasons / requires_approval
decision = cd_policy.decide(plan, l1, layer2_policy_or_None, target_kind="cache", confidence=0.9,
                            counters={"attempts_used": 0}, tenant="acme", channel="C0", now=now)
# decision conforms to contracts/schemas/decision.json; decision["final"] is allow | allow_with_approval | deny
```

* Medium risk without an approval yet gives `l1.pending_approval == True` and `final == "allow_with_approval"`
  (not a deny). Attach the human approval, re-sign and execute.
* `high` is never executable. Any Layer 2 problem (OPA down, non-200, 200 without `result`, unsigned or stale
  bundle) gives `final == "deny"`. Layer 2 can only tighten.
* Layer-1-only mode: pass `None` as the Layer 2 policy.

## 3. Call the actuator (unix socket `CD_ACTUATOR_SOCKET`, HTTP/1.0 JSON)

```python
from actuator.client import ActuatorClient
c = ActuatorClient(os.environ["CD_ACTUATOR_SOCKET"])
c.healthz()                                    # {"state": "ok" | "degraded", "invariants_version": "inv-0.1"}
c.validate(envelope)                           # dry run: {"ok", "rule_ids", "reasons", "invariants_version"}; no side effects
c.execute(envelope, "idem-0001-a")             # {"execution": {...}}  (idempotency key: 8..64 chars [A-Za-z0-9_-])
```

* HTTP 200 for every well-formed request, including refusals: look at `execution.result`
  (`success` | `failed` | `refused`) and `execution.refusal_rule_ids`. HTTP 400 means the request itself was malformed;
  500 means an internal error and nothing was executed. Treat anything that is not a clean `success` as "not executed".
* Idempotency: the same key with the same envelope returns the ORIGINAL execution and never re-executes (even after the
  envelope expired). The same key with a different request is refused (`A-IDEMPOTENCY`). Refusals do not consume the key.
* Nonces are consumed only when execution starts. Re-sending the same envelope under a new idempotency key is
  refused as replay (`A-REPLAY`); sign a fresh envelope with a fresh nonce for a retry.
* `/v1/validate` reports only `I-xx` ids (envelope failures show as `I-08` with the precise `A-*` id in `reasons`,
  see contract-change-request policy-1). `/v1/execute` reports the precise ids.
* Only `restart_service` executes in the MVP; other catalogue actions are refused with `A-UNSUPPORTED`.
* The actuator keeps its own attempt budget (2), cooldown (20 s) and failure circuit breaker, rebuilt from its audit file.

## 4. Run the actuator

```bash
CD_ACTUATOR_SOCKET=/run/cloud-doctor/actuator.sock CD_SIGNING_KEY_FILE=/etc/cloud-doctor/signing.key \
CD_AUDIT_SINK=/var/lib/cloud-doctor/actuator-audit.ndjson CD_CATALOG_PATH=infra/catalog/services.yaml \
PYTHONPATH=invariants:actuator python3 -m actuator
```

`CD_AUDIT_SINK=postgres` is not implemented (the process refuses to start); use a file path. A `.yaml` catalogue needs
PyYAML in the actuator environment; a `.json` catalogue needs nothing. `CD_SIGNING_KEY_ID` (default `mvp-1`) is the one
extra variable this stream added. The audit file is hash-chained; verify with `actuator.audit.verify_chain(path)`.
