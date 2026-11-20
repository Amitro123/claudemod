"""The secret scan against the shapes a history can take and the settings a repository can have.

Each shape adds the same credential in a file of its own, in a different way: the root commit, a plain commit,
a renamed file, a two-parent merge, an octopus merge, a criss-cross merge, a conflict's resolution, odd file
names, an add then delete, and a text file `.gitattributes` marks `-diff` or `binary` (git prints "Binary files
differ" for those). Each setting is one a repository or user may have that changes what `git log -p` prints.
A file that really is binary (a NUL byte in it) is skipped in history as it is in the tree. Every shape must be found under every setting: a new shape or setting goes in the tables below.
"""
from __future__ import annotations

import os

import pytest

from test_audit import TOKEN, findings, sh  # noqa: F401  (also puts the scripts on the path)

SETTINGS = {
    "defaults": [],
    "noprefix": [("diff.noprefix", "true")],
    "mnemonic prefix": [("diff.mnemonicPrefix", "true")],
    "color always": [("color.ui", "always"), ("color.diff", "always")],
    "no root diff": [("log.showRoot", "false")],
    "copies and renames": [("diff.renames", "copies")],
    "unquoted paths": [("core.quotePath", "false")],
    "histogram": [("diff.algorithm", "histogram")],
    "external diff": [("diff.external", "false")],
    "textconv": [("diff.rev.textconv", "rev")],
    "relative": [("diff.relative", "true")],
    "context": [("diff.context", "8"), ("diff.interHunkContext", "4")],
}


def commit(r, env, msg, **files):
    for name, text in files.items():
        p = r / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    sh(r, "git", "add", "-A", env=env)
    sh(r, "git", "commit", "-qm", msg, env=env)


@pytest.fixture(scope="module")
def history(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("matrix")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    r = tmp / "r"
    sh(tmp, "git", "init", "-q", "-b", "main", str(r))
    secret = f"TOKEN={TOKEN}\n"
    # The textconv driver the "textconv" setting turns on, for these files: it would print them reversed.
    commit(r, env, "root", **{"root.txt": secret, ".gitattributes": "*.cfg diff=rev\n*.lockx -diff\n*.dat binary\n",
                              "shared.txt": "a\nb\nc\nd\n"})
    commit(r, env, "plain", **{"plain.cfg": secret})
    sh(r, "git", "mv", "plain.cfg", "moved.cfg", env=env)
    commit(r, env, "rename and add", **{"moved.cfg": secret + secret.replace("TOKEN", "OTHER")})
    # A double quote is legal in a file name on Linux and macOS, not on Windows: that shape exists only where git can hold it.
    odd = {"שם עברי.txt": secret, "with space.txt": secret, **({} if os.name == "nt" else {'q"uote.txt': secret})}
    commit(r, env, "odd names", **odd)
    # Attributes: text files git is told to diff as binary, and a real binary (NUL bytes) holding the same value.
    commit(r, env, "attributes", **{"deps.lockx": secret, "blob.dat": secret})
    (r / "real.bin").write_bytes(b"\x00\x01\x02" + secret.encode() + b"\x00")
    sh(r, "git", "add", "real.bin", env=env)
    sh(r, "git", "commit", "-qm", "a real binary", env=env)
    commit(r, env, "added", **{"gone.txt": secret})
    sh(r, "git", "rm", "-q", "gone.txt", env=env)
    sh(r, "git", "commit", "-qm", "deleted", env=env)

    # A two-parent merge that adds a line of its own.
    sh(r, "git", "checkout", "-qb", "side", env=env)
    commit(r, env, "side", **{"side.txt": "side\n"})
    sh(r, "git", "checkout", "-q", "main", env=env)
    commit(r, env, "main", **{"main.txt": "main\n"})
    sh(r, "git", "merge", "-q", "--no-ff", "--no-commit", "side", env=env)
    commit(r, env, "evil merge", **{"evil-merge.txt": secret})

    # An octopus that adds a line to a file the branches didn't touch.
    for b in ("o1", "o2", "o3"):
        sh(r, "git", "checkout", "-qb", b, "main", env=env)
        commit(r, env, b, **{f"{b}.txt": b + "\n"})
    sh(r, "git", "checkout", "-q", "main", env=env)
    sh(r, "git", "merge", "-q", "--no-commit", "o1", "o2", "o3", env=env)
    commit(r, env, "octopus", **{"shared.txt": "a\nb\nc\nd\n" + secret})

    # A conflict whose resolution brings the credential in.
    sh(r, "git", "checkout", "-qb", "c1", "main", env=env)
    commit(r, env, "c1", **{"conflict.txt": "one\n"})
    sh(r, "git", "checkout", "-qb", "c2", "main", env=env)
    commit(r, env, "c2", **{"conflict.txt": "two\n"})
    sh(r, "git", "checkout", "-q", "c1", env=env)
    subprocess_merge = __import__("subprocess").run(["git", "merge", "-q", "c2"], cwd=r, env=env, capture_output=True)
    assert subprocess_merge.returncode != 0, "the merge was meant to conflict"
    commit(r, env, "resolved", **{"conflict.txt": "one and two\n" + secret})
    sh(r, "git", "checkout", "-q", "main", env=env)
    sh(r, "git", "merge", "-q", "--no-ff", "c1", "-m", "take c1", env=env)

    # A criss-cross: two branches merge each other, then one of them adds the credential in its second merge.
    sh(r, "git", "checkout", "-qb", "x1", "main", env=env)
    commit(r, env, "x1", **{"x1.txt": "x1\n"})
    sh(r, "git", "checkout", "-qb", "x2", "main", env=env)
    commit(r, env, "x2", **{"x2.txt": "x2\n"})
    sh(r, "git", "merge", "-q", "--no-ff", "x1", "-m", "x2 takes x1", env=env)
    sh(r, "git", "checkout", "-q", "x1", env=env)
    sh(r, "git", "merge", "-q", "--no-ff", "x2~1", "-m", "x1 takes x2", env=env)
    sh(r, "git", "checkout", "-q", "x2", env=env)
    sh(r, "git", "merge", "-q", "--no-ff", "--no-commit", "x1", env=env)
    commit(r, env, "criss-cross", **{"criss.txt": secret})
    sh(r, "git", "checkout", "-q", "main", env=env)
    sh(r, "git", "merge", "-q", "--no-ff", "x2", "-m", "take x2", env=env)
    return r, env


# real.bin is not here: a file with a NUL byte is skipped in history as `scan_files` skips it in a tree.
EXPECTED = ["blob.dat", "conflict.txt", "criss.txt", "deps.lockx", "evil-merge.txt", "gone.txt", "moved.cfg",
            "plain.cfg", *([] if os.name == "nt" else ['q"uote.txt']), "root.txt", "shared.txt", "with space.txt", "שם עברי.txt"]


@pytest.mark.slow
@pytest.mark.parametrize("name", list(SETTINGS))
def test_every_shape_is_found_under_every_setting(history, name):
    r, env = history
    for key, value in SETTINGS[name]:
        sh(r, "git", "config", key, value, env=env)
    try:
        got = sorted({f["path"] for f in findings(r, "main")})
    finally:
        for key, _ in SETTINGS[name]:
            sh(r, "git", "config", "--unset", key, env=env)
    assert got == sorted(EXPECTED), f"{name}: missing {sorted(set(EXPECTED) - set(got))}, extra {sorted(set(got) - set(EXPECTED))}"
