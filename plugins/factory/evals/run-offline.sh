#!/usr/bin/env bash
# Free, deterministic layer: no model, no auth. Static validate + all tests (incl. checks.ts chk-01/chk-02).
#   chk-02 (tests/checks-known-gaps.test.ts) pins today's behaviour for each known gap: red on the line a fix changes.
set -u
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."                      # plugins/factory
echo "== claude plugin validate .";  claude plugin validate .
echo "== claude plugin test .";      claude plugin test .
