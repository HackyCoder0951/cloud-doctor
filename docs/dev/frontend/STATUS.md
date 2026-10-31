# Stream D (frontend) — STATUS

Branch `stream/frontend`, base `main` @ `2113b85`. Written from what was actually run; anything not run is listed under "Not verified".

## Summary

| Area | Status |
|---|---|
| Tooling: OpenAPI → TypeScript types, stale check, fetch client, Idempotency-Key, safe errors | **Done** |
| Mock server (`frontend/mock/`, plain Node, SSE with `Last-Event-ID` replay, cookie login) | **Done** |
| Views: login, Overview, Topology, Incidents list, Incident detail (Timeline, Evidence, Diagnosis, Remediation, Verification, Report), service Metrics + Logs, Audit, live updates | **Done** (see gaps) |
| Security rules: no HTML-injection APIs, escaped text only, scan that fails the build | **Done** |
| nginx config, security headers, static checker, `nginx -t` | **Done** |
| Tests (Vitest + Testing Library) | **Done**: 132 tests / 9 files passing |
| Pushed to GitHub | **NOT DONE**: `git push` returned HTTP 403 (the Claude GitHub App has no access to `HackyCoder0951/cloud-doctor`). All commits exist only in the local clone of this session. |
| Run against the real backend | **Not started** (backend is another stream; only the mock was used) |

## Commands (all from `frontend/`, Node ≥ 20.9; developed on Node 22.22.0 / npm 10.9.4)

```bash
npm ci                      # exact pinned versions from package-lock.json
npm run mock                # mock API on http://127.0.0.1:8080/api/v1 (PORT / HOST override); login: any token of 8+ chars
npm run dev                 # Next dev server on :3000; .env.development points it at the mock (CORS + cookie work across ports)
npm run gen:api             # regenerate src/api/schema.d.ts from ../contracts/openapi.yaml (openapi-typescript 7.13.0)
npm run check:api           # exit 1 if src/api/schema.d.ts is stale (part of `npm run ci`)
npm run scan                # forbidden-API scan (also runs as `prebuild`, so `npm run build` fails on a violation)
npm run typecheck           # tsc --noEmit
npm test                    # vitest run
npm run build               # static export to frontend/out (+ postbuild regenerates infra/nginx/csp-script-hashes.conf)
npm run check:nginx         # static header/proxy checks, then `nginx -t` if nginx exists
npm run ci                  # all of the above in order
NODE_PATH=$(npm root -g) node scripts/verify-nginx-e2e.mjs   # optional: real nginx + Chromium + mock (needs nginx and a global playwright)
npm run nginx:render -- --upstream HOST:PORT --root DIR --listen ADDR   # print the nginx config with overrides
```

Also run before each commit batch: `python3 tests/contract/validate_contracts.py` → `RESULT: PASS (0 failures)` (last run after the nginx commit).

## Results recorded from real runs

- `npm run ci` (clean `out/` and `.next/`): exit 0. check:api ok; scan ok; `tsc --noEmit` clean; Vitest **9 files, 132 tests passed**; `next build` compiled and generated **9 static pages** (`/`, `/_not-found`, `/audit`, `/incidents`, `/incidents/view`, `/login`, `/services/view`, `/topology`, plus the 404 page), `frontend/out` ≈ 956 KB; check:nginx ok including `nginx -t` on **nginx 1.24.0** (installed in the session container with apt to be able to run it).
- `scripts/verify-nginx-e2e.mjs`: **20/20 checks passed**: real nginx serving `frontend/out`, proxying to the mock; Chromium (Playwright) loaded every route with headers present and **zero CSP violations from the app**, login through the proxy, SSE connected through nginx and **reconnected after the stream was dropped**, an injected inline script **was blocked** by the CSP, hostile evidence rendered as inert text, the approve flow worked end to end, unknown path → 404 page with headers, `/.env` → 404.
- Stale detection is exercised: appending a line to `src/api/schema.d.ts` makes `npm run check:api` exit 1.
- Bugs the tests/e2e run found and that are fixed: the live-update `subscribe` function changed identity on every connection-state change and cancelled the post-reconnect resync; the approve/reject confirmation vanished when the approval panel unmounted; nginx without `mime.types` served scripts as `text/plain`, which `nosniff` then refuses.

## F1 — the strictest CSP a Next.js static export can run with (answer)

**Finding.** `output: 'export'` pages contain **3 inline `<script>` elements each** (no inline `<style>`, no `style=` attributes, no inline event handlers once the UI uses none and the default 404 page is replaced):

1. `(globalThis["TURBOPACK"] ...).push(...)` chunk registration, 243 bytes, identical on every page;
2. `(self.__next_f=self.__next_f||[]).push([0])`, 43 bytes, identical on every page;
3. `self.__next_f.push([1, "..."])`, the React flight/RSC payload, ≈3.3–4.5 KB, **different per page** and containing the build id and chunk paths.

Next's own guidance for nonce-based CSP does not apply (a nonce needs a per-request render, impossible for static files), so without hashes the policy would need `script-src 'unsafe-inline'`, which defeats script CSP. **Chosen policy:** `script-src 'self' 'sha256-…' …` (10 hashes for the current build, no `'unsafe-inline'`, no `'unsafe-eval'`) and `style-src 'self'`. This was **run in Chromium behind nginx** and the app hydrated and worked with no violations (e2e above), and an injected inline script was blocked.

**What makes it work, and its cost.**
- `scripts/gen-csp-hashes.mjs` hashes every inline script of `out/**/*.html` and writes `infra/nginx/csp-script-hashes.conf` (`set $cd_script_hashes "…"`) from the `postbuild` script; the hashes are the union over all pages (one global header, not per page).
- `next.config.mjs` sets a **fixed `generateBuildId`** (`cloud-doctor-static`, overridable with `CD_BUILD_ID`); with the default random build id every rebuild changed the page-specific hashes (measured: only 2 of 10 hashes survived a rebuild). With the fixed id two clean rebuilds of the same source produced identical hashes. Chunk file names stay content-hashed, so the flight-data hash still changes when the code changes.
- **Operational rule:** the committed hash file must be regenerated whenever the UI is rebuilt and deployed together with `out/`; a stale list makes the browser block that page's flight data (the page would not hydrate). `npm run check:csp` / `npm run check:nginx` fail when the include does not match `out/`. HTML is served `Cache-Control: no-cache` for the same reason.
- `style-src 'self'` works only because no code uses inline styles (`style={...}` is a scan violation); Next's default 404 page uses inline styles, hence `src/app/not-found.tsx`.
- Remaining weakness: inline scripts are allowed by hash, so an attacker who can *modify the served HTML* is not stopped by the CSP; the primary XSS defence remains escaped text rendering (no HTML sinks, tested). CSP is defence in depth, as tech-stack.md §2.1 anticipated.
- Not used: SRI-based CSP (experimental in Next per the docs) and `'strict-dynamic'`.

## Versions (exact, from package.json / lockfile)

next 16.4.3, react / react-dom 19.3.1, typescript 5.9.3, openapi-typescript 7.13.0, vitest 3.2.7, jsdom 26.1.0, @testing-library/react 16.3.3, @testing-library/jest-dom 6.10.0, @testing-library/user-event 14.6.8, ajv 8.20.0, ajv-formats 3.0.1, yaml 2.9.0, @types/node 20.19.43, @types/react(-dom) 19.3.0. Vitest 3 was chosen over 5 because Vitest 5 requires Node ≥ 22.12 while the requirement is Node ≥ 20. No ESLint: the forbidden-API rule is a script + unit test instead, which was the allowed alternative. `typescript` is 5.9.3 because openapi-typescript 7.13.0 declares a `^5.x` peer.

## Design decisions worth knowing

- **Routes** use query strings (`/incidents/view/?id=INC-0002&tab=evidence&ev=EV-101`, `/services/view/?name=api`, `/audit/?incident=…`) because a static export cannot have runtime dynamic segments. Every id is checked against the contract pattern before it is used or turned into a link; invalid ids are not fetched.
- **Untrusted text**: every API-supplied string goes through `Untrusted` (React text node, truncation at 600 chars by default with a visible `[truncated, N chars]` marker, control/bidi characters shown as `\uXXXX`). Evidence/log payload JSON is shown as truncated text. No `href`/`src` is built from API strings except ids that match the contract patterns.
- **Errors**: `ApiError` shows a status-derived sentence plus a `code` and rule ids only if they match strict patterns; the server's `message` is never displayed.
- **Idempotency-Key**: generated per user action (32 hex chars). After a network failure (outcome unknown) a retry **reuses** the key; after any definitive HTTP answer the next click gets a new key. Every POST (including login/logout) carries one; the contract requires it only on diagnose/approve/reject.
- **Live updates**: `EventSource(withCredentials)`; events trigger a debounced refetch of the affected view (the UI never patches state from event payloads, so a malformed or hostile event cannot change what is displayed); every reconnect triggers a resync. The connection state (connected / connecting / reconnecting / offline) is always visible in the top bar. If `/status` is unreachable the banner shows fail-closed wording rather than "OK".
- **No business logic** in the UI: approve/reject send `plan_hash` and `reason` and display the API's decision; roles, policy and hash verification are the API's job. The UI cannot create plans or executions (none of those endpoints exist).
- nginx: `proxy_pass http://cd_api;` forwards the URI unchanged (assumption below); security headers are included in every location (nginx does not inherit `add_header` into a block with its own).

## Assumptions and contract change requests

- `docs/dev/contract-change-requests/frontend-1.md`: the report endpoint's behaviour for an incident without diagnosis is undocumented; assumed `404`.
- `…/frontend-2.md`: whether the backend serves `/api/v1/...` itself or nginx strips the prefix is undocumented; assumed the backend serves `/api/v1/...` (nginx forwards unchanged).
- `…/frontend-3.md`: `Last-Event-ID` cannot be sent on a manually reopened `EventSource` (UI resyncs instead); no endpoint exposes the caller's role (buttons are always shown, 403 is displayed).
- The generated types render free-form objects (`payload`, `data`, `params`) as `Record<string, never>`; `src/api/types.ts` re-types them as `Record<string, unknown>`. This is a generator limitation, not a contract error.
- The mock's audit data: `chain_valid` is `true` except for `GET /audit?incident=INC-0003`, which returns `false` with a tampered event. Mock hashes are plausible, not verified, and the real chain is verified only by the backend.
- The mock-only services `batch-job`, `notifier` and `search` are not in `infra/catalog/services.yaml`; they exist to cover the three missing-signal states on UNKNOWN services.
- Files outside `frontend/` and `infra/nginx/` that were written: `docs/dev/frontend/STATUS.md` and `docs/dev/contract-change-requests/frontend-{1,2,3}.md` (the latter explicitly requested by `streams.md`). `frontend/scripts/gen-csp-hashes.mjs` writes into `infra/nginx/`, which this stream owns.

## Known gaps / not verified

- **Not pushed** (see above). Nothing was merged and no PR was opened.
- **Never run against the real backend.** Behaviour on real data volumes, real 4xx/5xx bodies and the real SSE server is untested; the mock follows the contract (Ajv validation of every mock response against `contracts/openapi.yaml` and `contracts/schemas/*.json` passes) but is not the backend.
- **Node 20 not run.** `engines` says `>=20.9.0` (Next requires it; Vitest 3.2.7 supports 20), but everything was executed on Node 22.22.0.
- **Browsers**: only Chromium (Playwright's) was used for the e2e run; the screenshots were reviewed by eye once (Overview, Topology, Evidence, Remediation). No Firefox/Safari, no mobile device, no accessibility audit (semantic roles/labels are used; no axe run), no visual-regression tests.
- **TLS** is not configured or tested (the config listens on `127.0.0.1:8088`, HSTS is documented but off). The API's `Secure` cookie requires HTTPS outside local development, so a TLS terminator is needed in front.
- Blob-URL Markdown download is implemented but only the "Show Markdown" path is covered by a test (jsdom has no `createObjectURL`); CSP behaviour for the download was not exercised.
- Audit view shows at most 100 events (no "load more"); incident list limit is the API default (50); metric window is fixed at 10 min and logs at 5 min/100 lines; evidence metric series are shown as JSON text, not charted.
- Topology layout is a simple layered placement; edges can cross for dense graphs.
- Re-diagnose has a button but is not covered by its own test; reject's confirmation path is covered.
- `npm audit` reports 3 vulnerabilities, **all in dev dependencies** (Vitest 3.x's `@vitest/mocker` and `tinypool`; the fix is Vitest 5, which needs Node ≥ 22.12). `npm audit --omit=dev` reports 0. They affect the test runner on a developer/CI machine, not the shipped static files.
- The committed `infra/nginx/csp-script-hashes.conf` reflects the build of the committed source; any UI change requires rebuilding and committing it (CI check `check:csp` enforces this when `out/` exists).

## UI pass 2026-11-01: incident workspace (see `ux-audit.md` for the plan and the data-honesty table)

**Verified by running.** `npm run ci` exit 0 (API freshness, forbidden-API scan, `tsc`, Vitest **12 files / 177 tests**, `next build` with 11 static pages, CSP hash regeneration, `nginx -t` on nginx 1.26.3). The app was also driven in a browser against the mock server: login, Overview, incident workspace (summary), Code RCA, Topology service panel. Not done: the real nginx + Chromium e2e script, a pass at 1280 and 1024 widths by eye, a screen-reader pass, and any run against the real backend.

**Built (P0).** Dark design tokens with a light theme toggle (stored per viewer, works without storage); header with environment marker, live state, open-incident count; incident workspace (header with derived problem line, clickable 4-stage lifecycle, Summary tab, action rail, reasoning chain); evidence cards with role and trust labels and an evidence drawer opened from any evidence id; RCA tab with ranking caveat, supporting and contradicting claims labelled OBSERVED / INFERRED / HYPOTHESIS, alternatives, unknowns; Code RCA tab (source viewer, stack-trace viewer, git context, "why this line"); remediation policy check, BLOCKED state, execution timeline, approval summary, optional patch panel; verification before/after and window length; postmortem section in the report; Overview as an operational picture (six counts, Needs attention, active incidents, service health, recent recovery actions); incident list as a queue; Topology with a service side panel; Audit in the brief's column shape; Automation page from `/status`; Access page.

**Data honesty rules enforced and tested.** No incident title in the API, so the title is derived from the first symptom and says so. Evidence coverage and signal types are parsed from `confidence_basis` text and show "not reported" when absent. A diagnosis `404` is "No diagnosis yet", a code-analysis `404` is "Not available" (never an empty success). Trigger, follow-up actions, rollback availability, recent changes, current user and roles are shown as not available because the backend does not provide them.

**Mock vs real.** Code RCA data exists only in the mock (`mock/code.mjs`, flagged `mock: true`, shown with a MOCK DATA banner). The endpoint and a plan `patch` field are proposed in `docs/dev/contract-change-requests/frontend-4.md`; the real backend serves neither, so against it the Code RCA tab says "not available".

**Deviations from `docs/dev/conventions.md` section 5.** Legacy class names (`badge st-*`, `tag-*`, `evlink`, `arg`, `spark`) were kept because tests and hooks depend on them; new components use block__element naming and `data-*` for state. No external fonts: the prototype's Google Fonts would violate `style-src 'self'`, so the app uses a system font stack.

**Not built.** Simulation Control (needs a backend scenario API), Code Intelligence page, service detail upgrade (dependencies and incidents on the service page; the topology panel covers most of it), filters by cause and time on the queue, skeleton loaders on the login and service pages, a "collecting evidence" progress view, and the brief's "Approve & Execute" wording (kept "Approve plan": execution is system-initiated, so the button must not claim to execute).
