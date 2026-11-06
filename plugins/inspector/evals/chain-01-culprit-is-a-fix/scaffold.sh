#!/usr/bin/env bash
set -euo pipefail
git init -q -b main .
git config user.email eval@example.com
git config user.name eval
git config commit.gpgsign false
git commit -q --allow-empty -m "initial"
# Merge what is in the working tree as PR #n, the way GitHub writes it.
pr() {
  git checkout -q -b "$2"; git add -A; git commit -q -m "$3"; git checkout -q main
  git merge -q --no-ff "$2" -m "Merge pull request #$1 from eval/$2" -m "$4"; git branch -q -D "$2"
}
cat > README.md <<'X'
# cart
total(items) sums the prices of a cart. An empty or missing cart (None) totals 0.
X
cat > cart.py <<'X'
def total(items):
    if not items:
        return 0
    s = 0
    for i in range(1, len(items)):
        s += items[i]
    return s
X
pr 1 total "Add total()" "Add total()"
cat > cart.py <<'X'
def total(items):
    return sum(items[i] for i in range(len(items)))
X
pr 2 first-item "fix: total() skipped the first item" "fix: total() skipped the first item"
cat > cart.py <<'X'
def total(items):
    return sum(items or [])
X
pr 3 none-cart "fix: total(None) crashes" "fix: total(None) crashes"
