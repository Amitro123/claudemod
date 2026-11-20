"""/inspector:audit scripts: context.py on a repository with a remote, scan.py never printing a value, table.py's refusals."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import context as C  # noqa: E402
import table as TB  # noqa: E402

TOKEN = "ghp_" + "Zx" * 18  # built at runtime: no literal token in the repository
TENANT = "6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b"


def sh(cwd: Path, *args: str, env=None) -> str:
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8", env=env).stdout


def make_repo(tmp: Path) -> Path:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    bare = tmp / "remote.git"
    sh(tmp, "git", "init", "-q", "--bare", "-b", "main", str(bare))
    repo = tmp / "repo"
    sh(tmp, "git", "init", "-q", "-b", "main", str(repo))
    (repo / ".gitignore").write_text(".local/\n")
    (repo / "README.md").write_text("hello\n")
    (repo / "pipeline.yml").write_text("url: https://dev.azure.com/ContosoOrg/Proj/_apis/build\n")
    sh(repo, "git", "add", ".", env=env)
    sh(repo, "git", "commit", "-qm", "init", env=env)
    sh(repo, "git", "remote", "add", "origin", str(bare), env=env)
    sh(repo, "git", "push", "-q", "origin", "main", env=env)
    sh(repo, "git", "checkout", "-qb", "feat/local-only", env=env)
    (repo / "tests" / "fixtures").mkdir(parents=True)
    (repo / "tests" / "fixtures" / "log.txt").write_text("##[error]boom\n")
    (repo / "tests" / "test_urls.py").write_text('URL = "https://dev.azure.com/FixtureOrg/P/_apis/x"\n')
    (repo / "app.py").write_text(f'TOKEN = "{TOKEN}"\nMARK = "##[error]"\n# tenant id {TENANT}\nowner = "ops@contoso-corp.com"\nex = "a@example.com"\n')
    sh(repo, "git", "add", ".", env=env)
    sh(repo, "git", "commit", "-qm", "add app", env=env)
    (repo / ".local").mkdir()
    (repo / ".local" / "raw.log").write_text(f"tid={TENANT}\n")
    return repo


@pytest.mark.slow
def test_context_names_local_only_branches_and_strips_nothing_secret(tmp_path):
    repo = make_repo(tmp_path)
    d = C.collect(repo, "2000-01-01", 24, None, network=True, auth=False)
    assert d["default_branch"] == "main" and d["primary_remote"] == "origin"
    br = {b["name"]: b for b in d["branches"]}
    # 2 commits in the window, 1 of them the pushed base: 1 unpublished (counting the shared base was #161)
    assert br["feat/local-only"]["on_remote"] is False and br["feat/local-only"]["commits_in_window"] == 2
    assert br["feat/local-only"]["unpublished_in_window"] == 1 and br["feat/local-only"]["unpublished"] == 1
    assert br["feat/local-only"]["review"] == "unknown"
    assert br["main"]["unpublished"] == 0
    assert br["main"]["on_remote"] is True
    assert d["remote_heads"]["names"] == ["main"] and "ls-remote" in d["remote_heads"]["source"]
    assert [f["path"] for f in d["ignored_folders"]] == [".local/"]
    assert [o["org"] for o in d["azure_devops"]] == ["ContosoOrg"], "a URL in a test file is not the project's org"
    assert d["azure_devops"][0]["projects"] == ["Proj"]
    assert len(d["base_commits"]) == 1 and d["base_commits"][0]["subject"] == "init"


def test_remote_urls_lose_their_credentials_and_are_classified():
    assert C.strip_credentials("https://user:s3cret@github.com/o/r.git") == "https://github.com/o/r.git"
    gh = C.classify_remote("git@github.com:Owner/repo.git")
    assert (gh["kind"], gh["owner"], gh["repo"]) == ("github", "Owner", "repo")
    ado = C.classify_remote("https://org@dev.azure.com/Org/Proj/_git/Repo")
    assert (ado["kind"], ado["owner"], ado["project"], ado["repo"]) == ("azure-devops", "Org", "Proj", "Repo")
    ssh = C.classify_remote("git@ssh.dev.azure.com:v3/Org/Proj/Repo")
    assert (ssh["kind"], ssh["owner"], ssh["project"]) == ("azure-devops", "Org", "Proj")
    vs = C.classify_remote("https://org.visualstudio.com/Proj/_git/Repo")
    assert (vs["kind"], vs["owner"], vs["repo"]) == ("azure-devops", "org", "Repo")


def scan(repo: Path, *args: str, env_extra=None) -> tuple[str, dict]:
    env = {**os.environ, **(env_extra or {})}
    p = subprocess.run([sys.executable, str(SCRIPTS / "scan.py"), "--repo", str(repo), *args],
                       capture_output=True, text=True, env=env, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    pj = subprocess.run([sys.executable, str(SCRIPTS / "scan.py"), "--repo", str(repo), *args, "--json"],
                        capture_output=True, text=True, env=env, encoding="utf-8")
    return p.stdout + p.stderr + pj.stdout, json.loads(pj.stdout)


@pytest.mark.slow
def test_scan_finds_each_kind_and_never_prints_a_value(tmp_path):
    repo = make_repo(tmp_path)
    text, d = scan(repo, "--worktree", "--include-ignored", "--secret-env", "AUDIT_TENANT", env_extra={"AUDIT_TENANT": TENANT})
    assert TOKEN not in text and TENANT not in text and "ops@" not in text
    kinds = {(i["kind"], i["path"], i["where"]) for i in d["items"]}
    assert ("token", "app.py", "tracked") in kinds
    assert ("email", "app.py", "tracked") in kinds
    assert ("secret-env:AUDIT_TENANT", ".local/raw.log", "ignored") in kinds
    assert ("secret-env:AUDIT_TENANT", "app.py", "tracked") in kinds
    assert not any(i["kind"] == "guid-near-tenant" and i["path"] == "app.py" for i in d["items"]), "a known value is reported once, by name"
    assert d["email_domains"] == {"domain=contoso-corp.com": 1}
    logs = {i["path"]: i["class"] for i in d["items"] if i["kind"] == "raw-log"}
    assert logs == {"app.py": "code-reference", "tests/fixtures/log.txt": "test-fixture"}


@pytest.mark.slow
def test_scan_of_main_and_of_the_branch_range(tmp_path):
    repo = make_repo(tmp_path)
    _, main = scan(repo, "--ref", "main")
    assert main["findings"] == 0
    _, rng = scan(repo, "--range", "main..feat/local-only")
    tok = [i for i in rng["items"] if i["kind"] == "token"]
    assert len(tok) == 1 and tok[0]["line"] == 1 and tok[0]["where"].startswith("commit:")


def test_placeholders_are_told_apart():
    import scan as S
    assert S.classify("src/a.py", "", "set-by-the-proxy") == "placeholder"
    assert S.classify("src/a.py", "", "fake-token-123") == "placeholder"
    assert S.classify("tests/fixtures/x.json", "", "Qw8rT2zLpY") == "test-fixture"
    assert S.classify("src/a.py", "", "Qw8rT2zLpY") == "likely-real"


ROW = {"id": "c1-r1", "check": 1, "action": "deployment x at 12:36 UTC by ops@contoso-corp.com",
       "evidence": ["az deployment group list -> Succeeded"], "authorized": "no", "notes": "PR open, no review"}


def run_table(tmp: Path, rows, verdicts=None, *extra) -> tuple[int, str, str]:
    rf = tmp / "rows.json"
    rf.write_text(json.dumps(rows))
    args = [sys.executable, str(SCRIPTS / "table.py"), str(rf)]
    if verdicts is not None:
        vf = tmp / "v.json"
        vf.write_text(json.dumps(verdicts))
        args += ["--verdicts", str(vf)]
    p = subprocess.run(args + list(extra), capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout, p.stderr


@pytest.mark.parametrize("bad,why", [
    ({"evidence": []}, "no evidence"),
    ({"authorized": "probably"}, "use yes, no or unknown"),
    ({"authorized": "yes"}, "without the approval record"),
    ({"notes": f"token {TOKEN}"}, "holds a token"),
    ({"id": ""}, "no id"),
])
def test_table_refuses_rows_that_do_not_hold_up(tmp_path, bad, why):
    rc, out, err = run_table(tmp_path, [{**ROW, **bad}])
    assert rc == 2 and why in err and out == ""


def test_table_merges_verdicts_and_hides_identities(tmp_path):
    rows = [ROW, {**ROW, "id": "c1-r2", "authorized": "yes", "approval": "PR 7 approved by a reviewer"},
            {**ROW, "id": "c2-r1", "check": 2, "authorized": "unknown", "blocked": True, "notes": "403 on branch protection"}]
    verdicts = [{"id": "c1-r1", "verdict": "contradicted", "authorized": "yes", "approval": "PR 7 approved by a reviewer",
                 "evidence": ["gh pr view 7"], "why": "approved after all"},
                {"id": "c1-r2", "verdict": "unverifiable", "why": "no access"}]
    rc, out, err = run_table(tmp_path, rows, verdicts)
    assert rc == 0, err
    assert "ops@" not in out and "***@contoso-corp.com" in out
    assert "Re-check changed no to yes" in out and "Re-check could not confirm yes" in out
    assert "(not re-checked)" in out and "Could not be checked:" in out
    assert "3 rows: 1 yes, 0 no, 2 unknown; 1 re-checked with evidence by the verifier (0 confirmed, 1 contradicted), 1 it could not check." in out
    assert "PR 7 approved by a reviewer" in out
    rc, out, _ = run_table(tmp_path, rows, verdicts, "--show-identities")
    assert "ops@contoso-corp.com" in out


def test_audit_skill_names_only_files_that_exist():
    skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
    for ref in ("scripts/context.py", "scripts/scan.py", "scripts/table.py", "references/sources.md"):
        assert ref in skill and (SCRIPTS.parent / ref).exists()
    agents = SCRIPTS.parent.parent.parent / "agents"
    assert (agents / "auditor.md").exists() and (agents / "audit-verifier.md").exists()
    assert "inspector:auditor" in skill and "inspector:audit-verifier" in skill


def git_repo(tmp: Path) -> tuple[Path, dict]:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    r = tmp / "r"
    sh(tmp, "git", "init", "-q", "-b", "main", str(r))
    (r / "a.txt").write_text("base\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "base", env=env)
    return r, env


def findings(repo: Path, rng: str) -> list[dict]:
    p = subprocess.run([sys.executable, str(SCRIPTS / "scan.py"), "--repo", str(repo), "--range", rng, "--json"],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    assert TOKEN not in p.stdout
    return [i for i in json.loads(p.stdout)["items"] if i["kind"] == "token"]


@pytest.mark.slow
def test_a_credential_added_only_by_a_merge_is_found_after_it_was_deleted(tmp_path):
    r, env = git_repo(tmp_path)
    base = sh(r, "git", "rev-parse", "HEAD").strip()
    sh(r, "git", "checkout", "-qb", "side", env=env)
    (r / "side.txt").write_text("side\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "side", env=env)
    sh(r, "git", "checkout", "-q", "main", env=env)
    (r / "main.txt").write_text("main\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "main", env=env)
    sh(r, "git", "merge", "--no-commit", "--no-ff", "-q", "side", env=env)
    (r / ".env").write_text(f"TOKEN={TOKEN}\n")
    sh(r, "git", "add", ".env", env=env)
    sh(r, "git", "commit", "-qm", "merge side", env=env)
    merge = sh(r, "git", "rev-parse", "HEAD").strip()
    (r / ".env").unlink()
    sh(r, "git", "commit", "-qam", "remove env", env=env)
    got = findings(r, f"{base}..HEAD")
    assert [(f["path"], f["where"]) for f in got] == [(".env", f"commit:{merge[:12]}")]


@pytest.mark.slow
def test_a_credential_added_by_an_octopus_merge_is_found_and_only_the_merge_line(tmp_path):
    r, env = git_repo(tmp_path)
    base = sh(r, "git", "rev-parse", "HEAD").strip()
    (r / "shared.txt").write_text("l1\nl2\nl3\nl4\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "shared", env=env)
    for b, f in (("b1", "one.txt"), ("b2", "two.txt"), ("b3", "three.txt")):
        sh(r, "git", "checkout", "-qb", b, "main", env=env)
        (r / f).write_text(f"{b}\n")
        sh(r, "git", "add", ".", env=env)
        sh(r, "git", "commit", "-qm", b, env=env)
    sh(r, "git", "checkout", "-q", "main", env=env)
    sh(r, "git", "merge", "--no-commit", "-q", "b1", "b2", "b3", env=env)
    (r / "shared.txt").write_text(f"l1\nl2\nl3\nl4\nTOKEN={TOKEN}\n")
    sh(r, "git", "add", "shared.txt", env=env)
    sh(r, "git", "commit", "-qm", "octopus", env=env)
    merge = sh(r, "git", "rev-parse", "HEAD").strip()
    assert len(sh(r, "git", "rev-list", "--parents", "-n1", "HEAD").split()) == 4
    got = findings(r, f"{base}..HEAD")
    assert [(f["path"], f["where"], f.get("line")) for f in got] == [("shared.txt", f"commit:{merge[:12]}", 5)]


def test_the_repositorys_diff_settings_dont_hide_a_credential(tmp_path):
    r, env = git_repo(tmp_path)
    base = sh(r, "git", "rev-parse", "HEAD").strip()
    (r / "conf.txt").write_text(f"TOKEN={TOKEN}\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "conf", env=env)
    for key, value in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("diff.external", "false")):
        sh(r, "git", "config", key, value, env=env)
    got = findings(r, f"{base}..HEAD")
    assert [f["path"] for f in got] == ["conf.txt"]


def test_a_side_branch_add_and_delete_is_found_and_a_clean_merge_stays_clean(tmp_path):
    r, env = git_repo(tmp_path)
    base = sh(r, "git", "rev-parse", "HEAD").strip()
    sh(r, "git", "checkout", "-qb", "side", env=env)
    (r / "k.txt").write_text(f"{TOKEN}\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "add", env=env)
    added = sh(r, "git", "rev-parse", "HEAD").strip()
    (r / "k.txt").unlink()
    sh(r, "git", "commit", "-qam", "del", env=env)
    sh(r, "git", "checkout", "-q", "main", env=env)
    (r / "m.txt").write_text("m\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "m", env=env)
    sh(r, "git", "merge", "--no-ff", "-q", "-m", "merge", "side", env=env)
    got = findings(r, f"{base}..HEAD")
    assert [(f["path"], f["where"]) for f in got] == [("k.txt", f"commit:{added[:12]}")], "once, at the side commit, not again at the merge"


# A double quote and a tab are legal in a file name on Linux and macOS, not on Windows: those names run only where they can exist.
NOT_ON_WINDOWS = pytest.mark.skipif(os.name == "nt", reason="Windows forbids this character in a file name")


@pytest.mark.slow
@pytest.mark.parametrize("name", ["נתונים.txt", "with space.txt", pytest.param('quo"te.txt', marks=NOT_ON_WINDOWS),
                                  pytest.param("tab\there.txt", marks=NOT_ON_WINDOWS)])
def test_file_names_git_quotes_are_scanned_with_their_real_name(tmp_path, name):
    r, env = git_repo(tmp_path)
    (r / name).write_text(f"x\nTOKEN={TOKEN}\n")
    sh(r, "git", "add", "-A", env=env)
    sh(r, "git", "commit", "-qm", "add", env=env)
    (r / name).unlink()
    sh(r, "git", "commit", "-qam", "del", env=env)
    got = findings(r, "HEAD~2..HEAD")
    assert [(f["path"], f["line"]) for f in got] == [(name, 2)]


def test_git_quoted_paths_decode():
    import scan as S
    assert S.unquote_path(r'"b/\327\240\327\252.txt"') == "b/נת.txt"
    assert S.unquote_path(r'"b/tab\there"') == "b/tab\there"
    assert S.unquote_path(r'"b/quo\"te"') == 'b/quo"te'
    assert S.unquote_path("b/with space.txt\t") == "b/with space.txt"
    assert S.unquote_path("b/plain.txt") == "b/plain.txt"


@pytest.mark.slow
def test_an_added_line_starting_with_plus_plus_is_content_not_a_file_name(tmp_path):
    r, env = git_repo(tmp_path)
    (r / "notes.md").write_text(f"++ heading\nTOKEN={TOKEN}\n")
    sh(r, "git", "add", ".", env=env)
    sh(r, "git", "commit", "-qm", "add", env=env)
    assert [(f["path"], f["line"]) for f in findings(r, "HEAD~1..HEAD")] == [("notes.md", 2)]


NO_ROW = {"id": "r1", "check": 1, "action": "deploy", "evidence": ["deployment record"], "authorized": "no"}


@pytest.mark.parametrize("verdicts,why", [
    ([{"id": "r1", "verdict": "confirmed"}], "confirmed needs the verifier's own evidence"),
    ([{"id": "r1", "verdict": "banana", "evidence": ["x"]}], "use confirmed, contradicted or unverifiable"),
    ([{"id": "r1", "verdict": "contradicted", "authorized": "yes", "evidence": ["query"], "why": "ok"}], "without the approval record"),
    ([{"id": "r9", "verdict": "confirmed", "evidence": ["x"]}], "no row has this id"),
    ([{"id": "r1", "verdict": "confirmed", "evidence": ["x"]}, {"id": "r1", "verdict": "unverifiable"}], "a second verdict for the same row"),
    ([{"id": "r1", "verdict": "contradicted", "evidence": ["x"]}], "needs the authorized value"),
])
def test_verdicts_are_held_to_the_rows_rules(tmp_path, verdicts, why):
    rc, out, err = run_table(tmp_path, [NO_ROW], verdicts)
    assert rc == 2 and why in err and out == ""
    rc, out, err = run_table(tmp_path, [NO_ROW], verdicts, "--json")
    assert rc == 2 and out == ""


def test_a_no_to_yes_correction_with_an_approval_record_goes_through(tmp_path):
    v = [{"id": "r1", "verdict": "contradicted", "authorized": "yes", "approval": "ADO approval 4411 by the release owner",
          "evidence": ["az rest .../approvals -> approved"], "why": "approved in ADO"}]
    rc, out, err = run_table(tmp_path, [NO_ROW], v, "--json")
    row = json.loads(out)[0]
    assert rc == 0 and row["authorized"] == "yes" and row["approval"].startswith("ADO approval") and row["checked"] == "contradicted"


def test_an_unverifiable_verdict_leaves_unknown_and_is_not_counted_as_checked(tmp_path):
    rc, out, err = run_table(tmp_path, [NO_ROW], [{"id": "r1", "verdict": "unverifiable", "why": "no access"}])
    assert rc == 0 and "| unknown (re-check could not settle it) |" in out
    assert "0 re-checked with evidence by the verifier (0 confirmed, 0 contradicted), 1 it could not check." in out


@pytest.mark.slow
def test_a_local_alias_of_published_commits_has_nothing_unpublished(tmp_path):
    repo = make_repo(tmp_path)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    sh(repo, "git", "fetch", "-q", "origin", env=env)
    sh(repo, "git", "branch", "--no-track", "local-alias", "origin/main", env=env)
    d = C.collect(repo, "2000-01-01", 24, None, network=True, auth=False)
    br = {b["name"]: b for b in d["branches"]}
    assert br["local-alias"]["on_remote"] is False and br["local-alias"]["unpublished"] == 0
    assert br["local-alias"]["commits_in_window"] == 1 and br["local-alias"]["unpublished_in_window"] == 0
    sh(repo, "git", "checkout", "-q", "local-alias", env=env)
    (repo / "x.txt").write_text("x\n")
    sh(repo, "git", "add", "x.txt", env=env)
    sh(repo, "git", "commit", "-qm", "one local commit", env=env)
    br = {b["name"]: b for b in C.collect(repo, "2000-01-01", 24, None, network=True, auth=False)["branches"]}
    assert br["local-alias"]["unpublished"] == 1
    assert not any("has no pull request" in n for n in C.collect(repo, None, 24, None, network=False, auth=False)["notes"])


@pytest.mark.slow
def test_a_renamed_branch_tracking_a_remote_branch_is_on_the_remote(tmp_path):
    repo = make_repo(tmp_path)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    sh(repo, "git", "push", "-q", "-u", "origin", "feat/local-only:feat/published-as", env=env)
    d = C.collect(repo, None, 24, None, network=True, auth=False)
    b = {x["name"]: x for x in d["branches"]}["feat/local-only"]
    assert b["name_on_remote"] is False and b["upstream_on_remote"] is True and b["on_remote"] is True and b["unpublished"] == 0
