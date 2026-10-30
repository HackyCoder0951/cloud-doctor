# frontend-2: where the `/api/v1` prefix lives (backend routes vs. reverse proxy)

**What is unclear.** `servers: [{url: /api/v1}]` says the API is reachable under `/api/v1`, but not whether the Python app mounts its routes under `/api/v1` or the reverse proxy strips the prefix.

**Proposed change.** State in `openapi.yaml` (or `docs/10-architecture/api-architecture.md`) that the backend itself serves `/api/v1/...` and the reverse proxy forwards the URI unchanged.

**Impact.** Backend (route prefix), infra/nginx (proxy_pass form).

**Workaround used.** `infra/nginx/cloud-doctor.conf` uses `proxy_pass http://cd_api;` (no URI part), which forwards `/api/v1/...` unchanged, and the static checker enforces that form. If the backend serves routes at the root instead, change that single line to `proxy_pass http://cd_api/;` and update `scripts/check-nginx.mjs`.
