"""Trivial baseline detector, reported next to Cloud Doctor's detector (evaluation-framework.md).

BASELINE, NOT A PRODUCT FEATURE: a fixed threshold on the error_ratio the API reports per service, evaluated on
the samples the runner recorded. An episode starts at the first sample at or above the threshold and ends at the
first sample below it. Each episode is one detection event, scored exactly like an incident (per fault, no
point-adjust). It can only see error_ratio, so it is expected to miss latency-only and queue-only faults.
"""
from __future__ import annotations

from harness.records import DetectionEvent, RunRecord

DEFAULT_THRESHOLD = 0.05
DESCRIPTION = (f"fixed threshold error_ratio >= {DEFAULT_THRESHOLD} on any service reported by GET /services, "
               "one event per contiguous breach episode (baseline for comparison)")


def baseline_events(rec: RunRecord, threshold: float = DEFAULT_THRESHOLD) -> list[DetectionEvent]:
    events: list[DetectionEvent] = []
    current: tuple | None = None  # (start, set of services)
    for s in rec.samples:
        breaching = {n for n, v in s.services.items()
                     if isinstance(v.get("error_ratio"), (int, float)) and v["error_ratio"] >= threshold}
        if breaching:
            if current is None:
                current = (s.t, set(breaching))
            else:
                current[1].update(breaching)
        elif current is not None:
            events.append(DetectionEvent(current[0], frozenset(current[1]), f"baseline@{current[0].isoformat()}"))
            current = None
    if current is not None:
        events.append(DetectionEvent(current[0], frozenset(current[1]), f"baseline@{current[0].isoformat()}"))
    return events
