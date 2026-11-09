"""Precision fixes: patch bump is no fix signal, removal units carry no culprits, copies-left-behind
ignore imports/comments/descriptions, and --path is repeatable. Tiny synthetic repositories."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
import evidence  # noqa: E402
import snapshot  # noqa: E402
from synth import commit, merge_pr, new_repo  # noqa: E402

BUMP = ["plugins/a/.claude-plugin/plugin.json: 0.2.0->0.2.1"]


def unit(title: str, commits: list[str], bumps=None) -> evidence.Unit:
    u = evidence.Unit("a" * 40, "pr", 7, title, "2026-01-01", "b" * 40, version_bumps=list(bumps or []))
    u.commits = [{"sha": f"{i:040x}", "subject": s, "parent": "b" * 40} for i, s in enumerate(commits)]
    u.files = [{"path": "plugins/a/x.js", "ins": 3, "del": 1}]
    return u


# ---- 1. a patch version bump is not a fix signal ------------------------------------------------

@pytest.mark.parametrize("title,commits", [
    ("a 0.2.1: release", ["a: tweak the toast"]),
    ("Bump version", ["bump a to 0.2.1"]),
    ("a: update docs and bump", ["update docs", "bump"]),
])
def test_patch_bump_alone_is_not_a_fix(title, commits):
    u = unit(title, commits, BUMP)
    evidence.judge(u)
    assert not u.is_fix and "patch version bump" not in u.why
    assert u.version_bumps == BUMP            # still recorded as a fact


def test_real_fix_evidence_still_counts_with_a_bump():
    u = unit("a 0.2.1: fix the first item", ["a: total skips the first item"], BUMP)
    evidence.judge(u)
    assert u.is_fix and u.why[0].startswith("title:")
    u = unit("a 0.2.1: release", ["fix: crash on empty list", "fix: wrong total", "bump a to 0.2.1"], BUMP)
    evidence.judge(u)
    assert u.is_fix and "commits say fix" in u.why[0]


# ---- 2. removal-dominant units ----------------------------------------------------------------

BODY = "".join(f"step {i}: do the thing {i}\n" for i in range(40))


@pytest.fixture(scope="module")
def removal_repo(tmp_path_factory):
    r = new_repo(tmp_path_factory.mktemp("removal") / "r")
    commit(r, {"README.md": "# demo\n", "skills/x/SKILL.md": BODY, "src/keep.py": "def keep():\n    return 1\n"}, "initial")
    merge_pr(r, 1, "rm", [({"skills/x/SKILL.md": None}, "fix: remove the broken x skill")], "fix: remove the broken x skill")
    merge_pr(r, 2, "fix", [({"src/keep.py": "def keep():\n    return 2\n"}, "fix: keep returns 2")], "fix: keep returns 2")
    return r


def test_removal_threshold_is_a_named_constant():
    assert evidence.REMOVAL_RATIO > 1 and evidence.REMOVAL_MIN_DELETED > 0


def test_removal_unit_gets_a_verdict_and_no_culprits(removal_repo):
    ev = evidence.investigate(str(removal_repo))
    by = {u["unit"]: u for u in ev["timeline"]}
    assert by["#1"]["verdict"] == "removal" and "removal" in by["#1"]["tags"]
    assert by["#1"]["introduced_by"] == [] and not by["#1"]["fix_of_fix"]
    assert all("introduced_by" not in c for c in by["#1"]["commits"])
    assert "#1" not in ev["fix_of_fix"]
    assert "verdict" not in by["#2"] and by["#2"]["introduced_by"]       # a normal fix keeps its culprit


# ---- 3. copies left behind ignore imports, comments and descriptions ---------------------------

LINE = "out = render(user_text, escape=False)"


def test_left_behind_ignores_imports_comments_and_descriptions(tmp_path):
    r = new_repo(tmp_path / "r")
    commit(r, {"a.py": f"def a(user_text):\n    {LINE}\n    return out\n",
               "b.py": f"def b(user_text):\n    {LINE}\n    return out\n",
               "c.py": f"# {LINE}\n",
               "d.js": f"// {LINE}\nconst x = require('{LINE}')\n",
               "e.py": f"from {LINE} import z\n",
               "SKILL.md": f'---\ndescription: use when {LINE} appears\nwhen_to_use: "{LINE}"\n---\n'}, "Add files")
    merge_pr(r, 1, "fix", [({"a.py": "def a(user_text):\n    out = render(user_text, escape=True)\n    return out\n"},
                            "fix: a escapes user text")], "fix: a escapes user text")
    ev = evidence.investigate(str(r))
    assert [(x["unit"], x["at"]) for x in ev["left_behind"]] == [("#1", ["b.py:2"])]
    ignored = sorted(at for x in ev["ignored_matches"] for at in x["at"])
    assert ignored == ["SKILL.md:2", "SKILL.md:3", "c.py:1", "d.js:1", "d.js:2", "e.py:1"]
    assert all(x["unit"] == "#1" and x["line"] == LINE for x in ev["ignored_matches"])


def test_no_ignored_matches_key_when_nothing_was_ignored(tmp_path):
    r = new_repo(tmp_path / "r")
    commit(r, {"a.py": f"def a(user_text):\n    {LINE}\n    return out\n"}, "Add a")
    merge_pr(r, 1, "fix", [({"a.py": "def a(user_text):\n    out = render(user_text, escape=True)\n    return out\n"},
                            "fix: a escapes")], "fix: a escapes")
    assert "ignored_matches" not in evidence.investigate(str(r))


# ---- 4. --path is repeatable --------------------------------------------------------------------

@pytest.fixture(scope="module")
def multi_repo(tmp_path_factory):
    r = new_repo(tmp_path_factory.mktemp("multi") / "r")
    commit(r, {"README.md": "# demo\n"}, "initial")
    for n, d in enumerate(("plugins/a", "plugins/b", "src"), 1):
        merge_pr(r, n, f"f{n}", [({f"{d}/m.py": f"def m():\n    return {n}\n"}, f"fix: {d} m")], f"fix: {d} m")
    return r


def units_of(ev):
    return [u["unit"] for u in ev["timeline"]]


def test_single_path_is_unchanged(multi_repo):
    ev = evidence.investigate(str(multi_repo), path="plugins/a")
    assert units_of(ev) == ["#1"] and ev["path"] == "plugins/a" and ev["snapshot"]["options"]["path"] == "plugins/a"
    assert evidence.investigate(str(multi_repo), path=["plugins/a"])["path"] == "plugins/a"


def test_repeated_paths_union_and_are_recorded(multi_repo):
    ev = evidence.investigate(str(multi_repo), path=["plugins/a/", "src"])
    assert units_of(ev) == ["#1", "#3"]
    assert ev["path"] == ["plugins/a/", "src"] == ev["snapshot"]["options"]["path"]
    assert "path plugins/a/, src" in evidence.markdown(ev)


def test_cli_repeats_path_and_help_says_so(multi_repo, tmp_path, capsys):
    out = tmp_path / "ev.json"
    args = ["--repo", str(multi_repo), "--path", "plugins/a", "--path", "plugins/b", "--json", str(out),
            "--md", str(tmp_path / "ev.md"), "--budget", "1"]
    assert evidence.main(args) == 0
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert units_of(ev) == ["#1", "#2"] and ev["path"] == ["plugins/a", "plugins/b"]
    capsys.readouterr()
    assert evidence.main(["--show", "#2", "--json", str(out)]) == 0     # provenance/fingerprint validates
    with pytest.raises(SystemExit):
        evidence.main(["--help"])
    assert "--path a/ --path b/" in " ".join(capsys.readouterr().out.split())


def test_validation_compares_the_whole_path_set(multi_repo):
    ev = evidence.investigate(str(multi_repo), path=["plugins/a", "src"])
    snapshot.validate(ev, expected_scope={"path": ["plugins/a", "src"]})
    with pytest.raises(ValueError, match="Requested path differs"):
        snapshot.validate(ev, expected_scope={"path": ["plugins/a"]})
    assert snapshot.scope_path(["plugins/a"]) == "plugins/a" and snapshot.scope_path([]) is None
