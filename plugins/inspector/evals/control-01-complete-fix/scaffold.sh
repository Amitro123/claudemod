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
# vat
vat(cents) is the 17% VAT on an amount in whole cents, rounded down to a whole cent (integer
arithmetic only; amounts are non-negative integers).
X
mkdir -p tests
cat > vat.py <<'X'
RATE_PERCENT = 71


def vat(cents):
    return cents * RATE_PERCENT // 100
X
pr 1 vat "Add vat()" "Add vat()"
cat > vat.py <<'X'
RATE_PERCENT = 17


def vat(cents):
    return cents * RATE_PERCENT // 100
X
cat > tests/test_vat.py <<'X'
from vat import vat


def test_rate_is_17_percent():
    assert vat(10000) == 1700
    assert vat(99) == 16
X
pr 2 rate "fix: the VAT rate was typed as 71%" "fix: the VAT rate was typed as 71%"
