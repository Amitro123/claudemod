"""Two PRs that each add a row to the premerge eval table merge without a conflict.

CLAUDE.md has every PR add a row at the end of the table in `plugins/inspector/evals/premerge/README.md`, so any two
open PRs collided there (2026-11-25: #201 after #199, #197 after #201; resolved by hand both times by keeping both
rows). The rows are independent and order-free, so the repository's `.gitattributes` gives the file git's built-in
`union` merge. The scratch-repository test uses the repository's own attribute line, not a copy of it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TABLE = "plugins/inspector/evals/premerge/README.md"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false",
                           *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def test_the_table_has_the_union_merge_attribute() -> None:
    out = git(ROOT, "check-attr", "merge", "--", TABLE)
    assert out.strip().endswith("merge: union"), out


def test_two_appended_rows_merge_without_a_conflict(tmp_path) -> None:
    lines = [ln for ln in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines() if ln.startswith(TABLE)]
    assert lines, ".gitattributes names the table"
    (tmp_path / ".gitattributes").write_text("\n".join(lines) + "\n", encoding="utf-8")
    table = tmp_path / TABLE
    table.parent.mkdir(parents=True)
    table.write_text("| Date | Change |\n|---|---|\n| 2026-11-20 | #184 |\n", encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "pr-a")
    with table.open("a", encoding="utf-8", newline="\n") as f:
        f.write("| 2026-11-22 | #185 |\n")
    git(tmp_path, "commit", "-qam", "row a")
    git(tmp_path, "checkout", "-q", "main")
    with table.open("a", encoding="utf-8", newline="\n") as f:
        f.write("| 2026-11-22 | #196 |\n")
    git(tmp_path, "commit", "-qam", "row b")
    git(tmp_path, "merge", "-q", "--no-edit", "pr-a")   # check=True: a conflict fails here
    text = table.read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert "| 2026-11-22 | #185 |" in text and "| 2026-11-22 | #196 |" in text
