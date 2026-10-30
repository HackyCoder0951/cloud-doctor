# harness/ — Stream F (branch stream/harness)

Fault injector, run protocol, ground-truth recording and evaluation metrics. Never imported by the backend; ground truth is invisible to detection and RCA.
Status, commands, assumptions and gaps: `docs/dev/harness/STATUS.md`.

```bash
python3 -m pytest tests/harness -q          # no Docker, no network, no LLM
python3 -m harness validate-scenarios
python3 -m harness check-recoverability
python3 -m harness report                   # writes experiments/results/<date>/
```
