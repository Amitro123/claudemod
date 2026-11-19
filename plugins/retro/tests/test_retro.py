"""retro: the transcript reader, the digest, the skill linter and the sub-agent audit, on synthetic sessions in
the on-disk shape Claude Code writes (main JSONL, `<session>/subagents/agent-<id>.jsonl` + `.meta.json`)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISTILL = ROOT / "skills" / "distill" / "scripts"
AUDIT = ROOT / "skills" / "agent-audit" / "scripts"
sys.path.insert(0, str(DISTILL))
sys.path.insert(0, str(AUDIT))

import agents as A  # noqa: E402
import lint_skill as L  # noqa: E402
import trace as TR  # noqa: E402
import transcript as T  # noqa: E402

FAKE_TOKEN = "ghp_" + "Q7" * 18  # built at runtime so no literal token sits in the repository


class Writer:
    def __init__(self):
        self.rows, self.n = [], 0

    def ts(self):
        self.n += 1
        return f"2026-11-19T10:{self.n // 60:02d}:{self.n % 60:02d}.000Z"

    def user(self, text, **kw):
        self.rows.append({"type": "user", "sessionId": "s", "parentUuid": None, "isSidechain": kw.get("side", False),
                          "timestamp": self.ts(), "message": {"role": "user", "content": text}, **({"agentId": kw["aid"]} if "aid" in kw else {})})

    def call(self, cid, name, inp, result, ok=True, tur=None, **kw):
        base = {"sessionId": "s", "parentUuid": None, "isSidechain": kw.get("side", False), **({"agentId": kw["aid"]} if "aid" in kw else {})}
        self.rows.append({**base, "type": "assistant", "timestamp": self.ts(),
                          "message": {"role": "assistant", "content": [{"type": "tool_use", "id": cid, "name": name, "input": inp}]}})
        r = {**base, "type": "user", "timestamp": self.ts(),
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": result, "is_error": not ok}]}}
        if tur is not None:
            r["toolUseResult"] = tur
        self.rows.append(r)

    def text(self, t, **kw):
        self.rows.append({"type": "assistant", "sessionId": "s", "parentUuid": None, "isSidechain": kw.get("side", False), "timestamp": self.ts(),
                          "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}})

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8")


def brief(deliverable: Path, budget: int | None = 4, context=True) -> str:
    lines = ["Goal: check 1 of an audit.", "Context: the repo is at /work/repo." if context else "",
             "Asks:", "1. List the remote heads.", "2. Count them.",
             "Rules: read-only; never print a secret.", f"Budget: {budget} tool calls." if budget else "",
             f"Deliverables: write {deliverable}"]
    return "\n".join(x for x in lines if x)


def build_session(tmp: Path) -> Path:
    proj = tmp / "proj"
    out_ok = tmp / "out" / "ok.json"
    out_ok.parent.mkdir(parents=True)
    out_ok.write_text("{}")
    main = Writer()
    main.user("Audit today's work, read-only.")
    main.call("m1", "Skill", {"skill": "inspector:audit"}, "loaded")
    main.call("m2", "Bash", {"command": "cd /work/repo && git ls-remote --heads origin"}, "abc refs/heads/main")
    agents_spec = [
        ("tu1", "aaa", "haiku", brief(tmp / "out" / "missing.json", 4), "Tool calls used: 7"),
        ("tu2", "bbb", "opus", brief(out_ok, 10), "done"),
        ("tu3", "ccc", "sonnet", brief(tmp / "out" / "ok.json", None, context=False), "blocked"),
    ]
    for cid, aid, model, prompt, report in agents_spec:
        main.call(cid, "Agent", {"description": f"check {aid}", "subagent_type": "inspector:auditor", "model": model, "prompt": prompt},
                  f"agentId: {aid}\n<usage>tool_uses: 0</usage>",
                  tur={"status": "completed", "agentId": aid, "agentType": "inspector:auditor", "handbackReport": {"text": report}})
    main.text("Final table.")
    path = proj / "sess.jsonl"
    main.save(path)
    sub = path.with_suffix("") / "subagents"
    a = Writer()
    a.user("brief", side=True, aid="aaa")
    a.call("a1", "Bash", {"command": "git ls-remote --heads origin"}, "ok", side=True, aid="aaa")
    a.call("a2", "Bash", {"command": "git status --short"}, "", side=True, aid="aaa")
    for i in range(3):
        a.call(f"a3{i}", "Bash", {"command": "python count.py"}, "Traceback: boom", ok=False, side=True, aid="aaa")
    a.call("a4", "Write", {"file_path": "/work/repo/src/app.py", "content": "x"}, "ok", side=True, aid="aaa")
    a.call("a5", "SubagentHandback", {"message": "Tool calls used: 7"}, "delivered", side=True, aid="aaa")
    a.save(sub / "agent-aaa.jsonl")
    b = Writer()
    b.call("b1", "Bash", {"command": "git status --short"}, "", side=True, aid="bbb")
    b.call("b2", "Write", {"file_path": str(out_ok), "content": "{}"}, "ok", side=True, aid="bbb")
    b.save(sub / "agent-bbb.jsonl")
    c = Writer()
    c.call("c1", "Bash", {"command": "gh api repos/o/r/branches/main/protection"}, "HTTP 403: Forbidden", ok=False, side=True, aid="ccc")
    c.save(sub / "agent-ccc.jsonl")
    for aid, model in (("aaa", "haiku"), ("bbb", "opus"), ("ccc", "sonnet")):
        (sub / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": "inspector:auditor", "model": model, "finished": True}))
    return path


def audit(tmp: Path) -> dict[str, dict]:
    path = build_session(tmp)
    sess = T.load(path)
    rows = []
    for x in sess.agents:
        before = [c for c in sess.calls if c.ts and x.launched and c.ts < x.launched and c.tool not in T.AGENT_TOOLS]
        ctx = {"main_before": {A.norm_call(c) for c in before if c.tool in A.DISCOVERY_TOOLS},
               "skill": next((str(c.input["skill"]) for c in reversed(before) if c.tool == "Skill"), None)}
        rows.append(A.audit_run(x, tmp, ctx))
    A.shared_discovery(rows)
    return {r["agent"]: r for r in rows}


def test_claude_session_with_subagent_files_is_read(tmp_path):
    sess = T.load(build_session(tmp_path))
    assert sess.format == "claude-jsonl"
    assert sess.prompts == ["Audit today's work, read-only."]
    assert [a.agent_id for a in sess.agents] == ["aaa", "bbb", "ccc"]
    a = sess.agents[0]
    assert a.model == "haiku" and a.finished is True and a.transcript.endswith("agent-aaa.jsonl")
    assert len(a.calls) == 7 and len(a.work_calls) == 6
    assert sum(1 for c in a.calls if c.ok is False) == 3


def test_handback_is_not_a_work_call_and_the_difference_is_named(tmp_path):
    r = audit(tmp_path)["aaa"]
    assert r["calls"] == 6 and r["self_reported_calls"] == 7
    assert any("includes the hand-back call" in f for f in r["flags"])


def test_execution_problems_are_owned_by_the_agent(tmp_path):
    c = audit(tmp_path)["aaa"]["causes"]
    joined = " ".join(c["execution"])
    assert "repeated the same call 3x" in joined
    assert "not recovered" in joined
    assert "over budget (6/4)" in joined
    assert "deliverable missing" in joined
    assert "read-only" in joined


def test_a_small_model_struggling_on_a_clear_brief_is_a_model_problem(tmp_path):
    assert any("haiku struggled" in x for x in audit(tmp_path)["aaa"]["causes"]["model"])


def test_a_large_model_on_a_trivial_brief_is_flagged_for_cost(tmp_path):
    r = audit(tmp_path)["bbb"]
    assert any("smaller model may be enough" in x for x in r["causes"]["model"])
    assert r["deliverables"][0]["exists"] and r["deliverables"][0]["written_by_agent"]


def test_withheld_facts_are_a_brief_problem(tmp_path):
    rows = audit(tmp_path)
    assert any("already run" in x for x in rows["aaa"]["causes"]["brief"])
    assert any("sibling agents" in x for x in rows["bbb"]["causes"]["brief"])


def test_a_403_is_the_host_and_a_missing_budget_is_the_brief(tmp_path):
    r = audit(tmp_path)["ccc"]
    assert r["causes"]["host"] and "403" in r["causes"]["host"][0]
    assert not r["causes"]["execution"] and not r["causes"]["model"]
    assert any("no budget" in x for x in r["causes"]["brief"])
    assert not any("context" in x for x in r["causes"]["brief"]), "a missing label is shape, not a problem"
    assert r["brief_checks"]["context"] is False


def test_the_skill_that_wrote_the_brief_is_recorded_and_rolled_up(tmp_path):
    rows = list(audit(tmp_path).values())
    assert {r["skill"] for r in rows} == {"inspector:audit"}
    roll = {x["group"]: x for x in A.rollup(rows, "model")}
    assert roll["haiku"]["model"] == 1 and roll["sonnet"]["host"] == 1


def test_cli_filters_by_skill_and_writes_json(tmp_path):
    path = build_session(tmp_path)
    out = tmp_path / "a.json"
    rc = A.main([str(path), "--cwd", str(tmp_path), "--json", "--out", str(out), "--skill", "audit"])
    d = json.loads(out.read_text())
    assert rc == 0 and len(d["agents"]) == 3 and d["by_skill"][0]["group"] == "inspector:audit"
    A.main([str(path), "--cwd", str(tmp_path), "--json", "--out", str(out), "--skill", "other"])
    assert json.loads(out.read_text())["agents"] == []


def test_report_files_stand_in_when_there_is_no_transcript(tmp_path):
    rep = tmp_path / "agents"
    rep.mkdir()
    (rep / "check-1.json").write_text(json.dumps({"agent": "check-1", "asked": ["a"], "did": ["x"], "tool_calls": 30, "budget": 15,
                                                 "deliverables": [{"path": str(tmp_path / "nope.json"), "written": True}], "blocked": ["403"]}))
    out = tmp_path / "r.json"
    assert A.main(["--reports", str(rep), "--json", "--out", str(out), "--cwd", str(tmp_path)]) == 0
    r = json.loads(out.read_text())["agents"][0]
    assert "self-reported: no transcript checked" in r["flags"]
    assert any("over budget (own count): 30" in f for f in r["flags"])
    assert r["causes"]["host"] and r["causes"]["execution"]


def test_brief_terms():
    t = A.brief_terms("Rules: read-only.\nBudget: 12 tool calls\n1. one\n2. two\nDeliverables: write <scratch>/x.json and out/rows-1.json")
    assert t["budget"] == {"n": 12, "unit": "tool calls"} and t["read_only"]
    assert t["deliverables"] == ["out/rows-1.json"] and t["asks"] == ["one", "two"]


TEXT = """The user wants a read-only audit.

`git log origin/main --since=2026-11-16 --format=%H`

The git log output was truncated at line 150.

`python -c "import re; print(1)"`

The python heredoc got stripped of quotes by PowerShell.

The final table.
"""


def test_text_transcript_keeps_what_each_command_observed(tmp_path):
    f = tmp_path / "run.md"
    f.write_text(TEXT, encoding="utf-8")
    d = TR.digest(T.load(f))
    assert d["format"] == "text" and d["stats"]["calls"] == 2
    errs = " ".join(x["error"] for x in d["failures"])
    assert "truncated at line 150" in errs and "stripped of quotes" in errs
    assert d["steps"][0]["observed"].startswith("The git log output was truncated")


def test_digest_counts_failures_and_repeats_in_a_session(tmp_path):
    sess = T.load(build_session(tmp_path))
    d = TR.digest(sess)
    assert d["skills"] == ["inspector:audit"] and len(d["agents"]) == 3
    assert d["final"] == "Final table."


def test_mask_hides_what_a_skill_must_not_carry():
    s = T.mask(f"mail a.b@corp.example.io id 0f8fad5b-d9cb-469f-a165-70867728950e {FAKE_TOKEN} Bearer abcdefghijklmnopqrstuv "
               r"https://claude.ai/code/session_01ABCdef C:\Users\jdoe\repo /Users/jdoe/x")
    assert "a.b@" not in s and "[address]@corp.example.io" in s
    assert "0f8fad5b" not in s and FAKE_TOKEN not in s and "abcdefghijklmnop" not in s
    assert "session_01ABC" not in s and "jdoe" not in s


def test_trace_cli_masks_by_default(tmp_path):
    f = tmp_path / "run.md"
    f.write_text(f"Do it.\n\n`git push https://x:{FAKE_TOKEN}@github.com/o/r`\n\nmail ops@corp.example.io\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(DISTILL / "trace.py"), str(f)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and FAKE_TOKEN not in out.stdout and "ops@" not in out.stdout


def write_skill(folder: Path, body: str, name: str | None = None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name or folder.name}\ndescription: Does a thing.\n---\n\n{body}", encoding="utf-8")


def test_lint_passes_a_complete_skill(tmp_path):
    d = tmp_path / "my-skill"
    write_skill(d, "## Procedure\n\n1. Run `scripts/go.py`.\n\n## Gotchas\n\n- x\n\n## Output\n\nA table.\n\nBudget: 10 tool calls.\n")
    (d / "scripts").mkdir()
    (d / "scripts" / "go.py").write_text("print(1)\n")
    assert L.lint(d) == ([], [])


def test_lint_refuses_private_data_bad_names_and_missing_files(tmp_path):
    d = tmp_path / "my-skill"
    write_skill(d, "Ask ops@corp.example.io. Tenant 0f8fad5b-d9cb-469f-a165-70867728950e. See references/x.md.\n", name="My_Skill")
    errors, warnings = L.lint(d)
    text = " ".join(errors)
    assert "email" in text and "guid" in text and "references/x.md" in text and "lowercase" in text
    assert len(warnings) == 4


def test_lint_allows_example_addresses(tmp_path):
    d = tmp_path / "ok"
    write_skill(d, "Write to a@example.com.\n")
    assert not L.lint(d)[0]


def test_the_shipped_skills_pass_their_own_lint():
    for name in ("distill", "agent-audit"):
        errors, warnings = L.lint(ROOT / "skills" / name)
        assert errors == [], errors
        assert warnings == [], warnings


def test_shipped_skills_stay_short():
    for name in ("distill", "agent-audit"):
        words = len((ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split())
        assert words <= 1800, (name, words)


def plugin_session(tmp: Path) -> Path:
    """The shape of a factory review: two agents a plugin started, no Agent call in the main transcript."""
    main = Writer()
    main.user("Run a factory review.")
    path = tmp / "proj" / "s.jsonl"
    main.save(path)
    sub = path.with_suffix("") / "subagents"
    brief = ("Review the change for: a shared fact board (board.py) that agents write and read; write a JSON line per fact.\n"
             "The diff is in .factory/x.record/diff.patch. Answer VERDICT: PASS or CHANGES.")
    for aid, kind in (("r1", "factory:code-reviewer"), ("r2", "factory:security-reviewer")):
        w = Writer()
        w.user(brief, side=True, aid=aid)
        for off in (1, 400, 800):
            w.call(f"{aid}r{off}", "Read", {"file_path": "/w/.factory/x.record/diff.patch", "offset": off, "limit": 400}, "...", side=True, aid=aid)
        w.call(f"{aid}g", "Grep", {"pattern": "def add", "path": "/w/plugins"}, "board.py:1", side=True, aid=aid)
        w.call(f"{aid}t", "Bash", {"command": "claude plugin test plugins/retro"}, "Exit code 1\nno hooks module", ok=False, side=True, aid=aid)
        w.call(f"{aid}p", "Bash", {"command": "python -m pytest -q plugins/retro"}, "48 passed", side=True, aid=aid)
        w.call(f"{aid}z", "Bash", {"command": "claude plugin test plugins/inspector"}, "Exit code 1", ok=False, side=True, aid=aid)
        w.text("VERDICT: PASS. claude plugin test fails for want of a hooks module, unrelated.", side=True, aid=aid)
        w.save(sub / f"agent-{aid}.jsonl")
        (sub / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": kind, "model": "opus", "finished": True,
                                                                 "pluginSteered": True, "description": f"factory · {kind}"}))
    return path


def test_agents_a_plugin_started_are_found_and_attributed_to_it(tmp_path):
    sess = T.load(plugin_session(tmp_path))
    assert [(a.agent_id, a.started_by, a.model) for a in sess.agents] == [("r1", "plugin", "opus"), ("r2", "plugin", "opus")]
    assert sess.agents[0].prompt.startswith("Review the change") and sess.agents[0].report.startswith("VERDICT: PASS")
    out = tmp_path / "a.json"
    A.main([str(plugin_session(tmp_path / "2")), "--cwd", str(tmp_path), "--json", "--out", str(out)])
    d = json.loads(out.read_text())
    assert d["by_skill"][0]["group"] == "factory (plugin)" and d["by_skill"][0]["agents"] == 2


def test_the_false_positives_from_the_factory_run_stay_quiet(tmp_path):
    path = plugin_session(tmp_path)
    sess = T.load(path)
    rows = [A.audit_run(x, tmp_path, {"board_in_use": True, "skill": "factory (plugin)"}) for x in sess.agents]
    A.shared_discovery(rows)
    for r in rows:
        text = " ".join(x for v in r["causes"].values() for x in v)
        assert "never read" not in text, "the word board in a feature description is not a Board line"
        assert not r["loops"], "reading one file in three ranges is not a loop"
        assert "diff.patch" not in text and "/w/plugins" not in text, "reading the same diff or searching is not rediscovering"
        assert "python -m pytest -q plugins/retro" in text, "the same shell command in two agents still counts: duplicated work"
        assert r["deliverables"] == [], "a path in the description of the change is not a deliverable"
        assert "not recovered" not in text, "a failed check that the agent went past is not a loop of failures"
        assert any("no budget" in x for x in r["causes"]["brief"])


def test_a_last_failure_the_report_does_not_mention_is_unrecovered(tmp_path):
    a = T.AgentRun(call_id="c", agent_id="x", description="", subagent_type="t", model="sonnet", prompt="Budget: 5 tool calls",
                   report="done", calls=[T.Call("1", "Bash", {"command": "npm run build"}, result="Exit code 2", ok=False)])
    r = A.audit_run(a, tmp_path, {})
    assert any("not recovered" in x for x in r["causes"]["execution"])
    a.report = "done; npm run build fails on a missing env file"
    assert not any("not recovered" in x for x in A.audit_run(a, tmp_path, {})["causes"]["execution"])
