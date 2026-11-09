#!/usr/bin/env bash
# Run both deterministic checks; either failure must fail the wrapper.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
status=0
echo "== claude plugin validate ."
claude plugin validate . || status=1
echo "== pytest tests"
python3 -m pytest tests -q -p no:cacheprovider || status=1
exit "$status"
