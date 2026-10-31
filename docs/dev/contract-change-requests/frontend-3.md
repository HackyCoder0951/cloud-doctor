# frontend-3: SSE resume for clients that cannot send `Last-Event-ID`, and a way to learn the caller's role

## SSE resume
**Problem.** The contract says "Reconnect with Last-Event-ID". The browser's `EventSource` sends that header only for its *automatic* reconnects. When the browser gives up (for example after an HTTP error such as 503 during a restart) the application must open a new `EventSource`, which cannot set the header. `StreamEvent` also has no `id` field in its payload.

**Proposed change.** Accept an optional `last_event_id` query parameter on `GET /stream` as an equivalent of the header.

**Workaround used.** After every reconnect the UI refetches the data of the views that are open ("resync") instead of relying on replay, so correctness never depends on replay; replay only reduces refetching.

## Role discovery
**Problem.** Approve, reject and re-diagnose need role `operator`, but there is no endpoint that tells the UI the caller's role, so the UI cannot hide or disable those buttons for a `viewer`.

**Proposed change.** `GET /auth/me` returning `{role: viewer|operator|admin}` (UX only; the API keeps enforcing authorization).

**Workaround used.** The buttons are always shown to a logged-in user; a `403` is displayed as "The API refused this action (authorization or policy)" together with any pattern-valid rule ids.

## Resolution (coordinator, 2026-10-31)
**Not applied (deferred).** `last_event_id` on `/stream` and `GET /auth/me` are new endpoints and behavior that need backend implementation and tests. The dashboard already works without them (resync after reconnect; role not hidden in the UI).
