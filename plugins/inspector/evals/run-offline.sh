#!/usr/bin/env bash
# Free, deterministic layer: no model, no auth. Validate the plugin and run the collector's tests,
# the golden test against this repository's own history included (it needs the full history).
set -u
cd "$(dirname "$0")/.."                      # plugins/inspector
echo "== claude plugin validate ."; claude plugin validate .
echo "== pytest tests";             python3 -m pytest tests -q -p no:cacheprovider
