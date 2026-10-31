# Naming and data-format conventions

Status: proposed 2026-11-01. Rules marked **frozen** come from `contracts/` and cannot change without a contract-change note. Rules marked **new** are introduced here and apply to code written from now on.

## 1. One rule for the whole system

Raw data from a service is never read by anything downstream. It is converted once, at the edge, by `backend/normalize`, into the canonical records in section 4. Detectors, the RCA, the report and the UI read canonical records only.

## 2. Names

| Thing | Convention | Example | Source |
|---|---|---|---|
| Service (catalog name) | lower-case, letters, digits and `-`, 2–41 chars, starts with a letter. The `cd-` container prefix is not part of the name | `api`, `app-db` | frozen |
| Container | `cd-` + service name | `cd-api` | frozen |
| Incident / evidence / plan / decision / execution / timeline event ID | prefix + zero-padded number | `INC-0003`, `EV-034`, `PL-0001`, `DEC-0001`, `EX-0001`, `TL-0001` | frozen |
| Hash | `sha256:` + 64 hex | `sha256:7b1e…` | frozen |
| Cause ID | `<service_with_underscores>_<cause>` | `app_db_connection_exhaustion` | frozen (`contracts/cause_ids.md`) |
| Action ID | lower snake_case verb phrase | `restart_service`, `escalate` | frozen |
| Metric | lower snake_case; our own metrics start with `cd_`; unit as the last word (`_seconds`, `_bytes`, `_ratio`); counters end in `_total`; 0/1 flags have no unit suffix | `cd_db_connections`, `cd_fs_used_bytes` | frozen (`telemetry.md`) |
| Metric label | lower snake_case; `service` and `env` on every series; a dependency uses `dependency` | `service="app-db"` | frozen |
| Log field | lower snake_case. Required: `ts`, `level`, `service`, `msg`. Optional: `request_id`, `error` | `request_id` | frozen |
| JSON key in any API body, file or event | lower snake_case | `confidence_basis` | frozen |
| Enum value | lower snake_case, except `HealthState` (`HEALTHY`, `DEGRADED`, `UNHEALTHY`, `UNKNOWN`) which stays upper-case | `allow_with_approval` | frozen |
| Log level | `debug`, `info`, `warn`, `error` (`unknown` only inside normalised records) | `warn` | frozen / new |
| Normalised health state | `up`, `degraded`, `down`, `unknown` (not the same set as `HealthState`; see 5) | `up` | new |
| Python module / function / variable | `snake_case`; class `PascalCase`; constant `UPPER_SNAKE`; private `_leading` | `NormalizedLog` | new |
| Python test | `test_<behaviour_as_a_sentence>` | `test_hostile_text_is_neutralised_not_interpreted` | new |
| TypeScript variable / function | `camelCase`; type, interface and React component `PascalCase`; component file `PascalCase.tsx`; other files `camelCase.ts` | `IncidentDetail.tsx` | new |
| API field in TypeScript | stays snake_case exactly as the contract (no renaming layer), converted only inside view-model helpers | `incident.opened_at` | new |
| CSS design token | `--group-name`, kebab-case, by role not by value. Groups: `surface-`, `border-`, `text-`, `status-` (with `-surface` for its background), `accent`, `font-`, `space-`, `radius-`, `shadow-` | `--surface-raised`, `--status-bad-surface` | new, applied in the template |
| CSS class | kebab-case, block-first: `block`, `block__element`, `block--modifier`. A modifier is a fixed variant; **state and tone are data attributes**, not classes | `attention-item__severity`, `pill[data-tone="bad"]`, `stepper__step[data-state="done"]` | new, applied in the template |
| HTML data attribute | kebab-case name; value is a lower snake_case enum or a kebab-case action name. Actions are `data-action="open-incident"` plus the arguments it needs (`data-incident-id`) | `data-service-name`, `data-env-mode` | new, applied in the template |
| Icon | inline SVG from one icon set, `aria-hidden`, coloured by `currentColor`. No emoji or text glyphs as icons | `icon('lock')` | new, applied in the template |
| Inline style | never (`style=` is forbidden by the CSP and by `scan-forbidden`). Dynamic values use a data attribute or a native element (`<progress value>`) | `<progress value="44" max="100">` | frozen (security) |
| Environment variable | `CD_` + UPPER_SNAKE | `CD_PROMETHEUS_URL` | existing practice |
| Branch | `<type>/<scope>-<short-name>` | `feat/ui-redesign` | new |
| Commit | Conventional Commits, scope = area, no attribution line | `fix(backend): …` | existing practice |

## 3. Data shapes

- **Time**: RFC 3339 in UTC with a `Z` suffix on the wire and in storage. In code, an aware `datetime` in UTC. A source that sends a naive time is read as UTC and flagged `assumed_utc`.
- **Duration**: seconds as a number. **Size**: bytes as an integer. Percentages are ratios from 0 to 1 (`_ratio`), formatted only in the UI.
- **Absent is not zero**: a missing value is `null` or the key is left out. A missing series is `no_data_*`, never "healthy" and never `0`.
- **Text from a service is untrusted** (logs, errors, health details). It is stripped of NUL and control characters, capped at 8 192 characters, identified by a SHA-256 of the original, rendered only as escaped text, and never executed.
- **Unknown input is kept**: it becomes an `Unclassified` record with a preview and a hash. It is never dropped and never guessed at.

## 4. Canonical records (`backend/normalize/records.py`)

| Record | Built from | Key fields |
|---|---|---|
| `NormalizedLog` | a Loki line, a JSON object or plain text | `t`, `level`, `service`, `message`, `request_id`, `error`, `kind`, `fields`, `parse_status`, `truncated`, `raw_sha256` |
| `NormalizedMetric` | Prometheus `query` / `query_range` results or `/metrics` text | `name`, `labels`, `value`, `t`, `service`, `metric_type`, `unit` |
| `NormalizedHealth` | `/healthz`-style bodies in any common shape | `service`, `state`, `components`, `detail`, `http_status` |
| `Unclassified` | anything else | `source`, `reason`, `preview`, `raw_sha256` |

`parse_status` is `ok`, `partial` (usable, with `notes` saying what was missing or guessed), `text` (not structured) or `unparsed`. A record never claims more than was read.

`NormalizedLog.kind` is a coarse signature used by the RCA and the detector: `conn_limit`, `conn_fail`, `no_space`, `oom`, `timeout`, `other`. The most specific signature wins.

### What the normaliser accepts (all covered by `tests/backend/test_normalize.py`)

- Log keys in other spellings (`time`, `@timestamp`, `severity`, `lvl`, `levelname`, `message`, `text`, `app`, `svc`, `requestId`, `exception`) and any extra key (converted to snake_case, scalars only, at most 40).
- Levels as words (`WARNING`, `err`, `fatal`) or numbers using the pino/bunyan scheme (30 = info, 40 = warn, 50 = error).
- Times as RFC 3339 with any offset, `YYYY-MM-DD HH:MM:SS`, or epoch seconds, milliseconds, microseconds or nanoseconds.
- Health bodies such as `{"status":"alive"}`, `"OK"`, `{"ok":true}`, `{"healthy":false}`, `{"status":"UP","components":{…}}`, and a bare HTTP status when the body says nothing.
- Truncated JSON, plain text, hostile text and field floods.

## 5. Frontend template

[`docs/dev/frontend/ux-prototype.html`](frontend/ux-prototype.html) is the reference template and follows every rule above. When the screens are ported to the Next.js app, copy its token names, class names and data attributes unchanged.

- **Data in the template** uses the contract's field names (`incident_id`, `opened_at`, `top_cause`, `cause_id`, `evidence_ids`, `health_state`) and lower snake_case enum values. Only `health_state` is upper-case (`HEALTHY` …), as the frozen contract has it. Roles and permissions are lower snake_case ids (`viewer`, `decide_plans`).
- **Code in the template** is camelCase (`renderIncidentDetail`, `ui.pendingDecision`); render functions are `renderX`; one handler per `data-action` value in a single `actions` map keyed by the kebab-case name.
- **Tone mapping** is in one place (`healthTone`): `HEALTHY→ok`, `DEGRADED→warn`, `UNHEALTHY→bad`, `UNKNOWN→unknown`. A status is always shown with a shape as well as a colour.
- **Checked** by an audit of the template: 0 inline `style` attributes, 0 emoji, every class defined in the CSS and matching `block__element--modifier` in kebab-case.

## 6. Decisions and open points

1. **Two health vocabularies.** The frozen `HealthState` (`HEALTHY` …) describes a *service* after the detector has judged it. `up / degraded / down / unknown` describes one *raw health answer*. They are kept apart on purpose so a single probe never claims a verdict.
2. **Numeric log levels follow pino/bunyan.** Syslog uses different numbers; if a service ever logs syslog numbers, the mapping must be chosen per source.
3. **Adopted so far:** the Loki client reads levels through `normalize_log`. **Not yet adopted:** the evidence collector and the RCA still match raw text with their own patterns (`backend/rca/facts.py`); they should read `NormalizedLog.kind` and `fields` next. The health, metric and exposition normalisers are tested but nothing calls them yet.
4. **Frontend CSS and component names** in the current app predate these rules (`st-HEALTHY`, `tag-risk-low`). They are renamed during the UI port, not before.
5. **Service-specific shapes** (a new service with its own JSON log keys) are added by extending the alias table in `backend/normalize/logs.py`, with a test, not by special-casing downstream code.
