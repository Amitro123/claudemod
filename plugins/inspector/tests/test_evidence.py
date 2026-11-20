"""Tests for evidence.py on small repositories built here.

Run: python -m pytest plugins/inspector/tests -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402


def run(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def commit(repo: Path, files: dict[str, str | None], msg: str) -> None:
    for name, text in files.items():
        p = repo / name
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", msg)


def merge_pr(repo: Path, n: int, branch: str, commits: list[tuple[dict, str]], title: str) -> None:
    run(repo, "checkout", "-q", "-b", branch)
    for files, msg in commits:
        commit(repo, files, msg)
    run(repo, "checkout", "-q", "main")
    run(repo, "merge", "-q", "--no-ff", branch, "-m", f"Merge pull request #{n} from me/{branch}\n\n{title}")


def new_repo(path: Path) -> Path:
    path.mkdir()
    run(path, "init", "-q", "-b", "main")
    run(path, "config", "user.email", "t@example.com")
    run(path, "config", "user.name", "T")
    run(path, "config", "commit.gpgsign", "false")
    return path


SUM = """function total(items) {
  let sum = 0;
  for (let i = 1; i < items.length; i++) sum += items[i];
  return sum;
}
"""
MANIFEST = '{\n  "name": "a",\n  "version": "%s"\n}\n'


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    """Built once per module: the tests read it (the default-out test only adds a folder under .git)."""
    r = new_repo(tmp_path_factory.mktemp("evrepo") / "repo")
    commit(r, {"README.md": "# demo\n", "plugins/a/.claude-plugin/plugin.json": MANIFEST % "0.1.0"}, "initial")
    # 1: a feature with an off-by-one in it; its PR also has a housekeeping "fix lint" commit
    merge_pr(r, 1, "feat", [({"plugins/a/sum.js": SUM, "plugins/a/.claude-plugin/plugin.json": MANIFEST % "0.2.0"},
                             "Add a total helper"),
                            ({"plugins/a/sum.js": SUM + "\n"}, "fix lint")], "a: add total")
    # 2: the fix, which brings its own bug (no guard for a missing list)
    merge_pr(r, 2, "fix1", [({"plugins/a/sum.js": SUM.replace("let i = 1", "let i = 0").replace("items.length", "items.length ?? 0"),
                              "plugins/a/.claude-plugin/plugin.json": MANIFEST % "0.2.1"},
                             "a: total no longer skips the first item")], "a 0.2.1: fix the first item")
    # 3: a fix of the fix, touching a second component too
    merge_pr(r, 3, "fix2", [({"plugins/a/sum.js": SUM.replace("let i = 1", "let i = 0").replace("items.length", "(items || []).length"),
                              "plugins/b/use.js": "total([]);\n"}, "a: fix a crash on a missing list")],
             "a, b: fix the crash")
    # 4: a plain feature
    merge_pr(r, 4, "feat2", [({"plugins/b/more.js": "export const more = 1;\n"}, "Add more")], "b: add more")
    return r


_RUNS: dict = {}


def inv(repo: Path, **kw) -> dict:
    """evidence.investigate on the shared repo, once per distinct set of arguments: tests share a run
    where they ask the same question. Results are only read."""
    key = (str(repo), tuple(sorted(kw.items())))
    if key not in _RUNS:
        _RUNS[key] = evidence.investigate(str(repo), **kw)
    return _RUNS[key]


def by_unit(r: dict) -> dict:
    return {u["unit"]: u for u in r["timeline"]}


def test_units_are_prs_oldest_first(repo: Path) -> None:
    r = inv(repo)
    assert [u["unit"] for u in r["timeline"]][1:] == ["#1", "#2", "#3", "#4"]
    assert r["timeline"][1]["title"] == "a: add total"
    assert r["timeline"][2]["base"]
    assert not r["shallow"] and not r["truncated"] and r["warnings"] == []


def test_fix_detection(repo: Path) -> None:
    by = by_unit(inv(repo))
    assert not by["#1"]["is_fix"], "a feature PR with a 'fix lint' commit is not a fix"
    assert by["#2"]["is_fix"]
    assert by["#3"]["is_fix"]
    assert not by["#4"]["is_fix"]
    assert by["#2"]["version_bumps"] == ["plugins/a/.claude-plugin/plugin.json: 0.2.0->0.2.1"]


@pytest.mark.parametrize("subject,is_fix", [
    ("fix: a crash on empty input", True),
    ("goal-run 0.4.1: the toast no longer shows twice", False),       # weak words alone
    ("Add a bug marker to the pane", False),                         # bug as a noun
    ("Add export, fix the README wording", False),                   # starts as a feature
    ("followups: fix blank pane, harden export, add tests", True),   # "add tests" inside a fix
    ("fix lint", False), ("Address review comments", False),
    ("factory 0.16.0: run review findings L1, L2", True),
    ("factory 0.18.0: what the first real run found", False),       # weak alone
    ("factory 0.18.0: fixes from what the first real run found", True),
    ("Revert \"Add caching\"", True),
    ("inspector 0.2.0: a bug detective for the history, its evals, and 14 open bugs it found on main", False),
    ("followups: 3 bugs found by the inspector", False),            # reports bugs, fixes none
    ("fix 3 bugs found in review", True),
    ("found and fixed two bugs in the export", True),
])
def test_subject_verdict(subject: str, is_fix: bool) -> None:
    assert evidence.subject_verdict(subject)[0] is is_fix


def test_blame_traces_the_culprit_and_the_chain(repo: Path) -> None:
    r = inv(repo, min_lines=1)
    by = by_unit(r)
    assert [e["unit"] for e in by["#2"]["introduced_by"]] == ["#1"]
    assert not by["#2"]["fix_of_fix"]
    assert by["#3"]["introduced_by"][0]["unit"] == "#2"
    assert by["#3"]["fix_of_fix"]
    assert by["#3"]["commits"][0]["introduced_by"][0]["unit"] == "#2", "blame is kept per commit too"
    assert r["fix_of_fix"] == ["#3"]
    assert r["multi_component_fixes"] == ["#3"]


def test_manifest_and_readme_lines_are_not_blamed(repo: Path) -> None:
    by = by_unit(inv(repo, min_lines=1))
    for e in by["#2"]["introduced_by"]:
        assert all(not f.endswith(("plugin.json", "README.md")) for f in e["files"])


def test_since_keeps_attribution_beyond_the_window(repo: Path) -> None:
    second = run(repo, "rev-list", "--first-parent", "--max-count=1", "HEAD~2").strip()
    r = inv(repo, since=second, min_lines=1)
    assert [u["unit"] for u in r["timeline"]] == ["#3", "#4"]
    assert r["fix_of_fix"] == ["#3"], "#2 is before the work window but still known as a fix"


def test_unit_and_path_scopes(repo: Path) -> None:
    r = inv(repo, unit="#3", min_lines=1)
    assert [u["unit"] for u in r["timeline"]] == ["#3"] and r["fix_of_fix"] == ["#3"]
    inner = by_unit(inv(repo))["#3"]["commits"][0]["sha"]
    assert [u["unit"] for u in inv(repo, unit=inner)["timeline"]] == ["#3"]
    assert [u["unit"] for u in inv(repo, path="plugins/b")["timeline"]] == ["#3", "#4"]
    with pytest.raises(RuntimeError):
        inv(repo, unit="#99")


def test_truncation_is_warned(repo: Path) -> None:
    r = inv(repo, limit=2)
    assert r["truncated"] and any("--max 2" in w for w in r["warnings"])


def test_a_rename_keeps_its_culprit(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"src/old.js": "a\nb\nx = 1\nc\n"}, "initial")
    run(r, "checkout", "-q", "-b", "f")
    run(r, "mv", "src/old.js", "src/new.js")
    (r / "src/new.js").write_text("a\nb\nx = 2\nc\n")
    run(r, "commit", "-qam", "fix the x bug")
    run(r, "checkout", "-q", "main")
    run(r, "merge", "-q", "--no-ff", "f", "-m", "Merge pull request #1 from a/f\n\nfix the x bug")
    u = by_unit(evidence.investigate(str(r), min_lines=1))["#1"]
    assert u["is_fix"] and u["introduced_by"] and u["introduced_by"][0]["files"] == ["src/old.js"]


def test_an_octopus_merge_keeps_every_branch(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"x.js": "1\n"}, "initial")
    for b, f in (("b1", "y.js"), ("b2", "z.js")):
        run(r, "checkout", "-q", "-b", b, "main")
        commit(r, {f: "1\n"}, f"fix the {f} bug")
    run(r, "checkout", "-q", "main")
    run(r, "merge", "-q", "--no-ff", "b1", "b2", "-m", "Merge branches b1 and b2")
    u = evidence.investigate(str(r))["timeline"][-1]
    assert sorted(c["subject"] for c in u["commits"]) == ["fix the y.js bug", "fix the z.js bug"]


def test_instruction_markdown_is_blamed(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"skills/s/SKILL.md": "Always ask.\nRun the tests.\nNever push.\n", "README.md": "x\ny\nz\n"},
           "Add the skill")
    commit(r, {"skills/s/SKILL.md": "Always ask.\nRun the tests twice.\nNever push.\n", "README.md": "x\nY\nz\n"},
           "fix: the skill ran the tests once")
    r2 = evidence.investigate(str(r), min_lines=1)
    u = r2["timeline"][-1]
    assert u["introduced_by"] and u["introduced_by"][0]["files"] == ["skills/s/SKILL.md"]
    assert "instructions-only" in u["tags"], "the README is not code: among code, only the skill changed"
    assert dict(r2["hotspot_files"]) == {"skills/s/SKILL.md": 1}


def test_shallow_boundary_is_not_judged(tmp_path: Path, repo: Path) -> None:
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "2", f"file://{repo}", str(clone)], check=True)
    r = evidence.investigate(str(clone))
    assert r["shallow"] and any("shallow" in w for w in r["warnings"])
    first = r["timeline"][0]
    assert "shallow-boundary" in first["tags"] and not first["is_fix"] and first["files"] == []


def test_markdown_cli_show_and_nested_output(repo: Path, tmp_path: Path) -> None:
    out_md, out_json = tmp_path / "a" / "b" / "e.md", tmp_path / "a" / "e.json"
    assert evidence.main(["--repo", str(repo), "--md", str(out_md), "--json", str(out_json), "--min-lines", "1"]) == 0
    md = out_md.read_text()
    assert "Fix-of-fix" in md and "#3" in md and "| #2 " in md
    assert json.loads(out_json.read_text())["fixes"] == 2
    assert evidence.main(["--show", "#3", "--json", str(out_json)]) == 0


def test_bad_ref_fails_cleanly(repo: Path, capsys) -> None:
    assert evidence.main(["--repo", str(repo), "--ref", "nope"]) == 1
    assert "evidence.py" in capsys.readouterr().err


def test_left_behind_finds_a_copy_and_skips_a_move(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    line = "out = render(user_text, escape=False)"
    commit(r, {"a.py": f"def a(user_text):\n    {line}\n    return out\n",
               "b.py": f"def b(user_text):\n    {line}\n    return out\n",
               "c.py": "def c():\n    value = compute_the_total(1, 2)\n    return value\n"}, "Add a, b, c")
    merge_pr(r, 1, "fix", [({"a.py": "def a(user_text):\n    out = render(user_text, escape=True)\n    return out\n"},
                            "fix: a escapes user text")], "fix: a escapes user text")
    # a move: the same line deleted from c.py and added to d.py
    merge_pr(r, 2, "move", [({"c.py": None, "d.py": "def c():\n    value = compute_the_total(1, 2)\n    return value\n"},
                             "fix: move c to d")], "fix: move c to d")
    ev = evidence.investigate(str(r))
    assert [(x["unit"], x["at"]) for x in ev["left_behind"]] == [("#1", ["b.py:2"])]


def test_show_prints_a_dossier(repo: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "ev"
    assert evidence.main(["--repo", str(repo), "--out", str(out), "--min-lines", "1"]) == 0
    capsys.readouterr()
    assert evidence.main(["--show", "#3", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "culprit: #2" in text and "```diff" in text and "Culprit #2, on the same files" in text


def test_default_out_is_a_new_folder(repo: Path, capsys) -> None:
    assert evidence.main(["--repo", str(repo)]) == 0
    saved = capsys.readouterr().out.strip().splitlines()[-1]
    assert saved.startswith("Saved: ") and Path(saved.split()[1].rstrip(".")).exists()
    assert "/.inspector-run/" in saved.replace("\\", "/"), "the default folder is inside the working directory, where an agent's Write needs no approval"
    assert run(repo, "status", "--porcelain") == "", "and git never lists it"
    assert (repo / ".inspector-run" / ".gitignore").read_text() == "*\n"


def test_default_out_falls_back_to_git_dir_then_temp(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "blocked")
    (r / ".inspector-run").write_text("a file, so the folder cannot be made")
    p = Path(evidence.default_out(str(r)))
    assert p.parent == (r / ".git" / "inspector") and p.is_dir()
    assert Path(evidence.default_out(str(tmp_path / "not-a-repo-at-all"))).name.startswith("inspector-")


def test_out_flag_overrides_the_default(repo: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "chosen"
    assert evidence.main(["--repo", str(repo), "--out", str(out), "--min-lines", "1"]) == 0
    text = capsys.readouterr().out
    assert f"Saved: {out / 'evidence.json'}" in text and (out / "plan" / "plan.md").exists()
    assert ".inspector-run" not in text.splitlines()[-1]


def test_summary_ends_with_the_run_plan_pointer(repo: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "ev-plan"
    assert evidence.main(["--repo", str(repo), "--out", str(out), "--min-lines", "1"]) == 0
    lines = capsys.readouterr().out.rstrip("\n").splitlines()
    assert lines[-1].startswith("Saved: "), "the Saved line stays last"
    pointer = lines[-3]
    assert pointer.startswith("RUN PLAN: ") and pointer.endswith("/plan/plan.md: read it now and execute phase 1; do not skip phases")
    assert (out / "plan" / "plan.md").is_file() and (out / "plan" / "expect.json").is_file()
    assert "Read " in (out / "plan" / "plan.md").read_text(encoding="utf-8")


def test_no_plan_pointer_when_nothing_is_saved(repo: Path, capsys, monkeypatch) -> None:
    def no_write(*a, **k):
        raise OSError("Read-only file system")
    monkeypatch.setattr(evidence, "default_out", no_write)
    assert evidence.main(["--repo", str(repo), "--min-lines", "1"]) == 0
    out = capsys.readouterr().out
    assert "RUN PLAN: " not in out and "/plan/plan.md" not in out     # no pointer to a file; the plan itself is printed inline


def test_a_plan_failure_never_breaks_the_collector(repo: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    def boom(*a, **k):
        raise evidence.plan.Invalid("synthetic")
    monkeypatch.setattr(evidence.plan, "build", boom)
    assert evidence.main(["--repo", str(repo), "--out", str(tmp_path / "ev-boom"), "--min-lines", "1"]) == 0
    out = capsys.readouterr().out
    assert "RUN PLAN: not written (synthetic)" in out and out.rstrip().splitlines()[-1].startswith("Saved: ")


def test_triage_writes_dossiers_in_order(repo: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "ev"
    assert evidence.main(["--repo", str(repo), "--out", str(out), "--min-lines", "1", "--budget", "2"]) == 0
    text = capsys.readouterr().out
    assert "Cases to work, in order" in text and text.index("Cases to work") < text.index("Units in the work window")
    files = sorted(p.name for p in (out / "cases").iterdir())
    assert files[0] == "01-3.md", "the fix-of-fix comes first"
    assert len(files) == 2


def test_dossier_needs_no_saved_run(repo: Path, capsys) -> None:
    assert evidence.main(["--repo", str(repo), "--unit", "#3", "--dossier", "--min-lines", "1"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("# #3 ") and "culprit: #2" in text and "Culprit #2, on the same files" in text


def test_read_only_repository_still_reports(repo: Path, capsys, monkeypatch) -> None:
    def no_write(*a, **k):
        raise OSError("Read-only file system")
    monkeypatch.setattr(evidence, "default_out", no_write)
    assert evidence.main(["--repo", str(repo), "--min-lines", "1"]) == 0
    out = capsys.readouterr().out
    assert "Cases to work, in order" in out and "--dossier" in out and "nothing saved" in out


def test_dossier_handles_root_culprit(tmp_path: Path) -> None:
    r = new_repo(tmp_path / 'root-culprit')
    commit(r, {'a.py': 'value = 123456789\n'}, 'Initial helper')
    commit(r, {'a.py': 'value = 987654321\n'}, 'fix: wrong value')
    ev = evidence.investigate(str(r))
    text = evidence.dossier(str(r), ev['timeline'][-1], ev['unit_shas'])
    assert 'Culprit ' in text and '+value = 123456789' in text


def test_cli_fallback_is_pinned_and_shell_quoted(repo: Path, tmp_path: Path, capsys) -> None:
    import shlex
    head = run(repo, 'rev-parse', 'HEAD').strip()
    assert evidence.main(['--repo', str(repo), '--out', str(tmp_path / 'saved'), '--budget', '1']) == 0
    out = capsys.readouterr().out
    command = out.split('(or `', 1)[1].split('`)', 1)[0]
    args = shlex.split(command)
    assert args[args.index('--ref') + 1] == head
    assert args[args.index('--unit') + 1].startswith('#')
    saved = json.loads((tmp_path / 'saved' / 'evidence.json').read_text())
    assert saved['ref'] == saved['ref_sha'] == head


def test_with_nothing_saved_the_plan_is_printed_inline_and_names_the_agent_to_start(repo: Path, capsys, monkeypatch) -> None:
    """A sandbox that lets no command write: 'nothing saved' alone left the main conversation to work the cases itself."""
    def no_write(*a, **k):
        raise OSError("Read-only file system")
    monkeypatch.setattr(evidence, "default_out", no_write)
    assert evidence.main(["--repo", str(repo), "--min-lines", "1"]) == 0
    out = capsys.readouterr().out
    plan_text = out.split("nothing saved", 1)[1]
    assert "RUN PLAN (inline: no folder could be written)" in plan_text
    assert "Start ONE agent of type inspector:investigator" in plan_text and "do none of their work" in plan_text
    assert plan_text.count("--dossier") >= 1 and "write no file" in plan_text
    assert "inspector:verifier" in plan_text and "verification was skipped" in plan_text
    assert "/plan/plan.md" not in out                      # no pointer to a file that does not exist


def test_a_temporary_run_folder_gets_the_pointer_and_the_inline_plan(repo: Path, capsys, monkeypatch, tmp_path) -> None:
    """Each command of a sandbox may have its own /tmp: the next command cannot read the plan this one saved there."""
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(evidence, "default_out", lambda repo: tempfile.mkdtemp(prefix="inspector-"))
    assert evidence.main(["--repo", str(repo), "--min-lines", "1"]) == 0
    out = capsys.readouterr().out
    assert "The run folder is a temporary one" in out and "Check once: `ls " in out
    assert out.index("/plan/plan.md: read it now") < out.index("RUN PLAN (inline: for when that folder cannot be read)")
    assert "inspector:investigator" in out and "Saved: " in out


def test_a_run_folder_in_the_working_tree_gets_only_the_pointer(repo: Path, capsys, tmp_path) -> None:
    assert evidence.main(["--repo", str(repo), "--min-lines", "1", "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "/plan/plan.md: read it now" in out and "RUN PLAN (inline" not in out and "temporary one" not in out


def test_seven_or_more_cases_inline_plan_starts_case_readers() -> None:
    cmds = [(f"#{i}", f"evidence.py --unit '#{i}' --dossier") for i in range(1, 9)]
    text = evidence.inline_plan("/r", "a" * 40, cmds, "no folder could be written")
    assert "Start 3 agents of type inspector:case-reader" in text and "inspector:investigator" not in text
    assert text.count("--dossier") == 8 and "inspector:sweeper" in text and "inspector:verifier" in text


def test_only_a_json_path_still_ends_with_a_plan(repo: Path, capsys, tmp_path) -> None:
    """--json or --md without a run folder saved the evidence and printed no plan of either kind."""
    assert evidence.main(["--repo", str(repo), "--min-lines", "1", "--json", str(tmp_path / "e.json")]) == 0
    out = capsys.readouterr().out
    assert "RUN PLAN (inline: no run folder: only --json or --md was given)" in out and "inspector:investigator" in out
    assert out.rstrip().splitlines()[-1].startswith("Saved: ") and "3. Verify" in out


def test_a_plan_that_cannot_be_written_is_printed_inline(repo: Path, capsys, monkeypatch, tmp_path) -> None:
    def broken(run_dir):
        raise evidence.plan.Invalid("no cases/ folder")
    monkeypatch.setattr(evidence.plan, "build", broken)
    assert evidence.main(["--repo", str(repo), "--min-lines", "1", "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "RUN PLAN: not written" in out and "RUN PLAN (inline: the plan file could not be written)" in out
    assert out.rstrip().splitlines()[-1].startswith("Saved: ")
