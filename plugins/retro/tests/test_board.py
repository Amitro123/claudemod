"""retro board: the shared fact file, its refusals, parallel writers, and what agent-audit measures from it."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "skills" / "board" / "scripts"
sys.path.insert(0, str(BOARD))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_retro import Writer  # noqa: E402  (also puts distill/ and agent-audit/ scripts on the path)
import agents as A  # noqa: E402
import board as B  # noqa: E402
import transcript as T  # noqa: E402

TOKEN = "ghp_" + "Kp" * 18


def test_add_confirm_supersede_and_history(tmp_path):
    f = tmp_path / "board.jsonl"
    assert B.add(f, "azure.resource_group", "rg-a", "check-1", "az group list -> 1")[0] == "added"
    assert B.add(f, "azure.resource_group", "rg-a", "check-2", "az group show")[0] == "confirmed"
    what, rec = B.add(f, "azure.resource_group", "rg-b", "check-2", "az group show -> rg-b")
    assert what == "superseded" and rec["supersedes"] == 1
    assert [r["value"] for r in B.get(f, "azure.*", "main")] == ["rg-b"]
    assert [r["value"] for r in B.get(f, "azure.resource_group", "main", history=True)] == ["rg-a", "rg-b"]


def _lines(f: Path) -> list[dict]:
    return [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]


def _write(f: Path, recs: list[dict]) -> None:
    f.write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_same_value_add_appends_a_confirm(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.branch.x.on_remote", "false", "check-1", "git ls-remote --heads origin")
    what, rec = B.add(f, "git.branch.x.on_remote", "false", "check-2", "ev2")
    assert what == "confirmed"
    assert rec["type"] == "confirm" and rec["fact"] == 1 and rec["by"] == "check-2" and rec["evidence"] == "ev2"
    assert rec["id"] == 2 and rec["key"] == "git.branch.x.on_remote" and rec["value"] == "false" and rec["level"] == "read"
    assert rec["ts"]
    recs = _lines(f)
    assert len(recs) == 2 and [r["type"] for r in recs].count("fact") == 1


def test_last_confirmed_and_confirm_counts(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "1", "w", "e")
    B.add(f, "a.c", "2", "w", "e")
    recs = _lines(f)
    recs[0]["ts"] = recs[1]["ts"] = "2026-11-19T09:00:00+00:00"
    _write(f, recs)
    _, conf = B.add(f, "a.b", "1", "w2", "e2")
    got = {r["key"]: r for r in B.get(f, None, "t")}
    assert got["a.b"]["last_confirmed"] == conf["ts"] and got["a.b"]["confirms"] == 1
    assert got["a.c"]["last_confirmed"] == got["a.c"]["ts"] and got["a.c"]["confirms"] == 0


def test_a_malformed_confirm_ts_is_skipped(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "1", "w", "e")
    _, conf = B.add(f, "a.b", "1", "w2", "e2")
    recs = _lines(f)
    recs[1]["ts"] = "not a time"
    _write(f, recs)
    r = B.get(f, "a.b", "t")[0]
    assert r["last_confirmed"] == r["ts"] and r["confirms"] == 1


def test_confirms_do_not_carry_over_to_a_superseding_fact(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "v1", "w", "e")
    B.add(f, "a.b", "v1", "w", "e")
    B.add(f, "a.b", "v2", "w", "e")
    cur = B.get(f, "a.b", "t")[0]
    assert cur["value"] == "v2" and cur["confirms"] == 0 and cur["last_confirmed"] == cur["ts"]
    hist = {r["value"]: r for r in B.get(f, "a.b", "t", history=True)}
    assert hist["v1"]["confirms"] == 1 and hist["v2"]["confirms"] == 0


def test_a_confirm_with_a_secret_is_refused(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "x", "w", "e")
    with pytest.raises(ValueError, match="evidence looks like"):
        B.add(f, "a.b", "x", "w", f"cat .env -> {TOKEN}")
    with pytest.raises(ValueError, match="key or --by"):
        B.add(f, "a.b", "x", TOKEN, "e")
    assert '"type": "confirm"' not in f.read_text()


def test_a_confirm_under_the_windows_lock_writes_nothing(tmp_path, monkeypatch):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "x", "w", "e")
    before = f.read_bytes()
    monkeypatch.setitem(sys.modules, "msvcrt", _AlwaysLocked)
    monkeypatch.setattr(B.os, "name", "nt")
    monkeypatch.setattr(B, "LOCK_WAIT_S", 0.2)
    with pytest.raises(TimeoutError, match="nothing was written"):
        B.add(f, "a.b", "x", "w2", "e2")
    assert f.read_bytes() == before


def _aged(f: Path, ages_min: dict[str, float]) -> None:
    recs = _lines(f)
    now = B._utcnow()
    for r in recs:
        if r.get("key") in ages_min and r["type"] == "fact":
            r["ts"] = (now - B.timedelta(minutes=ages_min[r["key"]])).isoformat(timespec="seconds")
    _write(f, recs)


def test_get_max_age_keeps_recent_facts_and_recently_confirmed_ones(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.branch.a.on_remote", "true", "w", "git ls-remote")
    B.add(f, "git.branch.b.on_remote", "false", "w", "git ls-remote")
    _aged(f, {"git.branch.a.on_remote": 10, "git.branch.b.on_remote": 120})
    assert [r["key"] for r in B.get(f, None, "t", max_age=30)] == ["git.branch.a.on_remote"]
    assert len(B.get(f, None, "t")) == 2, "without --max-age nothing is filtered"
    B.add(f, "git.branch.b.on_remote", "false", "w2", "git ls-remote again")
    assert sorted(r["key"] for r in B.get(f, None, "t", max_age=30)) == ["git.branch.a.on_remote", "git.branch.b.on_remote"]


def test_get_max_age_bound_is_inclusive_and_uses_one_clock(tmp_path, monkeypatch):
    f = tmp_path / "b.jsonl"
    _write(f, [{"type": "fact", "id": 1, "key": "a.b", "value": "1", "by": "w", "evidence": "e", "level": "read",
                "ts": "2026-11-19T11:30:00+00:00", "supersedes": None},
               {"type": "fact", "id": 2, "key": "a.c", "value": "1", "by": "w", "evidence": "e", "level": "read",
                "ts": "garbage", "supersedes": None}])
    monkeypatch.setattr(B, "_utcnow", lambda: B.datetime(2026, 11, 19, 12, 0, tzinfo=B.timezone.utc))
    assert [r["key"] for r in B.get(f, None, "t", max_age=30)] == ["a.b"], "malformed ts is excluded"
    assert B.get(f, None, "t", max_age=29.9) == []


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_get_max_age_must_be_a_positive_number(tmp_path, bad):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "1", "w", "e")
    with pytest.raises(ValueError, match="--max-age"):
        B.get(f, None, "t", max_age=bad)
    assert '"type": "read"' not in f.read_text()


def test_the_read_log_records_max_age(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "1", "w", "e")
    B.add(f, "a.c", "1", "w", "e")
    _aged(f, {"a.c": 120})
    got = B.get(f, None, "t", max_age=30)
    B.get(f, None, "u")
    reads = [r for r in _lines(f) if r["type"] == "read"]
    assert reads[0]["max_age"] == 30 and reads[0]["keys"] == [r["key"] for r in got] == ["a.b"]
    assert "max_age" not in reads[1]
    assert B.get(f, "a.c", "t", max_age=30) == []
    assert [r for r in _lines(f) if r["type"] == "read"][-1]["keys"] == [], "an empty read is still logged"


def test_load_board_ignores_confirm_records(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "a.b", "1", "w", "e")
    B.add(f, "a.b", "1", "w2", "e2")
    B.get(f, None, "t")
    assert [r["type"] for r in A.load_board(str(f))] == ["fact"]


@pytest.mark.parametrize("key,value,evidence,why", [
    ("Azure.RG", "x", "e", "lowercase"),
    ("a.b", "two\nlines", "e", "one line"),
    ("a.b", "x" * 501, "e", "at most 500"),
    ("a.b", TOKEN, "e", "looks like a secret"),
    ("a.b", "Bearer abcdefghijklmnopqrstuvwx", "e", "looks like a secret"),
    ("a.b", "x", "  ", "evidence"),
    ("a.b", "x", f"cat .env -> {TOKEN}", "evidence looks like"),
])
def test_refusals(tmp_path, key, value, evidence, why):
    with pytest.raises(ValueError, match=why):
        B.add(tmp_path / "b.jsonl", key, value, "a", evidence)
    assert not (tmp_path / "b.jsonl").exists() or "fact" not in (tmp_path / "b.jsonl").read_text()


def test_the_same_attribute_under_another_namespace_is_refused(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.default_branch", "main", "main", "git symbolic-ref")
    with pytest.raises(B.DuplicateKey, match=r"git\.default_branch = main \(by main\).*--new-key"):
        B.add(f, "repo.default_branch", "main", "check-1", "git branch -r")
    assert [r["key"] for r in B.get(f, None, "t")] == ["git.default_branch"]
    _, rec = B.add(f, "repo.default_branch", "main", "check-1", "git branch -r", new_key=True)
    assert rec["similar_keys"] == ["git.default_branch"]


def test_entities_with_different_names_are_different_facts(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.branch.a.on_remote", "true", "c", "git ls-remote")
    B.add(f, "git.branch.b.on_remote", "false", "c", "git ls-remote")
    B.add(f, "tool.gh.installed", "true", "c", "which gh")
    B.add(f, "tool.az.installed", "false", "c", "which az")
    assert len(B.get(f, None, "t")) == 4


def test_show_names_two_keys_for_one_fact_and_keys_lists_them(tmp_path, capsys):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.default_branch", "main", "main", "git symbolic-ref")
    B.add(f, "repo.default_branch", "main", "c", "git branch -r", new_key=True)
    B.add(f, "git.branch.a.on_remote", "true", "c", "git ls-remote")
    B.main(["--board", str(f), "show"])
    out = capsys.readouterr().out
    assert "same fact, two keys: git.default_branch, repo.default_branch" in out and "on_remote," not in out
    B.main(["--board", str(f), "keys"])
    assert capsys.readouterr().out.splitlines() == ["git.branch.a.on_remote = true", "git.default_branch = main", "repo.default_branch = main"]


def test_two_things_with_the_same_attribute_are_both_written(tmp_path, capsys):
    f = tmp_path / "b.jsonl"
    B.add(f, "gh.version", "2.60", "c", "gh --version")
    B.add(f, "az.version", "2.67", "c", "az version")
    assert len(B.get(f, None, "t")) == 2
    B.main(["--board", str(f), "show"])
    assert "same attribute, different values" in capsys.readouterr().out


def test_seed_keys_do_not_collide_and_take_any_remote_name(tmp_path):
    ctx = {"repo": {"root": "/r"}, "remotes": [{"name": "Upstream", "url": "https://github.com/o/r", "kind": "github"}],
           "branches": [{"name": "feat/x", "on_remote": True}, {"name": "feat-x", "on_remote": False}, {"name": "release/1.2", "on_remote": True}],
           "worktrees": [{"path": "/r", "branch": "main"}, {"path": "/r/.factory/a/app", "branch": "f1"}, {"path": "/r/other/app", "branch": "f2"}]}
    keys = {k: v for k, v, _ in B.flatten_context(ctx)}
    assert keys["git.branch.feat/x.on_remote"] == "true" and keys["git.branch.feat-x.on_remote"] == "false"
    assert keys["git.branch.release/1.2.on_remote"] == "true"
    assert [k for k in keys if k.startswith("remote.upstream:")] and not any(k.startswith("remote.upstream.") for k in keys)
    assert len({B.slug(n) for n in ("release/1.2", "release/1_2", "Feat", "feat", "feat/x", "feat-x")}) == 6
    assert keys["git.worktree.root.branch"] == "main"
    assert keys["git.worktree.factory/a/app.branch"] == "f1" and keys["git.worktree.other/app.branch"] == "f2"
    f = tmp_path / "b.jsonl"
    for k, v, ev in B.flatten_context(ctx):
        B.add(f, k, v, "main", ev)
    assert len(B.get(f, None, "t")) == len(keys)


def test_a_fact_written_in_the_second_the_agent_started_is_known(tmp_path):
    path, board = board_session(tmp_path, verifier_reads_first=False, brief_has_board=True)
    sess = T.load(path)
    aud = [x for x in sess.agents if x.agent_id == "aud"][0]
    facts = A.load_board(str(board))
    facts[0]["ts"] = aud.launched
    r = A.audit_run(aud, tmp_path, {"board_in_use": True, "board_facts": facts})
    assert r["board"]["reran_known"] == ["azure.resource_group"]


def test_cli_refusal_names_the_existing_key(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.default_branch", "main", "main", "git symbolic-ref")
    p = subprocess.run([sys.executable, str(BOARD / "board.py"), "--board", str(f), "add", "repo.default_branch", "main",
                        "--by", "x", "--evidence", "e"], capture_output=True, text=True)
    assert p.returncode == 2 and "git.default_branch = main" in p.stderr


ADO_SHAPE = "abcdefghij" * 5 + "kl"  # 52 lowercase letters: the shape of an Azure DevOps PAT


def test_a_secret_in_the_key_or_the_writer_is_refused(tmp_path):
    f = tmp_path / "b.jsonl"
    with pytest.raises(ValueError, match="key or --by"):
        B.add(f, f"ado.pat.{ADO_SHAPE}", "x", "a", "e")
    with pytest.raises(ValueError, match="key or --by"):
        B.add(f, "a.b", "x", TOKEN, "e")
    with pytest.raises(ValueError, match="--by"):
        B.add(f, "a.b", "x", "  ", "e")
    with pytest.raises(ValueError, match="pattern"):
        B.get(f, None, TOKEN)
    assert not f.exists() or '"type": "fact"' not in f.read_text()


class _AlwaysLocked:
    LK_NBLCK, LK_UNLCK = 2, 0
    calls: list = []

    @classmethod
    def locking(cls, fd, mode, n):
        cls.calls.append(mode)
        if mode == cls.LK_NBLCK:
            raise OSError("locked by another writer")


def test_windows_lock_gives_up_with_an_error_not_an_unlocked_write(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "msvcrt", _AlwaysLocked)
    monkeypatch.setattr(B.os, "name", "nt")
    monkeypatch.setattr(B, "LOCK_WAIT_S", 0.2)
    f = tmp_path / "b.jsonl"
    with pytest.raises(TimeoutError, match="nothing was written"):
        B.add(f, "a.b", "x", "w", "e")
    assert f.read_text() == "" and _AlwaysLocked.LK_UNLCK not in _AlwaysLocked.calls


def test_min_level_and_reads_are_logged(tmp_path):
    f = tmp_path / "b.jsonl"
    B.add(f, "git.branch.x.on_remote", "false", "check-2", "git ls-remote --heads origin", "read")
    B.add(f, "approval.pr.7", "approved", "check-2", "commit message says so", "claimed")
    assert [r["key"] for r in B.get(f, None, "verifier", min_level="read")] == ["git.branch.x.on_remote"]
    reads = [json.loads(ln) for ln in f.read_text().splitlines() if '"read"' in ln and '"type": "read"' in ln]
    assert reads[-1]["by"] == "verifier" and reads[-1]["keys"] == ["git.branch.x.on_remote"]


def _writer(args):
    path, who, n = args
    for i in range(n):
        B.add(Path(path), f"p.{who}.{i}", "v", who, "e")
    assert B.add(Path(path), f"p.{who}.0", "v", who, "checked again")[0] == "confirmed"
    return n + 1


def test_parallel_writers_lose_nothing(tmp_path):
    f = tmp_path / "b.jsonl"
    with ProcessPoolExecutor(max_workers=6) as ex:
        assert sum(ex.map(_writer, [(str(f), f"w{k}", 10) for k in range(6)])) == 66
    recs = [json.loads(ln) for ln in f.read_text().splitlines()]
    ids = [r["id"] for r in recs]
    assert len(recs) == 66 and len(set(ids)) == 66 and sorted(ids) == list(range(1, 67))
    assert sum(r["type"] == "confirm" for r in recs) == 6


def test_seed_from_audit_context(tmp_path, capsys):
    ctx = {"window": {"now": "2026-11-19T12:00:00+00:00", "since": "2026-11-16"}, "repo": {"root": "/r"},
           "remotes": [{"name": "origin", "url": "https://github.com/o/r", "kind": "github", "owner": "o", "repo": "r"}],
           "default_branch": "main", "base_ref": "origin/main", "base_commits": [{}, {}],
           "remote_heads": {"count": 3, "source": "git ls-remote (live)"},
           "branches": [{"name": "feat/X", "on_remote": False, "commits_in_window": 2}],
           "worktrees": [{"path": "/r", "branch": "main"}], "tools": {"az": True}, "signed_in": {"gh": True, "az": None},
           "azure_devops": [{"org": "Contoso", "projects": ["P"], "files": ["pipe.yml"]}]}
    (tmp_path / "c.json").write_text(json.dumps(ctx))
    f = tmp_path / "b.jsonl"
    assert B.main(["--board", str(f), "seed", "--from", str(tmp_path / "c.json")]) == 0
    facts = {r["key"]: r["value"] for r in B.get(f, None, "t")}
    branch = [k for k in facts if k.startswith("git.branch.feat/x:") and k.endswith(".on_remote")]
    assert len(branch) == 1 and facts[branch[0]] == "false" and facts["git.base_commits_in_window"] == "2"
    assert facts["ado.org.contoso"] == "P" and facts["tool.gh.signed_in"] == "true" and "tool.az.signed_in" not in facts
    capsys.readouterr()
    assert B.main(["--board", str(f), "seed", "--from", str(tmp_path / "c.json")]) == 0
    out = capsys.readouterr().out
    assert f"{len(facts)} confirmed" in out and "exists" not in out and "added" not in out
    assert len(B.get(f, None, "t", history=True)) == len(facts), "seeding twice adds no fact"
    assert sum(1 for ln in f.read_text().splitlines() if '"type": "confirm"' in ln) == len(facts)


def test_cli_uses_agent_board_env_and_exit_codes(tmp_path):
    env = {"AGENT_BOARD": str(tmp_path / "b.jsonl"), "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, str(BOARD / "board.py"), *a], capture_output=True, text=True, env=env)
    assert run("add", "a.b", "1", "--by", "x", "--evidence", "e").returncode == 0
    bad = run("add", "a.c", TOKEN, "--by", "x", "--evidence", "e")
    assert bad.returncode == 2 and TOKEN not in bad.stdout + bad.stderr
    again = run("add", "a.b", "1", "--by", "z", "--evidence", "checked again")
    assert again.returncode == 0 and again.stdout.strip() == "confirmed: a.b = 1 (fact #1)"
    got = run("get", "a.*", "--by", "y").stdout
    assert "a.b = 1    [" in got and "written " in got and "last confirmed" in got
    shown = run("show").stdout
    assert "read by: y 1" in shown and "last confirmed" in shown and "1 confirms" in shown and "(1x)" in shown
    js = json.loads(run("get", "a.b", "--by", "y", "--json").stdout)
    assert js[0]["confirms"] == 1 and js[0]["last_confirmed"]
    assert "a.b = 1" in run("get", "a.*", "--by", "y", "--max-age", "30").stdout
    n_reads = Path(env["AGENT_BOARD"]).read_text().count('"type": "read"')
    for bad in ("0", "-5", "nan"):
        p = run("get", "--by", "x", "--max-age", bad)
        assert p.returncode == 2 and "refused:" in p.stderr and "Traceback" not in p.stderr
    assert run("get", "--by", "x", "--max-age", "abc").returncode == 2
    p = run("get", "--by", TOKEN)
    assert p.returncode == 2 and "refused:" in p.stderr and "Traceback" not in p.stderr
    assert Path(env["AGENT_BOARD"]).read_text().count('"type": "read"') == n_reads


def test_audit_skill_carries_an_identical_copy():
    copy = ROOT.parent / "inspector" / "skills" / "audit" / "scripts" / "board.py"
    assert copy.read_bytes() == (BOARD / "board.py").read_bytes(), "copy plugins/retro/skills/board/scripts/board.py over it"


def board_session(tmp: Path, verifier_reads_first: bool, brief_has_board: bool) -> tuple[Path, Path]:
    board = tmp / "board.jsonl"
    B.add(board, "azure.resource_group", "rg-a", "main", "az group list --query [].name -> rg-a")
    rec = json.loads(board.read_text().splitlines()[0])
    rec["ts"] = "2026-11-19T09:00:00+00:00"
    board.write_text(json.dumps(rec) + "\n")
    main = Writer()
    brief = "Goal: g\nContext: c\nAsks:\n1. a\nRules: read-only\nBudget: 9 tool calls\nDeliverables: write out/r.json\n" + \
            (f"Board: {board}\n" if brief_has_board else "")
    for cid, aid, desc in (("t1", "aud", "check 1"), ("t2", "ver", "verify chunk 1")):
        main.call(cid, "Agent", {"description": desc, "subagent_type": "inspector:audit-verifier" if aid == "ver" else "inspector:auditor",
                                 "model": "sonnet", "prompt": brief}, f"agentId: {aid}", tur={"status": "completed", "agentId": aid, "handbackReport": {"text": "ok"}})
    path = tmp / "proj" / "s.jsonl"
    main.save(path)
    sub = path.with_suffix("") / "subagents"
    a = Writer()
    a.call("a1", "Bash", {"command": "az group list --query [].name"}, "rg-a", side=True, aid="aud")
    a.call("a2", "Bash", {"command": f"python board.py --board {board} add git.x y --by check-1 --evidence e"}, "added", side=True, aid="aud")
    a.save(sub / "agent-aud.jsonl")
    v = Writer()
    steps = [("v1", f"python board.py --board {board} get 'azure.*' --by ver"), ("v2", "git ls-remote --heads origin")]
    for cid, cmd in (steps if verifier_reads_first else steps[::-1]):
        v.call(cid, "Bash", {"command": cmd}, "ok", side=True, aid="ver")
    v.save(sub / "agent-ver.jsonl")
    return path, board


def audited(tmp: Path, **kw) -> dict[str, dict]:
    path, board = board_session(tmp, **kw)
    out = tmp / "a.json"
    A.main([str(path), "--cwd", str(tmp), "--board", str(board), "--json", "--out", str(out)])
    return {r["agent"]: r for r in json.loads(out.read_text())["agents"]}


def test_rerunning_a_board_fact_is_counted_not_blamed(tmp_path):
    r = audited(tmp_path, verifier_reads_first=False, brief_has_board=True)["aud"]
    assert r["board"] == {"reads": 0, "writes": 1, "reran_known": ["azure.resource_group"]}
    assert not any("board" in x for x in r["causes"]["execution"] if "never read" not in x)
    assert any("never read it" in x for x in r["causes"]["execution"]), "the brief named the board and it never read it"


def test_a_brief_without_the_board_line_is_the_brief(tmp_path):
    r = audited(tmp_path, verifier_reads_first=False, brief_has_board=False)["aud"]
    assert any("no Board line" in x for x in r["causes"]["brief"])
    assert not any("never read" in x for x in r["causes"]["execution"])


def test_same_command_matches_words_from_the_start_only():
    assert A.same_command("git ls-remote --heads", "cd /r && git ls-remote --heads origin")
    assert A.same_command("az group list", "x=1; az group list -o json | jq .")
    assert not A.same_command("git ls-remote --heads", "ls -la")
    assert not A.same_command("git log origin/main --first-parent --since", "git log --oneline -5")
    assert not A.same_command("git", "git status"), "one word is too little to call it the same command"


def test_a_verifier_is_never_blamed_for_not_reading_the_board(tmp_path):
    path, board = board_session(tmp_path, verifier_reads_first=False, brief_has_board=True)
    sess = T.load(path)
    v = [x for x in sess.agents if x.agent_id == "ver"][0]
    v.calls = [c for c in v.calls if "board.py" not in str(c.input.get("command", ""))]
    r = A.audit_run(v, tmp_path, {"board_in_use": True, "board_facts": A.load_board(str(board))})
    assert not any("never read" in x for x in r["causes"]["execution"])


def test_a_verifier_that_reads_the_board_first_is_flagged(tmp_path):
    first = audited(tmp_path / "1", verifier_reads_first=True, brief_has_board=True)["ver"]
    later = audited(tmp_path / "2", verifier_reads_first=False, brief_has_board=True)["ver"]
    assert any("read the board before its own check" in x for x in first["causes"]["execution"])
    assert not any("read the board" in x for x in later["causes"]["execution"])
    assert first["board"]["reads"] == 1


def test_board_skill_passes_the_skill_lint():
    sys.path.insert(0, str(ROOT / "skills" / "distill" / "scripts"))
    import lint_skill as L
    assert L.lint(ROOT / "skills" / "board") == ([], [])
    text = (ROOT / "skills" / "board" / "SKILL.md").read_text(encoding="utf-8")
    assert "--max-age" in text and "confirm" in text
