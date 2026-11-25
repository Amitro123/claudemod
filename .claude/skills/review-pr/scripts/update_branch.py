"""Bring open PR branches up to date with origin/main after another PR merged (review-pr, "After a merge").

    python3 update_branch.py <branch> [<branch> ...] [--dry-run]

For each branch, in a temporary worktree detached at origin/<branch> (the main checkout, which a running review reads,
and every local branch are never touched):
merge origin/main; resolve a conflict only in a CHANGELOG.md or plugins/inspector/evals/premerge/README.md, by
keeping both sides (the main side first); stop on a conflict anywhere else; run the suites CI runs, each judged by
its own exit code; push only when there are no conflict markers left and every suite passed. Prints one line per
branch. Exit 0 when every branch was pushed (or, with --dry-run, would be), 1 otherwise.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

DOC_CONFLICTS = re.compile(r"(^|/)CHANGELOG\.md$|^plugins/inspector/evals/premerge/README\.md$")
SUITES = [["python3", "-m", "pytest", "-q", "plugins"]]
MARK = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)


def git(*args: str, cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=check)


def keep_both(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(MARK.sub(lambda m: m[2] + m[1], text))


def update(repo: str, branch: str, dry: bool) -> bool:
    tmp = tempfile.mkdtemp(prefix="update-branch-")
    wt = os.path.join(tmp, "wt")
    try:
        # Detached at the remote branch: a dry run, a stop or a failed suite leaves no commit on any local branch.
        git("worktree", "add", "-q", "--detach", wt, f"origin/{branch}", cwd=repo)
        merged = git("merge", "-q", "--no-edit", "origin/main", cwd=wt, check=False)
        if merged.returncode:
            left = git("diff", "--name-only", "--diff-filter=U", cwd=wt).stdout.split()
            other = [p for p in left if not DOC_CONFLICTS.search(p)]
            if other or not left:
                git("merge", "--abort", cwd=wt, check=False)
                print(f"{branch}: stopped, conflict outside the changelogs and the eval table: {other or merged.stderr.strip()}")
                return False
            for p in left:
                keep_both(os.path.join(wt, p))
            git("add", *left, cwd=wt)
            git("commit", "-q", "--no-edit", cwd=wt)
        markers = git("grep", "-l", "-E", "^(<<<<<<<|>>>>>>>) ", "--", "plugins", "docs", ".claude", cwd=wt, check=False).stdout.split()
        if markers:
            print(f"{branch}: not pushed, conflict markers left in {markers}")
            return False
        for suite in SUITES:
            r = subprocess.run(suite, cwd=wt, capture_output=True, text=True, encoding="utf-8")
            if r.returncode:
                tail = (r.stdout.strip().splitlines() or [""])[-1]
                print(f"{branch}: not pushed, `{' '.join(suite)}` exited {r.returncode}: {tail}")
                return False
        head = git("rev-parse", "--short", "HEAD", cwd=wt).stdout.strip()
        if dry:
            print(f"{branch}: would push {head}")
            return True
        pushed = git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=wt, check=False)
        print(f"{branch}: {'pushed ' + head if not pushed.returncode else 'push failed: ' + pushed.stderr.strip()[:200]}")
        return not pushed.returncode
    finally:
        git("worktree", "remove", "--force", wt, cwd=repo, check=False)
        git("worktree", "prune", cwd=repo, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    branches = [a for a in argv if a != "--dry-run"]
    if not branches:
        print(__doc__)
        return 2
    repo = git("rev-parse", "--show-toplevel", cwd=os.getcwd()).stdout.strip()
    git("fetch", "-q", "origin", cwd=repo)
    results = [update(repo, b, dry) for b in branches]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
