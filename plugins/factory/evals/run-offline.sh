#!/usr/bin/env bash
# Free, deterministic layer: no model, no auth. Static validate + all tests (incl. checks.ts chk-01/chk-02).
#   chk-02 (tests/checks-known-gaps.test.ts) is inverted with gap(): green while the gap exists, red when fixed.
set -u
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."                      # plugins/factory
echo "== claude plugin validate .";  claude plugin validate .
echo "== claude plugin test .";      claude plugin test .
