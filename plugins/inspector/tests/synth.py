"""Deterministic synthetic repositories for the collector's equality test and benchmark.

Fixed author, dates and bytes (no CRLF conversion), so the same call builds the same history anywhere.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
}
_clock = [1_700_000_000]


def run(repo: Path, *args: str) -> str:
    _clock[0] += 3600
    env = {**os.environ, **ENV, "GIT_AUTHOR_DATE": f"{_clock[0]} +0000", "GIT_COMMITTER_DATE": f"{_clock[0]} +0000"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def commit(repo: Path, files: dict[str, str | None], msg: str) -> None:
    for name, text in files.items():
        p = repo / name
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", msg)


def merge_pr(repo: Path, n: int, branch: str, commits: list[tuple[dict, str]], title: str) -> None:
    run(repo, "checkout", "-q", "-b", branch)
    for files, msg in commits:
        commit(repo, files, msg)
    run(repo, "checkout", "-q", "main")
    run(repo, "merge", "-q", "--no-ff", branch, "-m", f"Merge pull request #{n} from me/{branch}\n\n{title}")


def new_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    run(path, "init", "-q", "-b", "main")
    run(path, "config", "commit.gpgsign", "false")
    run(path, "config", "core.autocrlf", "false")
    return path


SUM = "function total(items) {\n  let sum = 0;\n  for (let i = 1; i < items.length; i++) sum += items[i];\n  return sum;\n}\n"
MANIFEST = '{\n  "name": "a",\n  "version": "%s"\n}\n'


def build_small(path: Path) -> Path:
    """The test_evidence history (feature, fix, fix-of-fix, feature) plus a rename fix, a copy left
    behind, a move, a squash commit with a PR number, a direct fix commit and a Hebrew subject."""
    r = new_repo(path)
    commit(r, {"README.md": "# demo\n", "plugins/a/.claude-plugin/plugin.json": MANIFEST % "0.1.0"}, "initial")
    merge_pr(r, 1, "feat", [({"plugins/a/sum.js": SUM, "plugins/a/.claude-plugin/plugin.json": MANIFEST % "0.2.0"},
                             "Add a total helper"), ({"plugins/a/sum.js": SUM + "\n"}, "fix lint")], "a: add total")
    merge_pr(r, 2, "fix1", [({"plugins/a/sum.js": SUM.replace("let i = 1", "let i = 0").replace("items.length", "items.length ?? 0"),
                              "plugins/a/.claude-plugin/plugin.json": MANIFEST % "0.2.1"},
                             "a: total no longer skips the first item")], "a 0.2.1: fix the first item")
    merge_pr(r, 3, "fix2", [({"plugins/a/sum.js": SUM.replace("let i = 1", "let i = 0").replace("items.length", "(items || []).length"),
                              "plugins/b/use.js": "total([]);\n"}, "a: fix a crash on a missing list")], "a, b: fix the crash")
    merge_pr(r, 4, "feat2", [({"plugins/b/more.js": "export const more = 1;\n"}, "Add more")], "b: add more")
    line = "out = render(user_text, escape=False)"
    commit(r, {"src/a.py": f"def a(user_text):\n    {line}\n    return out\n",
               "src/b.py": f"def b(user_text):\n    {line}\n    return out\n",
               "src/c.py": "def c():\n    value = compute_the_total(1, 2)\n    return value\n",
               "src/old.js": "a\nb\nx = 1\nc\n"}, "Add a, b, c")
    merge_pr(r, 5, "fix", [({"src/a.py": "def a(user_text):\n    out = render(user_text, escape=True)\n    return out\n"},
                            "fix: a escapes user text")], "fix: a escapes user text")
    merge_pr(r, 6, "move", [({"src/c.py": None, "src/d.py": "def c():\n    value = compute_the_total(1, 2)\n    return value\n"},
                             "fix: move c to d")], "fix: move c to d")
    run(r, "checkout", "-q", "-b", "ren")
    run(r, "mv", "src/old.js", "src/new.js")
    (r / "src/new.js").write_bytes(b"a\nb\nx = 2\nc\n")
    run(r, "commit", "-qam", "fix the x bug")
    run(r, "checkout", "-q", "main")
    run(r, "merge", "-q", "--no-ff", "ren", "-m", "Merge pull request #7 from a/ren\n\nfix the x bug")
    commit(r, {"docs/notes.md": "one\ntwo\n"}, "Add notes (#8)")
    commit(r, {"plugins/b/more.js": "export const more = 2;\n"}, "fix: more was wrong")
    commit(r, {"plugins/b/he.js": "export const he = 1;\n"}, "תיקון: ערך שגוי")
    return r


def build_big(path: Path, prs: int = 40) -> Path:
    """A longer history for the benchmark: `prs` merged PRs over a few files, every third a fix."""
    r = build_small(path)
    body = "".join(f"line_{i} = compute({i}, 'value number {i}')\n" for i in range(60))
    commit(r, {"services/api/core.py": body, "services/web/view.py": body.replace("compute", "render")}, "Add services")
    for n in range(9, 9 + prs):
        lines = body.splitlines(True)
        k = n % 50
        lines[k] = f"line_{k} = compute({k}, 'changed in {n}')\n"
        text = "".join(lines)
        fix = n % 3 == 0
        title = f"services: fix bug number {n}" if fix else f"Add feature {n}"
        merge_pr(r, n, f"b{n}", [({"services/api/core.py": text, f"services/api/f{n}.py": f"x_{n} = {n}\n"}, title)], title)
        body = text
    return r
