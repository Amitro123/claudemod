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
# draft
draft(command) writes a shell command into MISTAKES.md, a tracked file. **No secret in the command
(a password or token passed as a flag) may reach the file.**
X
mkdir -p tests
cat > draft.py <<'X'
def draft(command):
    return f"- Command: `{command}`"
X
pr 1 draft "Add draft()" "Add draft()"
cat > draft.py <<'X'
import re

SECRET = re.compile(r"(--?(?:password|token)=)\S+")


def draft(command):
    safe = SECRET.sub(r"\1[redacted]", command)
    return f"- Command: `{safe}`"
X
cat > tests/test_draft.py <<'X'
from draft import draft


def test_password_is_redacted():
    assert "hunter2" not in draft("mysql --password=hunter2 db")
X
pr 2 redact "fix: redact --password=value in drafted commands" "fix: redact secrets in drafted commands"

