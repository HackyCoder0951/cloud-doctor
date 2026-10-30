# Experiment: CPU Saturation (EXP-03)

**Status: designed, NOT executed. Results: pending.**

## Objective
Test detection of a gradual, resource-driven degradation and whether the system picks a proportionate action (scale or restart) rather than a reflexive restart.

## Hypothesis (HYPOTHESIS)
A CPU hog in `api` under a `--cpus` limit raises CPU saturation and latency before errors; the symptom detector (latency SLI) fires; ranked cause: `api CPU saturation`; a restart removes the hog only if the hog lives in the container.

## Initial State
Steady load.

## Fault Injection
Start a CPU-burning process inside the api container, ramped over time (also a step variant). Limits per Docker resource constraints [S-029].

## Expected Telemetry
CPU usage near limit / throttling, p95/p99 latency ↑ before 5xx, throughput flat or lower.

## Expected Detection / RCA
Latency SLI burn alert plus saturation warning. RCA candidates: CPU saturation (supported), downstream slowness (contradicted by healthy downstream latency), traffic spike (contradicted by flat request rate).

## Expected Remediation / Verification
Candidate actions: restart api (low), scale api (medium; approval). Verification: latency back within SLO over window, CPU below target, no error regression.

## Metrics
TTD for latency vs. saturation signals, action appropriateness, TTR.

## Results
Pending.

## Failure Cases
Traffic spike misread as saturation; restart returns the hog if injector re-launches it; scale unavailable in Compose (design limit).

## Conclusion
Pending.
