"""Regressions for the Retro review of 2026-11-19 (R1-R7, issues #163-#169): each test is a reproduction from it."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from test_retro import FAKE_TOKEN, Writer  # noqa: F401  (also puts the scripts on the path)
import agents as A  # noqa: E402
import lint_skill as L  # noqa: E402
import trace as TR  # noqa: E402
import transcript as T  # noqa: E402

PAT = "abcdefghij" * 5 + "kl"  # 52 lowercase letters: the shape of an Azure DevOps PAT
KEY = "-----BEGIN PRIVATE KEY-----\nMIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEAq7BFUpkGp3+Ld\n-----END PRIVATE KEY-----"


# R1 (#163)
def _home_with(tmp: Path, project: str, name: str = "s.jsonl") -> Path:
    d = tmp / ".claude" / "projects" / project
    d.mkdir(parents=True)
    (d / name).write_text('{"type":"user","sessionId":"s","parentUuid":null}\n')
    return d / name


def test_no_transcript_for_this_project_is_no_match_not_another_projects(tmp_path):
    _home_with(tmp_path, "other-project")
    assert T.candidates("/different/requested-project", str(tmp_path)) == []
    assert len(T.candidates("/different/requested-project", str(tmp_path), everywhere=True)) == 1


def test_a_newer_foreign_transcript_never_wins(tmp_path):
    mine = _home_with(tmp_path, T.project_slug("/work/mine"))
    other = _home_with(tmp_path, "-work-other")
    os.utime(other, (time.time() + 60, time.time() + 60))
    cur = tmp_path / ".cursor" / "projects"
    (cur / "work-other" / "agent-transcripts").mkdir(parents=True)
    (cur / "work-other" / "agent-transcripts" / "x.md").write_text("Do it.\n")
    (cur / "work-mine" / "agent-transcripts").mkdir(parents=True)
    (cur / "work-mine" / "agent-transcripts" / "y.md").write_text("Do it.\n")
    got = T.candidates("/work/mine", str(tmp_path))
    assert mine in got and other not in got
    assert [f.name for f in got if ".cursor" in str(f)] == ["y.md"]


# R2 (#164)
def resumed_session(tmp: Path) -> Path:
    main = Writer()
    main.call("t1", "Agent", {"description": "check-1", "subagent_type": "auditor", "prompt": "Budget: 3 tool calls\nfirst brief"},
              "agentId: aaa", tur={"status": "completed", "agentId": "aaa", "handbackReport": {"text": "half"}})
    sub = Writer()
    sub.call("s1", "Bash", {"command": "git log -1"}, "x", side=True, aid="aaa")
    main.call("t2", "Agent", {"description": "check-1", "subagent_type": "auditor", "resume": "aaa", "prompt": "Budget: 2 tool calls\ncarry on"},
              "agentId: aaa", tur={"status": "completed", "agentId": "aaa", "handbackReport": {"text": "done"}})
    sub.n = main.n
    sub.call("s2", "Bash", {"command": "git status"}, "x", side=True, aid="aaa")
    path = tmp / "p" / "s.jsonl"
    main.save(path)
    sub.save(path.with_suffix("") / "subagents" / "agent-aaa.jsonl")
    return path


def test_a_resumed_agent_counts_each_call_once_against_its_own_brief(tmp_path):
    sess = T.load(resumed_session(tmp_path))
    assert [(a.dispatch, a.dispatches, len(a.work_calls)) for a in sess.agents] == [(1, 2, 1), (2, 2, 1)]
    rows = [A.audit_run(a, tmp_path, {}) for a in sess.agents]
    assert [r["agent"] for r in rows] == ["aaa#1", "aaa#2"]
    assert [r["budget"]["n"] for r in rows] == [3, 2] and sum(r["calls"] for r in rows) == 2


# R3 (#165)
def test_key_blocks_and_pat_shapes_are_masked_in_both_digest_formats(tmp_path):
    f = tmp_path / "run.md"
    f.write_text(f"Do it.\n\n`cat key.pem`\n\n{KEY}\nTOKEN={PAT}\n", encoding="utf-8")
    for fmt in ([], ["--json"]):
        out = tmp_path / "d.txt"
        TR.main([str(f), "--out", str(out), *fmt])
        text = out.read_text()
        assert "MIIBVQIB" not in text and PAT not in text and "BEGIN PRIVATE KEY" not in text


def test_lint_refuses_a_key_block_or_a_pat_in_any_file_without_printing_it(tmp_path, capsys):
    d = tmp_path / "s"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: s\ndescription: x\n---\n\nTOKEN=" + PAT + "\n")
    (d / "references" / "k.md").write_text(KEY + "\n")
    errors, _ = L.lint(d)
    kinds = " ".join(errors)
    assert "azure-devops-pat" in kinds and "private-key" in kinds and PAT not in kinds and "MIIBVQIB" not in kinds


# R4 (#166)
def test_a_report_only_agent_is_neither_clean_nor_a_measured_zero(tmp_path):
    rep = tmp_path / "agents"
    rep.mkdir()
    (rep / "c.json").write_text(json.dumps({"agent": "c", "type": "auditor", "budget": 10, "tool_calls": 2, "did": ["done"]}))
    out = tmp_path / "a.json"
    A.main(["--reports", str(rep), "--json", "--out", str(out), "--cwd", str(tmp_path)])
    d = json.loads(out.read_text())
    roll = d["by_skill"][0]
    assert roll["observed"] == 0 and roll["reported_only"] == 1 and roll["failure_rate"] is None and roll["clean"] == 0
    assert "1 of 1 self-reported" in d["budgets"][0]["note"]
    md = tmp_path / "a.md"
    A.main(["--reports", str(rep), "--out", str(md), "--cwd", str(tmp_path)])
    assert "| 1 (1 report-only) | 0 | ? |" in md.read_text()


# R5 (#167)
def test_a_budget_in_turns_is_not_compared_with_calls(tmp_path):
    a = T.AgentRun(call_id="c", agent_id="x", description="", subagent_type="t", model="haiku", prompt="Budget: 1 turns\n1. do it",
                   report="done", calls=[T.Call("1", "Read", {"file_path": "/a"}, ok=True), T.Call("2", "Read", {"file_path": "/b"}, ok=True)])
    r = A.audit_run(a, tmp_path, {})
    assert r["budget"] == {"n": 1, "unit": "turns"}
    assert not any("over budget" in x for v in r["causes"].values() for x in v)
    assert any("not checkable" in f for f in r["flags"])
    a.prompt = "Budget: 1 tool calls\n1. do it"
    assert any("over budget (2/1)" in x for v in A.audit_run(a, tmp_path, {})["causes"].values() for x in v)


# R6 (#168): paths outside /tmp, which the audit counts as scratch
WORK = Path("/work")


def run_with_write(path: str, ok: bool = True) -> dict:
    a = T.AgentRun(call_id="c", agent_id="x", description="", subagent_type="t", model="sonnet",
                   prompt=f"Rules: read-only\nDeliverables: {WORK}/out/report.md", report="done",
                   calls=[T.Call("1", "Write", {"file_path": path, "content": "x"}, ok=ok, result="" if ok else "permission denied")])
    return A.audit_run(a, WORK / "repo", {})


def test_the_same_file_name_in_another_folder_is_not_the_allowed_deliverable():
    r = run_with_write(str(WORK / "repo" / "report.md"))
    assert any("broke the brief's read-only rule" in x for x in r["causes"]["execution"])
    assert not any("read-only" in x for x in run_with_write(str(WORK / "out" / "report.md"))["causes"]["execution"])
    assert not any("read-only" in x for x in run_with_write("../out/sub/../report.md")["causes"]["execution"]), "relative to the agent's folder"


def test_a_refused_write_is_an_attempt_not_a_change():
    r = run_with_write(str(WORK / "repo" / "report.md"), ok=False)
    assert r["writes"] == [] and r["refused_writes"]
    ex = " ".join(r["causes"]["execution"])
    assert "broke the brief's read-only rule" not in ex and "the writes were refused" in ex


# R7 (#169)
def labelled_session(tmp: Path, label_twice: bool = False) -> Path:
    main = Writer()
    for cid, aid in (("t1", "aaa"), ("t2", "bbb")) if label_twice else (("t1", "aaa"),):
        main.call(cid, "Agent", {"description": "check-1", "subagent_type": "auditor",
                                 "prompt": f"Budget: 5 tool calls\nReport file: <run>/agents/check-1.json"},
                  f"agentId: {aid}", tur={"status": "completed", "agentId": aid, "handbackReport": {"text": "done"}})
    path = tmp / "p" / "s.jsonl"
    main.save(path)
    for aid in ("aaa", "bbb") if label_twice else ("aaa",):
        w = Writer()
        w.call("s1", "Bash", {"command": "git log -1"}, "x", side=True, aid=aid)
        w.call("s2", "Bash", {"command": "git status"}, "x", side=True, aid=aid)
        w.save(path.with_suffix("") / "subagents" / f"agent-{aid}.jsonl")
    return path


def reports(tmp: Path, calls: int) -> Path:
    rep = tmp / "agents"
    rep.mkdir(exist_ok=True)
    (rep / "check-1.json").write_text(json.dumps({"agent": "check-1", "brief_id": "check-1", "tool_calls": calls, "budget": 5}))
    return rep


def test_a_report_named_by_its_brief_label_joins_its_transcript_row(tmp_path):
    out = tmp_path / "a.json"
    A.main([str(labelled_session(tmp_path)), "--reports", str(reports(tmp_path, 7)), "--json", "--out", str(out), "--cwd", str(tmp_path)])
    rows = json.loads(out.read_text())["agents"]
    assert [r["agent"] for r in rows] == ["aaa"]
    assert any("report file says 7 calls, transcript shows 2" in f for f in rows[0]["flags"])


def test_an_ambiguous_label_joins_nothing(tmp_path):
    out = tmp_path / "a.json"
    A.main([str(labelled_session(tmp_path, label_twice=True)), "--reports", str(reports(tmp_path, 2)), "--json", "--out", str(out), "--cwd", str(tmp_path)])
    rows = json.loads(out.read_text())["agents"]
    assert sorted(r["agent"] for r in rows) == ["aaa", "bbb", "check-1"]
    assert any("ambiguous" in f for f in next(r for r in rows if r["agent"] == "check-1")["flags"])


def test_timestamps_in_mixed_formats_compare_by_the_instant():
    from transcript import _instant
    assert _instant("2026-11-19T10:00:01Z") == _instant("2026-11-19T10:00:01+00:00") == _instant("2026-11-19T10:00:01.000Z")
    assert _instant("2026-11-19T10:00:01.5Z") > _instant("2026-11-19T10:00:01Z"), "as text, '.5Z' sorts before 'Z'"
    assert _instant("2026-11-19T12:00:00+02:00") == _instant("2026-11-19T10:00:00Z")
    assert _instant("2026-11-19T10:00:00.1234567Z") is not None, "more than six fraction digits"
    assert _instant("") is None and _instant("yesterday") is None


def test_a_truncated_private_key_is_masked_without_breaking_the_json_line():
    line = json.dumps({"type": "tool_result", "content": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...cut", "next": "kept"})
    out = T.mask(line)
    assert json.loads(out) == {"type": "tool_result", "content": "[private-key]", "next": "kept"}
    assert T.mask("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\nafter") == "[private-key]\nafter"
    assert T.mask("-----BEGIN PRIVATE KEY-----\nabc") == "[private-key]", "plain text with no end still masks to the end"


def test_a_path_through_scratch_and_back_out_is_not_scratch():
    assert A.is_scratch("/tmp/run/out.md") and A.is_scratch("C:\\Users\\a\\AppData\\Local\\Temp\\x.txt")
    assert not A.is_scratch("/tmp/../home/user/repo/src/app.py")
    assert not A.is_scratch("scratchpad/../../repo/x.py")
    assert not A.is_scratch("../tmp/x")


def _write_verdict(tmp_path, target, cwd="/work/repo"):
    from pathlib import Path as P
    run = T.AgentRun("x", "a", "", "auditor", None, "Rules: read-only\nBudget: 5 tool calls", report="done",
                     calls=[T.Call("1", "Write", {"file_path": target}, ok=True)])
    return A.audit_run(run, P(cwd))["causes"]["execution"]


def test_a_source_file_named_like_scratch_is_still_a_write_to_the_repository(tmp_path):
    for target in ["/work/repo/src/scratchpad.py", "/work/repo/src/temp/app.py", "/work/repo/src/tmp/app.py",
                   "src/temp/app.py", "./src/scratchpad.py", "/work/repo/src/app.py"]:
        assert _write_verdict(tmp_path, target) == ["broke the brief's read-only rule"], target
    for target in ["/tmp/claude-0/s/scratchpad/out.md", "/work/repo/.inspector-run/r.json", ".inspector-run/r.json",
                   "/var/folders/ab/T/x.txt", "$env:TEMP\\x.txt", "%TEMP%\\x.txt"]:
        assert _write_verdict(tmp_path, target) == [], target
    win = "C:\\Users\\a\\repo"
    assert _write_verdict(tmp_path, "C:\\Users\\a\\AppData\\Local\\Temp\\x.txt", win) == []
    assert _write_verdict(tmp_path, "C:\\Users\\a\\repo\\src\\temp\\x.py", win) == ["broke the brief's read-only rule"]


def test_a_repository_under_a_temp_folder_is_not_scratch_itself(tmp_path):
    assert _write_verdict(tmp_path, "/tmp/repo/src/app.py", "/tmp/repo") == ["broke the brief's read-only rule"]
    assert _write_verdict(tmp_path, "src/app.py", "/tmp/repo") == ["broke the brief's read-only rule"]
    assert _write_verdict(tmp_path, "/tmp/elsewhere/out.md", "/tmp/repo") == []
    assert _write_verdict(tmp_path, "/tmp/../work/repo/src/app.py") == ["broke the brief's read-only rule"]


BACKSLASH = chr(92)
TRICKY = ["-----BEGIN PRIVATE KEY-----\nQUJDQUJD" + BACKSLASH,
          "-----BEGIN PRIVATE KEY-----\nQUJD" + BACKSLASH * 3,
          "-----BEGIN PRIVATE KEY-----\nQUJD\n-----END PRIVATE KEY-----",
          'quote " and ' + BACKSLASH + '" inside',
          "log line C:" + BACKSLASH + "work" + BACKSLASH]


def test_masking_json_keeps_it_json_with_backslashes_quotes_and_nesting():
    data = {"content": TRICKY[0], "next": "kept", "list": [{"a": v, "b": "kept"} for v in TRICKY], "n": 3}
    out = json.loads(json.dumps(T.mask_data(data)))
    assert out["next"] == "kept" and out["n"] == 3 and all(x["b"] == "kept" for x in out["list"])
    assert "QUJD" not in json.dumps(out)
    assert out["list"][3]["a"] == TRICKY[3] and out["list"][4]["a"] == TRICKY[4]


def test_both_clis_emit_valid_json_around_a_cut_off_key_and_a_trailing_backslash(tmp_path):
    md = tmp_path / "run.md"
    md.write_text("Do it.\n\n-----BEGIN PRIVATE KEY-----\nQUJDQUJD\n\nran it in C:" + BACKSLASH + "work" + BACKSLASH + "\n\nsaid \"done\"\n", encoding="utf-8")
    out = tmp_path / "t.json"
    assert TR.main([str(md), "--json", "--out", str(out)]) in (0, None)
    text = out.read_text(encoding="utf-8")
    json.loads(text)
    assert "QUJDQUJD" not in text
    rep = tmp_path / "agents"
    rep.mkdir()
    (rep / "c.json").write_text(json.dumps({"agent": "c", "type": "auditor", "did": [TRICKY[0], "next step", TRICKY[4]]}))
    out2 = tmp_path / "a.json"
    A.main(["--reports", str(rep), "--json", "--out", str(out2), "--cwd", str(tmp_path)])
    text2 = out2.read_text(encoding="utf-8")
    json.loads(text2)
    assert "QUJDQUJD" not in text2
