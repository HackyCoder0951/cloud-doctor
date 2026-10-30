#!/usr/bin/env bash
# Gate G1 check: contracts valid and sandbox telemetry matches contracts/telemetry.md.
# Requires a running sandbox (make up). Exit 0 only if everything passes.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
python3 tests/contract/validate_contracts.py || exit 1
infra/scripts/smoke_test.sh || exit 1
echo "G1 PASS (spike outcomes S1-S7 are a separate, manual condition)"
