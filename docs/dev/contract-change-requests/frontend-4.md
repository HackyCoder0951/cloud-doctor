# frontend-4: code-level RCA and an optional patch on a remediation plan

**What is missing.** The incident workspace has a Code RCA tab (file, function, line, stack trace, git commit, reasoning linked to evidence). Nothing in `contracts/openapi.yaml` or the schemas carries that data, and the backend produces none (`docs/current-state-analysis.md` section 8).

**Proposed change.**

1. `GET /incidents/{incident}/code-analysis` returning `code_analysis` (below). `404` means "the backend has no code analysis for this incident".
2. An optional `patch` object on `plan`, present only when a plan proposes a code change:
   `{ file: string, lines: [{ op: "+"|"-"|" ", text: string }], tests: [{ name: string, result: "passed"|"failed"|"not_run" }] }`.

```json
{
  "incident_id": "INC-0003", "generated_at": "...", "origin": "rule", "engine_version": "code-rca-0.1",
  "findings": [{
    "code_rca_id": "CRCA-0001", "title": "...", "status": "candidate|supported|strong_candidate|confirmed|rejected|unknown",
    "ranking": 0.81, "service": "worker", "mechanism": "...", "evidence_ids": ["EV-201"],
    "locations": [{ "repository": "...", "branch": "main", "commit": "7c91a21", "file": "worker/config.py", "line_start": 38, "line_end": 44,
                    "symbol": "load_config", "language": "python", "snippet": [{ "line": 43, "text": "..." }], "highlight": [43] }],
    "stack_trace": [{ "file": "worker/config.py", "line": 43, "function": "load_config" }],
    "commit": { "sha": "7c91a21b3f0e", "subject": "...", "author": "...", "committed_at": "...", "files_changed": ["..."], "diff": [{ "file": "...", "lines": [{ "op": "+", "text": "..." }] }] },
    "runtime_symptoms": ["..."], "next_step": "...", "unknowns": ["..."], "alternatives": ["..."]
  }]
}
```

`ranking` is an evidence-weighted prioritisation score, not a probability. All strings are untrusted text.

**Impact.** Backend: a new optional endpoint, produced by the Code RCA pipeline in the evolution plan. Harness: none. Policy: a `patch` on a plan does not change what the actuator may execute; the executor still only runs catalogue actions, so a patch is display-only until a patch action is added to the catalogue and invariants.

**Workaround used.** The UI treats `404` as "Not available" (never as an empty success) and parses the response defensively (`frontend/src/lib/code-analysis.ts`), dropping malformed findings. The mock serves a fixture for INC-0003 flagged `mock: true`, and the UI shows a MOCK DATA banner for it. A plan `patch` is rendered only if present and well-formed.
