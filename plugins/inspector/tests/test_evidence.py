"""Tests for evidence.py on a small repository built here.

Run: python -m pytest plugins/inspector/tests -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402


def run(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout


def commit(repo: Path, files: dict[str, str], msg: str) -> None:
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", msg)


def merge_pr(repo: Path, n: int, branch: str, files: dict[str, str], msg: str, title: str) -> None:
    run(repo, "checkout", "-q", "-b", branch)
    commit(repo, files, msg)
    run(repo, "checkout", "-q", "main")
    run(repo, "merge", "-q", "--no-ff", branch, "-m",
        f"Merge pull request #{n} from me/{branch}\n\n{title}")


PLUGIN_A = """function total(items) {
  let sum = 0;
  for (let i = 1; i < items.length; i++) sum += items[i];
  return sum;
}
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    run(r, "init", "-q", "-b", "main")
    run(r, "config", "user.email", "t@example.com")
    run(r, "config", "user.name", "T")
    run(r, "config", "commit.gpgsign", "false")
    commit(r, {"README.md": "# demo\n", "plugins/a/.claude-plugin/plugin.json":
               '{\n  "version": "0.1.0"\n}\n'}, "initial")
    # 1: a feature with an off-by-one in it
    merge_pr(r, 1, "feat", {"plugins/a/sum.js": PLUGIN_A,
                            "plugins/a/.claude-plugin/plugin.json": '{\n  "version": "0.2.0"\n}\n'},
             "Add a total helper", "a: add total")
    # 2: the fix, which brings its own bug (no guard for a missing list)
    merge_pr(r, 2, "fix1", {"plugins/a/sum.js": PLUGIN_A.replace("let i = 1", "let i = 0")
                            .replace("items.length", "items.length ?? 0"),
                            "plugins/a/.claude-plugin/plugin.json": '{\n  "version": "0.2.1"\n}\n'},
             "a: total no longer skips the first item", "a 0.2.1: fix the first item")
    # 3: a fix of the fix, touching a second component too
    merge_pr(r, 3, "fix2", {"plugins/a/sum.js": PLUGIN_A.replace("let i = 1", "let i = 0")
                            .replace("items.length", "(items || []).length"),
                            "plugins/b/use.js": "total([]);\n"},
             "a: fix a crash on a missing list", "a, b: fix the crash")
    # 4: a plain feature
    merge_pr(r, 4, "feat2", {"plugins/b/more.js": "export const more = 1;\n"},
             "Add more", "b: add more")
    return r


def test_units_are_prs_oldest_first(repo: Path) -> None:
    r = evidence.investigate(str(repo), "HEAD", None, 50, 400)
    labels = [u["unit"] for u in r["timeline"]]
    assert labels[1:] == ["#1", "#2", "#3", "#4"]
    assert r["timeline"][1]["title"] == "a: add total"
    assert not r["shallow"]


def test_fix_detection(repo: Path) -> None:
    r = evidence.investigate(str(repo), "HEAD", None, 50, 400)
    by = {u["unit"]: u for u in r["timeline"]}
    assert not by["#1"]["is_fix"]
    assert by["#2"]["is_fix"] and "patch bump 0.2.0->0.2.1" in by["#2"]["signals"]
    assert by["#3"]["is_fix"]
    assert not by["#4"]["is_fix"]


def test_blame_traces_the_culprit_and_the_chain(repo: Path) -> None:
    r = evidence.investigate(str(repo), "HEAD", None, 50, 400, min_lines=1)
    by = {u["unit"]: u for u in r["timeline"]}
    assert [e["unit"] for e in by["#2"]["introduced_by"]] == ["#1"]
    assert not by["#2"]["fix_of_fix"]
    culprits = [e["unit"] for e in by["#3"]["introduced_by"]]
    assert culprits[0] == "#2"
    assert by["#3"]["fix_of_fix"]
    assert r["fix_of_fix"] == ["#3"]
    assert r["cross_component_fixes"] == ["#3"]


def test_manifest_lines_are_not_blamed(repo: Path) -> None:
    r = evidence.investigate(str(repo), "HEAD", None, 50, 400, min_lines=1)
    by = {u["unit"]: u for u in r["timeline"]}
    for e in by["#2"]["introduced_by"]:
        assert all(not f.endswith("plugin.json") for f in e["files"])


def test_since_a_ref(repo: Path) -> None:
    second = run(repo, "rev-list", "--first-parent", "--max-count=1", "HEAD~2").strip()
    r = evidence.investigate(str(repo), "HEAD", second, 50, 400)
    assert [u["unit"] for u in r["timeline"]] == ["#3", "#4"]


def test_markdown_and_cli(repo: Path, tmp_path: Path) -> None:
    out_md, out_json = tmp_path / "e.md", tmp_path / "e.json"
    assert evidence.main(["--repo", str(repo), "--md", str(out_md), "--json", str(out_json),
                          "--min-lines", "1"]) == 0
    md = out_md.read_text()
    assert "Fix-of-fix" in md and "#3" in md and "| #2 " in md
    assert out_json.read_text().startswith("{")


def test_bad_ref_fails_cleanly(repo: Path, capsys) -> None:
    assert evidence.main(["--repo", str(repo), "--ref", "nope"]) == 1
    assert "evidence.py" in capsys.readouterr().err
