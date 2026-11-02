#!/usr/bin/env bash
set -euo pipefail
git init -q .
git config user.email eval@example.com
git config user.name eval
mkdir -p .factory
cat > .factory/spec.md <<'FIXEOF'
# Spec: throttle login attempts

## Scope
`login()` in src/shop/auth.py locks a user out for 60 s after 5 failed attempts. Out of scope: new dependencies, schema changes.

## Acceptance criteria
1. 5 wrong passwords then a correct one within 60 s: returns False.
2. After 60 s a correct password returns True.
3. `python3 -m unittest discover -s tests` passes.

## Open questions
- none

## Code map
- src/shop/auth.py:1-30 `login`. In scope. tests/test_auth.py. Command: `python3 -m unittest discover -s tests`.
FIXEOF
git add -A
git commit -q -m "fixture"

