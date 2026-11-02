#!/usr/bin/env bash
set -euo pipefail
git init -q .
git config user.email eval@example.com
git config user.name eval
mkdir -p .factory
cat > .factory/spec.md <<'FIXEOF'
# Spec: --json flag for `list`

## Problem
`shop list` prints text only; scripts need JSON.

## Scope
Add `--json` to the `list` command. Out of scope: CSV, pagination, accounts, any other command, README roadmap items.

## Design
- `src/shop/cli.py`: `main(argv)` accepts `list --json` and prints `json.dumps(ITEMS)`-style output (a JSON array of objects with id, name, price).
- Without the flag the output and exit code are unchanged.
- Failure mode: an unknown flag after `list` prints the usage line and returns 2.

## Acceptance criteria
1. `cli.main(["list", "--json"])` returns 0 and prints a JSON array whose first element has id 1, name "pen" and price 2.5 (test: json.loads of stdout).
2. `cli.main(["list"])` output is unchanged (existing test `test_list_prints_items` still passes).
3. `cli.main(["list", "--bogus"])` returns 2.
4. `python3 -m unittest discover -s tests` passes.

## Open questions
- Should price be a JSON number or a string like "2.50"? Assumed: number (2.5), the stored value; say how you settled it.

## Code map
- src/shop/cli.py:1-15 `list_items()` text lines, `main(argv)` dispatch. In scope.
- src/shop/store.py:1-7 `ITEMS` list of dicts {id, name, price}. Read only.
- tests/test_cli.py:1-17 `ListTest`. Extend here.
- Copies of the list logic elsewhere: none (searched `list_items`).
- Test command: `python3 -m unittest discover -s tests`.
FIXEOF
git add -A
git commit -q -m "fixture"

