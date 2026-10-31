# frontend-1: report and diagnosis availability for incidents that have no diagnosis yet

**What is incomplete.** `GET /incidents/{incident}/report` documents only `200` (JSON or Markdown), and `report.json` *requires* a `diagnosis`. A freshly detected incident has no diagnosis (`getDiagnosis` documents a `404` for that case), so the contract does not say what the report endpoint returns for it.

**Proposed change.** Document `404` (with the standard `Error` body) on `getReport` for incidents without a diagnosis, mirroring `getDiagnosis`; alternatively make `report.diagnosis` optional.

**Impact.** Backend: one more documented status. Frontend: none beyond what is already implemented. Harness: if it reads reports it must handle `404`.

**Workaround used.** The UI treats `404` on the report as "no report yet" and shows a neutral message; the mock returns `404` for such incidents (INC-0004). Every other non-2xx is shown as a generic, status-derived message.

## Resolution (coordinator, 2026-10-31)
**Applied.** `getReport` documents `404` (`contracts/openapi.yaml`); frontend API types regenerated.
