# Stream C status: policy and actuator (branch `stream/policy`)

Date of last run: 2026-10-30. Everything below marked "run" was run in this session; nothing else is claimed.

## Summary

| Part | State |
|---|---|
| `invariants/` (Layer 1 I-01..I-08, signing, catalogue, `compose_decision`) | **Done**, tested |
| `actuator/` (unix-socket server, signature/expiry/nonce/hash/approval checks, Layer 1 re-run, idempotency, `docker restart` via injectable runner, hash-chained NDJSON audit, `python -m actuator`, test client) | **Done**, tested with a fake runner. Never run against a real Docker daemon |
| `policy/` Layer 2 (fail-closed OPA client, minimised input, glue to composition) | **Done**, tested with a Python OPA double and a loopback fake OPA |
| `policy/rego/` (default deny; freeze window, per-service allowlist, cache-restart approval, confidence threshold) and `policy_test.rego` | **Executed by the coordinator (2026-10-31)**: `opa check policy/rego` exit 0 and `opa test policy/rego` PASS 13/13 on OPA 1.22.0 (official `openpolicyagent/opa:latest-static` image, digest `sha256:2e5f84895445ca479be9eb1f2473c904a447b5ec53e6a487e0fcb3193d651ed8`), run through Docker because the vendor host is blocked by the cloud egress policy. The two `tests/policy` OPA tests then pass (108 passed, 0 skipped). Not run: a live OPA server with a signed bundle (B4 bundle checks), and the Rego was only tested with its own inputs |
| `docs/dev/policy/INTEGRATION.md` | Done |
| Postgres audit sink (`CD_AUDIT_SINK=postgres`) | **Not started**: the actuator refuses to start with it; NDJSON file only |

## How to run the tests

```bash
pip install pytest==9.2.0                      # only dev dependency
pip install jsonschema==4.26.0 referencing==0.37.0 pyyaml==6.0.3   # optional: enables contract-schema and YAML-catalogue tests (otherwise skipped)
python3 -m pytest tests/invariants tests/actuator tests/policy -q
python3 tests/contract/validate_contracts.py
```

Result of the last run: `318 passed, 2 skipped` (the 2 skipped are the `opa test` / `opa check` tests, skipped because `opa` was not installed in that session; the coordinator later ran them with OPA 1.22.0 and they pass);
contract validator `RESULT: PASS (0 failures)`. Tests need no Docker, no external network and no OPA. Two test modules use loopback only
(a fake OPA HTTP server on 127.0.0.1, and unix sockets for the actuator server); they skip if binding fails.

## Where the required test cases live

* Rules I-01..I-08 positive and negative, adversarial plans: `tests/invariants/test_inv_rules.py`.
* Signing, hashing (checked against `contracts/examples/plan.example.json` and the audit example), catalogue, stdlib-only import check: `test_inv_canonical_catalog.py`.
* Composition matrix and "Layer 2 can never loosen Layer 1": `test_inv_compose.py` (L1 x L2, schema-validated) and `tests/policy/test_pol_engine.py` (end-to-end through the OPA client).
* Tampered plan, wrong key, expired, future-dated, replayed nonce, mismatched approval, medium without approval, high with approval, attempts, cooldown, circuit breaker, unlabeled container, container not in catalogue, audit failure, idempotency, hash-chain verification and tamper detection, source scan for `shell=True` / `os.system` / `eval` / `exec`: `tests/actuator/test_act_execute.py`.
* Unix socket server (mode 0660, 400/404/405, oversized body), real `SubprocessRunner` (no shell, environment limited to PATH), env-only startup: `test_act_server.py`.
* OPA failure modes (connection error, non-200, malformed JSON, 200 without `result`, bad result shape, unsigned/stale/inactive bundle): `tests/policy/test_pol_client.py`, `test_pol_transport.py`.

## Assumptions

1. **I-05 / I-07 / circuit breaker in the actuator**: the envelope cannot carry evidence ids, the validated-diagnosis flag or the top cause. The actuator treats the signature as attestation for I-05 (accepts the plan's own `evidence_refs`, diagnosis validated) and does not evaluate I-07. It enforces I-04 with its own counters. See `contract-change-requests/policy-2.md`. This means a compromised control plane holding the key can bypass I-05/I-07, which is inherent to the contract as frozen.
2. `/v1/validate` reports envelope failures as `I-08` because its schema only allows `I-xx` ids (`policy-1.md`); `/v1/execute` returns precise `A-*` ids.
3. Risk floors: `restart_service` is low except on a `cache` (medium) and a `database` (high); rollback, scale, clear_cache and isolate_dependency are medium; escalate is low. A service label `risk.<action>` in the catalogue can override ("unless the catalogue says otherwise"). `queue_worker` is treated as stateless (the queue lives in redis).
4. I-07 is applied to `restart_service` of ANY service other than the cause (not only transitive dependents) when the top cause is down; if `down_services` is not supplied the cause is assumed down.
5. `escalate` is exempt from I-04 (budget, cooldown, circuit breaker) and from Layer 2 restrictions so that escalation stays possible; it is not executable by the actuator in the MVP (`A-UNSUPPORTED`).
6. Envelope lifetime is capped at 15 minutes and clock skew for `issued_at` is 2 s. Idempotent replays return the stored result even after the envelope expired.
7. Extra environment variable `CD_SIGNING_KEY_ID` (default `mvp-1`). The key file must be a regular file, mode 0600, at least 16 bytes.
8. `PolicyContext` gained optional fields `down_services`, `max_attempts`, `cooldown_seconds`; `ValidationResult` gained `passed_rule_ids`, `pending_approval`, `plan_id`, `plan_hash`. `compose_decision` takes optional keyword arguments (`plan`, `decision_id`, `now`). Decision `l1.rule_ids` lists passed rules on a pass and violated rules on a deny. A decision for a plan whose id or hash cannot be read uses the placeholders `PL-0000` / zero hash so it still validates against the schema.
9. In-process dry runs have no Docker, so `container_labels` must be supplied by the caller (`Catalog.declared_labels` is a declared-labels stand-in). If it is missing, I-02 denies.

## Residual risks and known gaps

* **The actuator needs Docker daemon access**, which is root-equivalent on the daemon's host (TM-04). Controls here: fixed argv, name regex plus catalogue match, sandbox label check, no exec/run/mounts, but the process still holds the capability; run it as its own user against the MicroVM's private daemon. The actuator was not run against a real daemon.
* The subprocess environment is reduced to `PATH`, so a daemon reachable only through `DOCKER_HOST` or a non-default context will not work until Stream A / the coordinator decides how the actuator reaches the sandbox daemon.
* The label check and the restart are separate Docker calls (small time-of-check/time-of-use window).
* Layer 2 bundle signature state is not verified by the client: `OpaHealthEndpoint` reads `GET /health?bundles` only and takes "signed" from operator configuration. The OPA endpoint semantics were not verified against the full docs, and staleness uses the `last_activated` value the health implementation supplies.
* The Rego was first executed by the coordinator after this stream ended (see above). The decision path `cloud_doctor/policy/decision` is this stream's choice.
* Audit is a local file; there is no external anchoring, so someone with write access to the file and the ability to recompute hashes can rewrite the whole chain (the chain detects partial edits, deletions and reordering). A torn or tampered file makes the actuator refuse to start.
* Single-threaded server: a slow client can delay others up to the 10 s socket timeout.
* No load, fuzz or property-based testing beyond the parametrised adversarial cases; no measured numbers are claimed.
* The change requests `policy-1.md` and `policy-2.md` are proposals; the coordinator has not decided them.

## Git

Commits are on local branch `stream/policy` (based on `main` at 2113b85). Pushing was **blocked** in this session: `git push` returned HTTP 403 ("Claude doesn't have GitHub access to HackyCoder0951/cloud-doctor"), so nothing has been pushed yet. No pull request was opened and nothing was merged.
