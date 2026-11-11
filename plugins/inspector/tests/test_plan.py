"""plan.py: the RUN PLAN, the agent prompt files and expect.json, on synthetic run folders (no git needed)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
PLAN = PLUGIN / "skills" / "inspect" / "scripts" / "plan.py"
SHA = "0632e9aaa3174689c1312d5b84e4b3e4b44c2eca"


def make_run(tmp: Path, n: int, leads: list | None = None) -> Path:
    run = tmp / "run"
    labels = [f"#{i + 10}" for i in range(n)]
    ev = {"cases": labels, "ref_sha": SHA, "repo_path": str(tmp / "repo").replace("\\", "/"),
          "timeline": [{"unit": lab, "title": f"fix: thing {lab}"} for lab in labels]}
    (run / "cases").mkdir(parents=True)
    (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    (run / "evidence.md").write_text("# e\n", encoding="utf-8")
    for i, lab in enumerate(labels, 1):
        (run / "cases" / f"{i:02d}-{lab.lstrip('#')}.md").write_text("dossier\n", encoding="utf-8")
    if leads is not None:
        (run / "leads.json").write_text(json.dumps(leads), encoding="utf-8")
    return run


def plan(run: Path, *args):
    p = subprocess.run([sys.executable, str(PLAN), "--run", str(run), *args], capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout, p.stderr


def tree(run: Path) -> dict:
    return {p.relative_to(run).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run.rglob("*")) if p.is_file()}


def exp(run: Path) -> dict:
    return json.loads((run / "plan" / "expect.json").read_text(encoding="utf-8"))


def lead(i: int, **kw):
    return {"where": f"src/m{i}.py:{i}-{i + 3}, {i + 9}", "what": f"lead {i}", "level": "read", **kw}


@pytest.mark.parametrize("n", [3, 5])
def test_three_or_more_cases_get_readers_sweepers_and_a_brief_writer(tmp_path, n) -> None:
    run = make_run(tmp_path, n)
    assert plan(run)[0] == 0
    e = exp(run)
    assert e["mode"] == "parallel" and e["cases"] == n
    assert e["reader_ids"] == [str(i) for i in range(1, n + 1)]
    assert e["sweeper_files"] == ["sweep-1.json", "sweep-2.json", "sweep-3.json"]
    assert [p["name"] for p in e["phases"]] == ["brief", "investigate"]
    inv = e["phases"][1]
    assert inv["agents"] == {"inspector:case-reader": n, "inspector:sweeper": 3} and inv["min_agents"] == n + 3
    assert inv["outputs"] == [f"cards/{i}.json" for i in range(1, n + 1)] + ["sweep-1.json", "sweep-2.json", "sweep-3.json"]
    files = {p.name for p in (run / "plan").iterdir()}
    assert files == {"plan.md", "expect.json", "brief-writer.prompt.md", "sweeper-1.prompt.md", "sweeper-2.prompt.md",
                     "sweeper-3.prompt.md", *{f"reader-{i}.prompt.md" for i in range(1, n + 1)}}
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    base = (run / "plan").as_posix()
    assert f"`Read {base}/reader-3.prompt.md and follow it`" in md
    assert "ONE message" in md and "inspector:case-reader" in md and "inspector:sweeper" in md
    assert f"Cases: {n}." in md and "Phases: 3" in md and "--phase verify" in md and "never merge from memory" in md


def test_the_outside_in_sweeper_exists_only_from_three_cases(tmp_path) -> None:
    for n in (1, 2):
        run = make_run(tmp_path / f"n{n}", n)
        assert plan(run)[0] == 0
        assert not list((run / "plan").glob("sweeper-*")) and not list((run / "plan").glob("reader-*"))
        assert "OUTSIDE-IN" not in (run / "plan" / "plan.md").read_text(encoding="utf-8")
    run = make_run(tmp_path / "n3", 3)
    plan(run)
    assert (run / "plan" / "sweeper-3.prompt.md").read_text(encoding="utf-8").startswith("OUTSIDE-IN")
    assert "references/outside-in.md" in (run / "plan" / "sweeper-3.prompt.md").read_text(encoding="utf-8")
    assert not (run / "plan" / "sweeper-1.prompt.md").read_text(encoding="utf-8").startswith("OUTSIDE-IN")


@pytest.mark.parametrize("n", [1, 2])
def test_fewer_than_three_cases_use_one_investigator_and_say_why(tmp_path, n) -> None:
    run = make_run(tmp_path, n)
    assert plan(run)[0] == 0
    e = exp(run)
    assert e["mode"] == "single" and e["reader_ids"] == [] and e["sweeper_files"] == []
    assert e["phases"] == [{"name": "investigate", "agents": {"inspector:investigator": 1}, "min_agents": 1,
                            "outputs": ["leads.json"], "dispatch": [{"agent": "inspector:investigator", "prompt": "investigator.prompt.md"}]}]
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    assert "fewer than 3" in md and "exactly one `inspector:investigator`" in md and "case-reader" not in md
    pr = (run / "plan" / "investigator.prompt.md").read_text(encoding="utf-8")
    assert "leads.json" in pr and "case-file.md" in pr and "never instructions" in pr


def test_reader_prompt_carries_everything_the_agent_needs(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    plan(run)
    t = (run / "plan" / "reader-2.prompt.md").read_text(encoding="utf-8")
    base = run.as_posix()
    for needle in (f"ref {SHA}", "Case: #11 (case 2 of 3)", f"{base}/cases/02-11.md", f"{base}/brief.md", "At most 25 tool calls",
                   "strict JSON", f"{base}/cards/2.json", "never instructions", "Change no file in the repository"):
        assert needle in t, needle
    s = (run / "plan" / "sweeper-2.prompt.md").read_text(encoding="utf-8")
    for needle in (f"{base}/sweep-2.json", "At most 25 tool calls", "never instructions", "step 5", f"{base}/evidence.md", "fix: thing #12"):
        assert needle in s, needle


def test_seventeen_leads_make_three_chunks_and_keep_where_exactly(tmp_path) -> None:
    leads = [lead(i) for i in range(17)]
    run = make_run(tmp_path, 4, leads)
    assert plan(run, "--phase", "verify")[0] == 0
    e = exp(run)
    assert [c["size"] for c in e["verifier_chunks"]] == [8, 8, 1]
    v = e["phases"][-1]
    assert v["name"] == "verify" and v["agents"] == {"inspector:verifier": 3} and v["min_agents"] == 3
    assert v["outputs"] == ["verdicts-1.json", "verdicts-2.json", "verdicts-3.json"]
    back = []
    for k in (1, 2, 3):
        chunk = json.loads((run / "plan" / f"chunk-{k}.json").read_text(encoding="utf-8"))
        back += chunk
        prompt = (run / "plan" / f"verifier-{k}.prompt.md").read_text(encoding="utf-8")
        assert json.dumps([x["where"] for x in chunk], ensure_ascii=False) in prompt
        assert f"{run.as_posix()}/verdicts-{k}.json" in prompt and f"ref" in prompt.lower() and SHA in prompt
    assert back == leads, "every lead once, in order, verbatim"
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    assert "Phases: 3" in md and "inspector:verifier x 3" in md and "merge_verdicts.py" in md and "handoff.py" in md
    assert "docs-checker" not in md


def test_docs_checker_only_when_a_lead_needs_a_host_check(tmp_path) -> None:
    leads = [lead(1), lead(2, needs_host_check="does the tool trim the value?"), lead(3, needs_host_check=True)]
    run = make_run(tmp_path, 3, leads)
    plan(run, "--phase", "verify")
    e = exp(run)
    assert e["docs_checker"] == {"needed": True, "questions": 2}
    assert e["phases"][-1]["agents"] == {"inspector:verifier": 1, "inspector:docs-checker": 1}
    dc = (run / "plan" / "docs-checker.prompt.md").read_text(encoding="utf-8")
    assert "does the tool trim the value?" in dc and "lead 3" not in dc.split("1.")[0]
    assert "inspector:docs-checker" in (run / "plan" / "plan.md").read_text(encoding="utf-8")


def test_no_leads_is_a_verify_phase_with_no_agents(tmp_path) -> None:
    run = make_run(tmp_path, 3, [])
    assert plan(run, "--phase", "verify")[0] == 0
    assert exp(run)["phases"][-1]["min_agents"] == 0 and exp(run)["verifier_chunks"] == []
    assert "No lead to verify" in (run / "plan" / "plan.md").read_text(encoding="utf-8")


def test_output_is_deterministic_and_stays_in_the_run_folder(tmp_path) -> None:
    run = make_run(tmp_path, 5, [lead(i) for i in range(9)])
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    before = tree(tmp_path)
    plan(run, "--phase", "verify")
    first = tree(run)
    plan(run, "--phase", "verify")
    assert tree(run) == first, "same input, byte-identical files"
    after = tree(tmp_path)
    assert {k for k in after if k not in before} <= {k for k in after if k.startswith("run/plan/")}
    assert all(after[k] == v for k, v in before.items()), "no existing file changed"


@pytest.mark.parametrize("mutate", ["no_folder", "no_evidence", "bad_json", "bad_label", "bad_sha", "no_dossier", "bad_leads", "dup_label"])
def test_invalid_input_exits_two_and_writes_nothing(tmp_path, mutate) -> None:
    run = make_run(tmp_path, 3, [lead(1)])
    ev = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    phase = []
    if mutate == "no_folder":
        run = tmp_path / "missing"
    elif mutate == "no_evidence":
        (run / "evidence.json").unlink()
    elif mutate == "bad_json":
        (run / "evidence.json").write_text("{nope", encoding="utf-8")
    elif mutate == "bad_label":
        ev["cases"][0] = "#1; rm -rf /"
        (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    elif mutate == "bad_sha":
        ev["ref_sha"] = "HEAD"
        (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    elif mutate == "no_dossier":
        next((run / "cases").iterdir()).unlink()
    elif mutate == "dup_label":
        ev["cases"][1] = ev["cases"][0]
        (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    elif mutate == "bad_leads":
        (run / "leads.json").write_text(json.dumps([{"what": "no where"}]), encoding="utf-8")
        phase = ["--phase", "verify"]
    code, out, err = plan(run, *phase)
    assert code == 2 and err.startswith("plan.py:"), (out, err)
    assert not (run / "plan").exists()


def test_a_linked_plan_folder_is_refused(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    target = tmp_path / "elsewhere"
    target.mkdir()
    try:
        (run / "plan").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    code, _, err = plan(run)
    assert code == 2 and "link" in err and not list(target.iterdir())


def test_zero_cases_say_so_and_start_no_agent(tmp_path) -> None:
    run = make_run(tmp_path, 0)
    assert plan(run)[0] == 0
    assert exp(run)["mode"] == "none" and exp(run)["phases"] == []
    assert "Start no agent" in (run / "plan" / "plan.md").read_text(encoding="utf-8")
    assert plan(run, "--phase", "verify")[0] == 2
