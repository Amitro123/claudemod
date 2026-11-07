#!/usr/bin/env bash
# This repository as it was at PR #50 (2026-10-28), with nothing after it: no later commit, ref,
# reflog entry or object. The answer key is what #51-#72 fixed in plugins/followups.
set -euo pipefail
AT=f3c170572de95a09aeaa7a6e58aff23c4d5317a5   # Merge pull request #50
git clone -q --single-branch --branch main https://github.com/Amitro123/claudemod.git .
git reset -q --hard "$AT"
git remote remove origin
git reflog expire --expire=now --all
git gc -q --prune=now
test "$(git rev-parse HEAD)" = "$AT"
! git cat-file -e 92974e4 2>/dev/null   # #72 must be gone
