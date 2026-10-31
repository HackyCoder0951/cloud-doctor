# Frontend UX audit and implementation plan

Date: 2026-11-01. Branch: `integration`. Scope: `frontend/` (Next.js 16 static export), against the "incident first" UI/UX brief.
Method: read every source file under `frontend/src`, the mock server, `contracts/openapi.yaml` and schemas, `docs/dev/frontend/STATUS.md`, `docs/dev/conventions.md` and `docs/dev/frontend/ux-prototype.html`. Baseline run before any change: `tsc --noEmit` clean, Vitest 9 files / 132 tests passing.

## 1. Current UI

```
CURRENT UI
  Top bar: Cloud Doctor | Overview Topology Incidents Audit | live badge | Sign out
  Status banner (backend self-health: ok / degraded / fail-closed)
  /                  service cards + open-incident table
  /topology          SVG layered graph (nodes link to the service page)
  /incidents         table + state dropdown
  /incidents/view    summary card, then 6 tabs: timeline evidence diagnosis remediation verification report
  /services/view    health, 5 sparklines, untrusted log lines
  /audit             table with hash-chain badge
```

Stack: React 19, plain CSS in one 83-line `globals.css`, hooks only (`useApi`, `useLiveReload`, one SSE context), no UI library. Data comes from `/api/v1` through a typed client generated from `contracts/openapi.yaml`.

## 2. What works (keep)

- **Safety rendering is excellent.** Every API string goes through `Untrusted` (text node, truncation marker, control and bidi characters made visible). A build-time scan rejects HTML-injection APIs. Ids only become links after matching contract patterns. The brief's trust model builds on this and must not weaken it.
- **Honest unknowns.** `UNKNOWN` is never rendered as healthy, missing signals have their own badges, "no contradicting evidence recorded (this is not proof there is none)" already exists, unverifiable is not a pass.
- **Ranking is already not a probability.** `DiagnosisTab` says so in two places.
- **Approval is deliberate.** `ApprovalPanel` binds approval to `plan_hash`, requires a 3 to 300 character reason, and reuses the idempotency key correctly after a network failure.
- **Live updates** refetch rather than patch state from events, and the connection state is always visible.
- **Evidence ids link** to a focused row in the Evidence tab.
- **Verification** already shows baseline, pre-action and post-action per check, with stability window bounds.
- **Operational hardening**: strict CSP (`style-src 'self'`, hashed scripts), nginx checks, 132 tests, hostile-input tests.

## 3. What is confusing

1. **Nothing says what the problem is.** An incident has `symptoms[]` and a severity, no title. The list and overview show raw symptom strings, so an operator cannot tell "app-db out of connections" from the table.
2. **The cause is a click away.** Likely cause lives only in the Diagnosis tab; the overview, list and incident header never show it.
3. **The incident page opens on Timeline**, the least informative tab, and the summary card is a row of loose labels (`root cause confirmed: false`).
4. **Tabs are named after internals** (diagnosis, remediation) and are lower-case buttons with no order or progress. There is no sense of where in the lifecycle the incident is, and no "needs a human" signal even when a plan awaits approval.
5. **Evidence is a 10-column table.** IDs, hashes and queries have the same weight as the observation. There is no role (supporting, contradicting), no trust label beyond a small UNTRUSTED tag, and no way to open one item.
6. **Evidence ids link to a different tab**, which loses the reader's place in the reasoning.
7. **Topology is a map only.** Clicking a node leaves the page. A failed dependency does not lead to the incident. There is no per-incident view of propagation.
8. **Three vocabularies for colour**: `st-HEALTHY`, `tag-risk-low`, `is-detected`, each with its own rules. Several are colour-only apart from a word.
9. **Light by default, dark only through `prefers-color-scheme`**, with no control and no environment marker. The product's safety story (sandbox, simulation) is invisible.
10. **Safety-critical state is buried**: policy layers are inside plan cards, `/status` dependencies show only when degraded, and there is no place that shows what automation is allowed to do.
11. **Empty and error states are mostly "Loading…" and bare sentences.** No skeletons, no statement of what is missing and what that does to confidence.

## 4. What is missing

Against the brief, grouped by whether the backend can feed it today. This table is the data-honesty contract for the UI: where the answer is "no", the UI shows `Not available`, never a made-up value.

| Brief feature | Data source today | Verdict |
|---|---|---|
| Incident problem title | `symptoms[0]`, top hypothesis `description` | Derive; label as derived |
| Likely cause, ranking, status | `GET diagnosis` (`cause_id`, `confidence`, `status`) | Available. Rename display to "ranking" |
| Evidence coverage %, independent signal types | `confidence_basis` strings (`evidence_coverage=0.73 (…)`, `independent_signal_types=1 (…)`) | Parse defensively; if the string is absent show "not reported" |
| Contradictions, alternatives, unknowns | `contradicting`, `alternatives` (ids only), `unknowns` | Available. Alternatives carry no "reason" or evidence; show the ids, and the reason only when the hypothesis exists in the list |
| Known / unknown panel | `claims` of type observation, plus `unknowns` | Derive; "known" = observation claims with evidence, nothing else |
| Evidence type, source, time, trust | `type`, `source`, `observed_at`, `untrusted`, `status` | Available. Trust label derived from `untrusted` and `source`; no "git verified" or "AI inference" evidence exists yet |
| Lifecycle stepper | `incident.state`, plans, decisions, executions, verifications | Derive; "needs human" = a plan with `allow_with_approval` and no execution, or state `escalated` |
| Per-incident topology | global `/topology` plus `incident.services` | Derive (highlight affected nodes); no propagation edges exist |
| Recent changes, restarts on a service | evidence `deploy_event`, `container_event` | Available only through incident evidence |
| Policy panel | `decision.l1`, `l2`, `final`, `reasons` | Available |
| Execution events | one `execution` record with `argv`, result, times | Available as a single event; the multi-step log (patch created, tests passed) does not exist |
| Verification before/after | per-check `baseline`, `pre_action`, `post_action` | Available |
| Stability window length | `window_start`, `window_end` | Available (45 s today, not 5 minutes) |
| Audit table | `audit_event` | Available. Columns `target` and `result` are inside `detail`; show them only when present |
| Automation page | `GET /status` dependencies (prometheus, logs, database, actuator, policy_layer2, llm) | Partly. No auto-execution flag exists; do not show one |
| Postmortem | `GET report` JSON and Markdown | Available; follow-up actions are not produced |
| Overview counts: pending approvals, active recoveries | derive from incidents and remediation | Pending approvals needs one remediation fetch per open incident; acceptable at demo scale |
| **Code RCA**: file, function, line, snippet | none | **Backend absent** (see current-state analysis §8) |
| **Stack trace**, **git commit / diff / blame** | none | **Backend absent** |
| **Proposed patch**, **patch tests**, code-change remediation | none. The executor only does `restart_service` | **Backend absent** |
| Simulation Control, sandbox/simulation markers | `environment: sandbox` exists only in the catalog; no API | Needs a backend field; until then a static "SANDBOX" marker that states it comes from configuration |
| Access page, roles, current user | no `/auth/me`, no roles (contract change request frontend-3 is deferred) | **Backend absent**; read-only explanation page only |
| Code Intelligence page | none | Out of scope for this pass (P2) |

## 5. What should change

1. A dark, dense design system following the prototype's tokens and naming rules (`--surface-*`, `--status-*`, `block__element--modifier`, state in `data-tone` / `data-state`), replacing the three ad hoc colour vocabularies. Dark is the default; light remains available through the same tokens and a theme control.
2. An incident workspace: a header with severity, derived problem, services, state and a clickable lifecycle; a Summary tab as the landing tab; a persistent action column on wide screens; the existing tabs kept, renamed and reordered to Summary, Timeline, Evidence, RCA, Code RCA, Remediation, Verification, Report.
3. Evidence presented as cards with role and trust, opened in a drawer without leaving the page, keeping the table as an "all evidence" view.
4. A reasoning view: ranked hypotheses with supporting evidence chips, contradictions with the standing caveat, alternatives, and a Known / Unknown panel; a symptom-to-verification chain.
5. A Code RCA tab that renders whatever the backend supplies and otherwise states plainly what is missing (see §7).
6. Overview built around "needs attention": counts, then incidents ranked by severity and need for a human, then service health.
7. Topology becomes clickable investigation: a service side panel (health, dependencies, dependents, incidents, SLIs, recent logs), with failed dependency edges visually distinct and linking to the incident.
8. A global header showing environment, live state, open incident count, theme.
9. Automation and Audit pages upgraded; Access is an honest read-only page.

## 6. What should not change

- `Untrusted`, `safeText`, the id patterns, the forbidden-API scan and `style-src 'self'`: no inline `style=`, no `dangerouslySetInnerHTML`, no external fonts or scripts. The prototype loads Google Fonts; the app must use a system font stack (or self-hosted font files added to `out/`).
- Approval semantics (plan hash, reason, idempotency key), live refetch model, fail-closed status handling.
- The API client, generated types, the routes' query-string shape (static export), mock server structure, `data-testid` hooks used by the 132 tests.
- Backend APIs. Anything the UI needs that the API lacks goes through a contract change request in `docs/dev/contract-change-requests/`, as the project already does, not through a UI workaround.
- Exact dependency pins: no new runtime dependencies are required.

## 7. Conflicts between the brief and the backend (need a decision, defaults chosen)

1. **Code RCA has no data.** Nothing in the backend produces code references, stack traces or commits. Default: define the shape in a contract change request (`frontend-4`: `GET /incidents/{id}/code-analysis`, optional, `404` meaning "not available"). The UI treats `404` as `Not available`, never as an empty success. The mock server serves a fixture for INC-0003 only, labelled as mock data in the response and in the UI banner when `NEXT_PUBLIC_API_BASE` points at the mock. The real backend gets this endpoint in the Code RCA backend work from the earlier plan; the UI does not wait for it.
2. **The brief's demo remediates by deploying a code patch.** The executor can only restart a container, and the invariants forbid anything else. Default: the Remediation tab renders any plan generically (action, params, risk, policy, approval, execution, argv). A "proposed patch" panel and patch-test results render only if a plan carries a `patch` object (also in `frontend-4`). The demo story the code supports today is "restart with approval, then verify". Making the patch story real is a policy and actuator decision, not a UI one.
3. **Stability window is 45 s**, not 5 minutes. The UI shows the actual window from the data.
4. **Alternative hypotheses carry no rejection reason.** Show `alternatives` and, when the alternative is also a ranked hypothesis, its status and contradiction.
5. **Access / roles**: nothing to display. The nav item exists, the page says authorization is enforced by the API and shows the policy layers from `/status`.

## 8. Priorities

### P0: required for the demo (complete incident journey)
1. Design tokens, dark theme, theme control, global header with environment and live state, SANDBOX marker.
2. Incident workspace: header, lifecycle stepper (clickable, explains each stage), Summary tab with what happened, likely cause (ranking, coverage, signal types), Known / Unknown, next action.
3. Evidence: cards with role and trust, ids open a drawer; table kept.
4. RCA tab: ranked hypotheses, supporting and contradicting evidence, alternatives, unknowns, symptom-to-cause chain; AI/rule origin labelled (OBSERVED / INFERRED / HYPOTHESIS / RECOMMENDED / CONFIRMED / UNKNOWN badges driven by claim type and hypothesis status).
5. Code RCA tab with code viewer, stack-trace viewer and git context components, honest `Not available` state, mock fixture.
6. Remediation: recommendation card, policy panel (L1/L2), deliberate approval with the approval summary, execution timeline from real records, optional patch panel.
7. Verification: check list with before/after, stability window, verdict. Report tab as postmortem view.
8. Overview "needs attention", incident list as an SRE queue with problem, cause, evidence coverage.
9. Tests for each new component and the data-honesty cases; all 132 existing tests kept green or consciously updated.

### P1: important
- Topology investigation panel and per-incident highlighting; service detail upgrade.
- Audit table columns per brief; Automation page from `/status`.
- Loading skeletons, structured error states, "evidence collection failed" states.
- Incident list filters (severity, service, cause, time).
- Keyboard and focus audit, `aria` review, responsive layouts at 1440 / 1280 / 1024.

### P2: nice to have
- Code Intelligence page, Access page beyond an explanation, Simulation Control panel (needs a backend scenario API), postmortem follow-up checklist, MetricComparison charts beyond the bars.

## 9. Implementation plan

Incremental, each step ends green (`npm run typecheck`, `npm test`, `npm run scan`) and is committed on its own.

1. **Tokens and shell.** Port the prototype's tokens and primitives into `globals.css` using the project naming rules; system font stack; header with environment, live, open incidents, theme (stored in `localStorage`, guarded); SANDBOX marker. Rename legacy classes as each component is touched.
2. **Shared components** (`components/ui/`): `SeverityBadge`, `StatusPill`, `EvidenceChip`, `EvidenceDrawer`, `TrustBadge`, `ClaimKindBadge`, `Stepper`, `EmptyState`, `Skeleton`. Only what two or more screens use.
3. **Derived view model** (`lib/incident-view.ts`): pure functions from API data to `problem`, `likelyCause`, `lifecycle`, `needsHuman`, `known`, `unknown`, `coverage`. Unit-tested, including the "absent means not reported" cases. This keeps business inference out of components and makes data honesty testable.
4. **Incident workspace**: header, stepper, Summary tab, tab order, landing tab, wide-screen action column.
5. **Evidence and RCA tabs** with the drawer and chain.
6. **Remediation, Verification, Report** upgrades.
7. **Code RCA**: contract change request `frontend-4`, optional client call, types, mock fixture, components, tests.
8. **Overview, Incidents, Topology, Service, Audit, Automation, Access.**
9. **End-to-end pass**: run the mock server and `next dev`, click through the demo path at 1440 / 1280 / 1024, run `npm run ci`, update `docs/dev/frontend/STATUS.md`.

## 10. Risks

- **Test churn.** `views.test.tsx` (27 tests) asserts on current markup and text. Expect targeted updates; behaviour assertions (ids, links, hostile rendering, approval) must survive unchanged.
- **CSP hashes.** Any rebuild changes the page flight-data hash; `postbuild` regenerates `infra/nginx/csp-script-hashes.conf`, which must be committed with the UI.
- **Scope.** The brief is large. The plan protects the end-to-end incident path first and leaves breadth (Code Intelligence, Simulation Control, Access) for after the demo.
- **Never run against the real backend.** The mock is the only integration partner so far; shapes inferred from `confidence_basis` text are the most fragile and are parsed defensively.
