"""Resume (`plan.py --status`) and the docs-checker: its answers are a tracked output, and the verifier that waits for
them (`after`) is not handed out while they are missing or unusable. Found in a review of 4ad47bd: the docs-checker was
registered with no output, so status could not see its work was unfinished and named only the verifier to restart."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_plan import exp, lead, make_run, plan, tree  # noqa: E402

VALID = [{"n": 1, "where": lead(2)["where"], "answer": "yes", "text": "The tool trims the value.", "source": "https://docs.example/x"}]


def docs_run(tmp_path: Path) -> Path:
    """Three leads, one with a documentation question: one chunk, whose verifier waits for the answers."""
    run = make_run(tmp_path, 3, [lead(1), lead(2, needs_host_check="does the tool trim the value?"), lead(3)])
    assert plan(run, "--phase", "verify")[0] == 0
    return run


def status(run: Path):
    before = tree(run)
    code, out, err = plan(run, "--status")
    assert tree(run) == before, "--status writes nothing"
    return code, out + err


def agent_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("- inspector:")]


def test_the_docs_checker_has_a_tracked_output(tmp_path) -> None:
    run = docs_run(tmp_path)
    d = [x for ph in exp(run)["phases"] for x in ph["dispatch"] if x["agent"] == "inspector:docs-checker"]
    assert [x["outputs"] for x in d] == [["docs-answers.json"]]
    assert "docs-answers.json" in [o for ph in exp(run)["phases"] if ph["name"] == "verify" for o in ph["outputs"]]


def test_missing_answers_restart_the_docs_checker_and_hold_the_verifier(tmp_path) -> None:
    code, out = status(docs_run(tmp_path))
    lines = agent_lines(out)
    assert code == 1
    assert len(lines) == 1 and "inspector:docs-checker" in lines[0] and "docs-answers.json missing" in lines[0]
    assert "1 agent to start again" in out
    blocked = [ln for ln in out.splitlines() if "blocked" in ln]
    assert len(blocked) == 1 and "verifier-1.prompt.md" in blocked[0] and "docs-answers.json" in blocked[0]
    assert "Left: 2 agents" in out                      # the held verifier is still work left


@pytest.mark.parametrize("content,why", [("", "empty"), ("   \n", "empty"), ("not json at all", "not valid JSON"),
                                         ("[]", "holds no answer"), ('{"n": 1}', "holds no answer"),
                                         ('[{"n": 1, "answer": "yes"}]', "holds no answer")])
def test_empty_or_unusable_answers_leave_the_prerequisite_unfinished(tmp_path, content, why) -> None:
    run = docs_run(tmp_path)
    (run / "docs-answers.json").write_text(content, encoding="utf-8")
    code, out = status(run)
    lines = agent_lines(out)
    assert code == 1 and len(lines) == 1 and "inspector:docs-checker" in lines[0] and why in lines[0], out
    assert any("blocked" in ln and "verifier-1.prompt.md" in ln for ln in out.splitlines())


def test_valid_answers_free_the_verifier_and_the_docs_checker_is_not_restarted(tmp_path) -> None:
    run = docs_run(tmp_path)
    (run / "docs-answers.json").write_text(json.dumps(VALID), encoding="utf-8")
    code, out = status(run)
    lines = agent_lines(out)
    assert code == 1 and len(lines) == 1 and "inspector:verifier" in lines[0] and "verdicts-1.json missing" in lines[0]
    assert "docs-checker" not in out and "blocked" not in out


def test_everything_present_is_complete(tmp_path) -> None:
    run = docs_run(tmp_path)
    (run / "docs-answers.json").write_text(json.dumps(VALID), encoding="utf-8")
    (run / "verdicts-1.json").write_text(json.dumps([{"where": lead(i)["where"], "verdict": "REAL"} for i in (1, 3, 2)]), encoding="utf-8")
    code, out = status(run)
    assert "docs-checker" not in out and "blocked" not in out and not agent_lines(out)


def test_a_run_without_a_documentation_question_is_as_before(tmp_path) -> None:
    run = make_run(tmp_path, 3, [lead(1), lead(2), lead(3)])
    assert plan(run, "--phase", "verify")[0] == 0
    assert all("after" not in d for ph in exp(run)["phases"] for d in ph["dispatch"])
    code, out = status(run)
    lines = agent_lines(out)
    assert code == 1 and len(lines) == 1 and "inspector:verifier" in lines[0]
    assert "docs" not in out and "blocked" not in out


def test_a_plan_written_before_the_output_was_tracked_still_honours_after(tmp_path) -> None:
    """0.8.2 plans carry `after` on the verifier and a docs-checker with no outputs."""
    run = docs_run(tmp_path)
    p = run / "plan" / "expect.json"
    e = json.loads(p.read_text(encoding="utf-8"))
    for ph in e["phases"]:
        ph["outputs"] = [o for o in ph["outputs"] if o != "docs-answers.json"]
        for d in ph["dispatch"]:
            if d["agent"] == "inspector:docs-checker":
                d["outputs"] = []
    p.write_text(json.dumps(e), encoding="utf-8")
    code, out = status(run)
    lines = agent_lines(out)
    assert code == 1 and len(lines) == 1 and "inspector:docs-checker" in lines[0] and "docs-answers.json missing" in lines[0]
    assert any("blocked" in ln and "verifier-1.prompt.md" in ln for ln in out.splitlines())
    (run / "docs-answers.json").write_text(json.dumps(VALID), encoding="utf-8")
    code, out = status(run)
    assert [("inspector:verifier" in ln) for ln in agent_lines(out)] == [True] and "blocked" not in out


def test_a_plan_older_still_with_no_after_is_unchanged(tmp_path) -> None:
    run = docs_run(tmp_path)
    p = run / "plan" / "expect.json"
    e = json.loads(p.read_text(encoding="utf-8"))
    for ph in e["phases"]:
        ph["outputs"] = [o for o in ph["outputs"] if o != "docs-answers.json"]
        for d in ph["dispatch"]:
            d.pop("after", None)
            if d["agent"] == "inspector:docs-checker":
                d["outputs"] = []
    p.write_text(json.dumps(e), encoding="utf-8")
    code, out = status(run)
    lines = agent_lines(out)
    assert code == 1 and len(lines) == 1 and "inspector:verifier" in lines[0] and "blocked" not in out
