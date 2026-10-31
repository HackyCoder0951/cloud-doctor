# harness-1: no way to associate an incident with a harness run

**What is wrong.** `incident.json` has an optional `run_id` ("Experiment run id when the incident occurred during a harness run"), but no API input
sets it: `openapi.yaml` has no call that accepts a run id, and the harness must not send ground truth or run context to the system under test.

**Proposed change.** None required if `run_id` is meant to be filled from a backend-side setting that is not ground truth. If a run correlation id is wanted, define a
neutral, opaque, harness-chosen header or endpoint (for example `X-Run-Id` on read calls, or `POST /system/run-marker`) whose value carries no fault information.

**Impact.** Backend (B): optional storage of an opaque id. Harness (F): could stop matching by time.

**Workaround used.** The harness never sends the run id. It matches incidents to a fault by time window and affected services (`harness/records.py`, `classify_events`): an incident
opened inside [t_inject, t_inject + detection_deadline] that lists an affected service is the true positive. `incident.run_id` is not read.
