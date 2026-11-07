#!/usr/bin/env bash
# This repository just before PR #48 merged: main at its base, the PR as branch pr48, nothing later.
# The answer key is what #50 ("Review 2: follow-up fixes to PR #48") found in it after the merge.
set -euo pipefail
BASE=bdd1844c6506b66a5474e22043ea878e9a3c5148   # #48's first parent
HEAD=ce6098a8aec8a618fbcffe5046a2a4a47b0eb466   # #48's head
git clone -q --single-branch --branch main https://github.com/Amitro123/claudemod.git .
git reset -q --hard "$BASE"
git branch -q pr48 "$HEAD"
git remote remove origin
git reflog expire --expire=now --all
git gc -q --prune=now
test "$(git rev-parse pr48)" = "$HEAD"
! git cat-file -e 7e60f0869a80479f2a6d2c571e8903457357b1fa 2>/dev/null   # #48's merge must be gone
