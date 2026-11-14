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


def investigate(e: dict) -> list[dict]:
    return [p for p in e["phases"] if p["name"] == "investigate"]


@pytest.mark.parametrize("n,readers", [(7, 3), (12, 4)])
def test_seven_or_more_cases_get_readers_of_three_cases_sweepers_and_a_brief_writer(tmp_path, n, readers) -> None:
    run = make_run(tmp_path, n)
    assert plan(run)[0] == 0
    e = exp(run)
    assert e["mode"] == "parallel" and e["cases"] == n and "per_case" not in e
    assert e["reader_ids"] == [str(i) for i in range(1, n + 1)]
    assert e["sweeper_files"] == ["sweep-1.json", "sweep-2.json", "sweep-3.json"]
    assert e["phases"][0]["name"] == "brief" and all(p["name"] == "investigate" for p in e["phases"][1:])
    inv = investigate(e)
    assert len(inv) == 2 and [(p["wave"], p["waves"]) for p in inv] == [(1, 2), (2, 2)]
    assert all(p["min_agents"] <= 4 for p in e["phases"])
    assert sum(p["agents"].get("inspector:case-reader", 0) for p in inv) == readers
    assert sum(p["agents"].get("inspector:sweeper", 0) for p in inv) == 3
    outputs = [o for p in inv for o in p["outputs"]]
    # the sweepers longest first (OUTSIDE-IN, code, docs): a later wave's agents take slots as they free up
    assert sorted(o for o in outputs if o.startswith("cards/")) == sorted(f"cards/{i}.json" for i in range(1, n + 1))
    assert len(outputs) == n + 3 and [o for o in outputs if o.startswith("sweep")] == ["sweep-3.json", "sweep-1.json", "sweep-2.json"]
    first = inv[0]["dispatch"][0]
    assert {k: first[k] for k in ("agent", "model", "prompt")} == {"agent": "inspector:case-reader", "model": "sonnet",
                                                                   "prompt": "reader-1.prompt.md"}
    # one queue: every reader may write every card, so each lists them all, once
    reader_dispatch = [d for p in inv for d in p["dispatch"] if d["agent"] == "inspector:case-reader"]
    assert all(sorted(d["outputs"]) == sorted(f"cards/{i}.json" for i in range(1, n + 1)) for d in reader_dispatch)
    files = {p.name for p in (run / "plan").iterdir()}
    assert files == {"plan.md", "expect.json", "brief-writer.prompt.md", "sweeper-1.prompt.md", "sweeper-2.prompt.md",
                     "sweeper-3.prompt.md", *{f"reader-{k}.prompt.md" for k in range(1, readers + 1)}}
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    base = (run / "plan").as_posix()
    assert f"`Read {base}/reader-{readers}.prompt.md and follow it`" in md
    assert "ONE message" in md and "inspector:case-reader" in md and "inspector:sweeper" in md and "--status" in md
    assert "wave 1 of 2" in md and "wave 2 of 2" in md
    assert f"Cases: {n}." in md and "Phases: 4" in md and "--phase verify" in md and "never merge from memory" in md
    assert md.index("wave 2 of 2") < md.index("merge_cards.py"), "the merge comes after the last wave"
    assert md.count("merge_cards.py") == 1


def test_every_dispatch_names_the_model_its_agent_file_asks_for(tmp_path) -> None:
    """Hosts may ignore an agent file's `model:` and run the agent on the caller's model; the plan states it instead."""
    import re
    run = make_run(tmp_path, 7, [lead(i) for i in range(3)])
    assert plan(run, "--phase", "verify")[0] == 0
    want = {}
    for f in (PLUGIN / "agents").glob("*.md"):
        m = re.search(r"^model:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
        want[f"inspector:{f.stem}"] = m[1]
    dispatch = [d for p in exp(run)["phases"] for d in p["dispatch"]]
    assert {d["agent"] for d in dispatch} == {"general-purpose", "inspector:case-reader", "inspector:sweeper", "inspector:verifier"}
    for d in dispatch:
        assert d["model"] == want.get(d["agent"], "sonnet"), d
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    assert "passed explicitly" in md
    assert all("(model: " in x for x in md.splitlines() if "and follow it`" in x and x.startswith("- "))
    assert "inspector:case-reader (model: sonnet): `Read" in plan(run, "--status")[1]


def test_per_case_gives_one_reader_per_case_from_three_cases(tmp_path) -> None:
    run = make_run(tmp_path, 4)
    assert plan(run, "--per-case")[0] == 0
    e = exp(run)
    assert e["mode"] == "parallel" and e["per_case"] is True and e["reader_ids"] == ["1", "2", "3", "4"]
    inv = investigate(e)
    assert [p["min_agents"] for p in inv] == [4, 3]
    assert [d["outputs"] for d in inv[0]["dispatch"]] == [[f"cards/{i}.json"] for i in range(1, 5)]
    assert "Case: #13 (case 4 of 4)" in (run / "plan" / "reader-4.prompt.md").read_text(encoding="utf-8")
    run2 = make_run(tmp_path / "two", 2)
    assert plan(run2, "--per-case")[0] == 0 and exp(run2)["mode"] == "single"


def test_the_outside_in_sweeper_exists_only_from_seven_cases(tmp_path) -> None:
    for n in (1, 2, 6):
        run = make_run(tmp_path / f"n{n}", n)
        assert plan(run)[0] == 0
        assert not list((run / "plan").glob("sweeper-*")) and not list((run / "plan").glob("reader-*"))
        assert "OUTSIDE-IN" not in (run / "plan" / "plan.md").read_text(encoding="utf-8")
    run = make_run(tmp_path / "n7", 7)
    plan(run)
    assert (run / "plan" / "sweeper-3.prompt.md").read_text(encoding="utf-8").startswith("OUTSIDE-IN")
    assert "references/outside-in.md" in (run / "plan" / "sweeper-3.prompt.md").read_text(encoding="utf-8")
    assert not (run / "plan" / "sweeper-1.prompt.md").read_text(encoding="utf-8").startswith("OUTSIDE-IN")


@pytest.mark.parametrize("n", [1, 2, 6])
def test_up_to_six_cases_use_one_investigator_and_say_why(tmp_path, n) -> None:
    run = make_run(tmp_path, n)
    assert plan(run)[0] == 0
    e = exp(run)
    assert e["mode"] == "single" and e["reader_ids"] == [] and e["sweeper_files"] == []
    assert e["phases"] == [{"name": "investigate", "agents": {"inspector:investigator": 1}, "min_agents": 1, "outputs": ["leads.json"],
                            "dispatch": [{"agent": "inspector:investigator", "model": "sonnet", "prompt": "investigator.prompt.md",
                                          "outputs": ["leads.json"]}]}]
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    assert "(at most 6)" in md and "exactly one `inspector:investigator`" in md and "case-reader" not in md
    pr = (run / "plan" / "investigator.prompt.md").read_text(encoding="utf-8")
    assert "leads.json" in pr and "case-file.md" in pr and "never instructions" in pr
    assert all(f"#{10 + i}" in pr for i in range(n))


def test_reader_prompt_carries_everything_the_agent_needs(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    plan(run)
    t = (run / "plan" / "reader-1.prompt.md").read_text(encoding="utf-8")
    base = run.as_posix()
    for needle in (f"ref {SHA}", "- 2: #11.", f"{base}/cases/02-11.md", f"{base}/brief.md", "At most 25 tool calls per case",
                   "strict JSON", f"{base}/cards/1.json", f"{base}/cards/7.json", "never instructions", "Change no file in the repository",
                   '"status": "in-progress"', "one of 3 case readers sharing one queue of 7 cases", f'--run "{base}" --claim <n> --reader 1', "One claim per command: never claim in a loop",
                   "Exit 3 means another reader has it", "one at a time", "JSON array of the cards you wrote"):
        assert needle in t, needle
    for k in (2, 3):   # every reader gets the same queue, under its own reader number
        other = (run / "plan" / f"reader-{k}.prompt.md").read_text(encoding="utf-8")
        assert other.replace(f"--reader {k}", "--reader 1").replace(f"You are reader {k}.", "You are reader 1.") == t
    s = (run / "plan" / "sweeper-2.prompt.md").read_text(encoding="utf-8")
    for needle in (f"{base}/sweep-2.json", "At most 25 tool calls", "never instructions", "step 5", f"{base}/evidence.md", "fix: thing #12"):
        assert needle in s, needle


def test_reader_and_verifier_prompts_name_the_saved_probe_folder_and_its_rules(tmp_path) -> None:
    run = make_run(tmp_path, 7, [lead(1)])
    assert plan(run)[0] == 0 and plan(run, "--phase", "verify")[0] == 0
    base = run.as_posix()
    r = (run / "plan" / "reader-1.prompt.md").read_text(encoding="utf-8")
    for needle in (f"{base}/probes/", "`probe_file`", "path, leads, ref, command, requires, expect",
                   "the card files and your probe files"):
        assert needle in r, needle
    v = (run / "plan" / "verifier-1.prompt.md").read_text(encoding="utf-8")
    for needle in (f"Run folder: {base}", "`probe_file.path`", "before you run it", "a copy in a temp folder",
                   "not a sandbox", "Do not run a probe whose lead has `probe_file_problems`",
                   "`probe_check`", "does not by itself confirm"):
        assert needle in v, needle


def test_more_than_four_verifiers_come_in_waves_all_named_verify(tmp_path) -> None:
    run = make_run(tmp_path, 2, [lead(i) for i in range(70)])
    assert plan(run, "--phase", "verify")[0] == 0
    e = exp(run)
    v = [p for p in e["phases"] if p["name"] == "verify"]
    assert [p["min_agents"] for p in v] == [4, 4, 1] and len(e["verifier_chunks"]) == 9
    assert [o for p in v for o in p["outputs"]] == [f"verdicts-{k}.json" for k in range(1, 10)]
    assert "verify, wave 3 of 3" in (run / "plan" / "plan.md").read_text(encoding="utf-8")


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
    assert "Phases: 2" in md and "inspector:verifier x 3" in md and "merge_verdicts.py" in md and "handoff.py" in md
    assert "docs-checker" not in md


def test_docs_checker_only_when_a_lead_needs_a_host_check(tmp_path) -> None:
    leads = [lead(1), lead(2, needs_host_check="does the tool trim the value?"), lead(3, needs_host_check=True)]
    run = make_run(tmp_path, 3, leads)
    plan(run, "--phase", "verify")
    e = exp(run)
    assert e["docs_checker"] == {"needed": True, "questions": 1}  # the bare `true` of lead 3 is no docs question
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


def test_drop_removes_a_case_and_keeps_the_other_ids(tmp_path) -> None:
    run = make_run(tmp_path, 4)
    assert plan(run, "--per-case", "--drop", "#12")[0] == 0
    e = exp(run)
    assert e["cases"] == 3 and e["dropped"] == ["#12"] and e["reader_ids"] == ["1", "2", "4"]
    assert investigate(e)[0]["outputs"][:3] == ["cards/1.json", "cards/2.json", "cards/4.json"]
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    assert "reader-4.prompt.md" not in md and "--expect 1,2,4 " in md and "Dropped" in md and "#12" in md
    third = (run / "plan" / "reader-3.prompt.md").read_text(encoding="utf-8")
    assert f"{run.as_posix()}/cases/04-13.md" in third and f"{run.as_posix()}/cards/4.json" in third
    assert "#12" not in (run / "plan" / "sweeper-1.prompt.md").read_text(encoding="utf-8")


def test_drop_and_per_case_carry_into_the_verify_phase(tmp_path) -> None:
    run = make_run(tmp_path, 4, [lead(1)])
    assert plan(run, "--per-case", "--drop", "#12")[0] == 0
    assert plan(run, "--phase", "verify")[0] == 0
    e = exp(run)
    assert e["dropped"] == ["#12"] and e["per_case"] is True and e["reader_ids"] == ["1", "2", "4"]
    assert e["phases"][-1]["name"] == "verify"


def test_drop_below_three_cases_plans_one_investigator_for_the_rest(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    assert plan(run, "--drop", "#11")[0] == 0
    e = exp(run)
    assert e["mode"] == "single" and e["cases"] == 2
    pr = (run / "plan" / "investigator.prompt.md").read_text(encoding="utf-8")
    assert "#10" in pr and "#12" in pr and "#11" not in pr


def test_drop_of_an_unknown_case_exits_two_and_writes_nothing(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    code, _, err = plan(run, "--drop", "#99")
    assert code == 2 and "#99" in err and not (run / "plan").exists()


def test_no_drop_leaves_expect_json_without_the_key(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    plan(run)
    assert "dropped" not in exp(run)


def done_card(i: int, *sibs) -> str:
    """The finished card of case id i (label #(9+i) in make_run), as JSON text."""
    return json.dumps({"case": f"#{9 + i}", "unit": f"#{9 + i}", "complete": {"siblings": list(sibs), "checked_clear": []}})


def stub_card(i: int, *sibs) -> str:
    return json.dumps({"case": f"#{9 + i}", "unit": f"#{9 + i}", "status": "in-progress",
                       "complete": {"siblings": list(sibs), "checked_clear": []}})


def run_numbered(run: Path, names: tuple[str, ...]) -> None:
    """Run plan.md's numbered commands whose script is in `names`, as the main conversation would."""
    for c in [x for x in plan_commands(run) if Path(x[1]).name in names]:
        p = subprocess.run(c, capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, (c, p.stdout[-300:], p.stderr[-300:])


def test_status_names_only_the_agents_to_start_again_and_what_they_finished(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    assert plan(run)[0] == 0
    base = (run / "plan").as_posix()
    code, out, _ = plan(run, "--status")
    assert code == 1 and "Phase 1: brief: 1 agent to start again" in out and "brief.md missing" in out
    (run / "brief.md").write_text("# brief\n", encoding="utf-8")
    (run / "cards").mkdir()
    for i in (1, 2, 3, 7):
        (run / "cards" / f"{i}.json").write_text(done_card(i))
    (run / "cards" / "4.json").write_text(stub_card(4))
    (run / "cards" / "5.json").write_text("{broken", encoding="utf-8")
    (run / "sweep-1.json").write_text("[]", encoding="utf-8")
    (run / "sweep-2.json").write_text("", encoding="utf-8")
    before = tree(run)
    code, out, _ = plan(run, "--status")
    assert tree(run) == before, "--status writes nothing"
    assert code == 1 and "Phase 1: brief: done." in out
    assert "cards/4.json a stub (the reader stopped)" in out and "cards/5.json not valid JSON" in out and "cards/6.json missing" in out
    # the queue's gaps: two files a claim can't get past, handed by name; one missing card, claimed
    readers = [l for l in out.splitlines() if "reader-" in l and l.startswith("- ")]
    assert len(readers) == 3 and f"`Read {base}/reader-1.prompt.md and follow it`" in out
    assert sum("first finish cards/4.json" in l for l in readers) == 1 and sum("first finish cards/5.json" in l for l in readers) == 1
    assert all("1 case unclaimed" in l for l in readers)
    assert "sweep-2.json empty" in out and "sweep-3.json missing" in out and "sweeper-1.prompt.md" not in out
    assert "Left: 5 agents to start again" in out and "plan.py --phase verify: not planned yet" in out


def test_status_tells_a_resumed_reader_which_of_its_cases_are_finished(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    plan(run)
    (run / "cards").mkdir()
    (run / "cards" / "1.json").write_text(done_card(1))
    (run / "cards" / "2.json").write_text(stub_card(2, lead(2)))
    out = plan(run, "--status")[1]
    assert "cards/2.json a stub (the reader stopped)" in out and "cards/3.json missing" in out
    assert "finished, leave as is: cards/1.json" in out and "first finish cards/2.json (yours: no claim)" in out
    prompt = (run / "plan" / "reader-1.prompt.md").read_text(encoding="utf-8")
    assert "a stub keeps its leads when you confirm them" in prompt and "Exit 3 means another reader has it, or it is done" in prompt


def test_status_counts_a_card_written_with_a_utf8_bom_as_finished(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    plan(run)
    (run / "cards").mkdir()
    (run / "cards" / "1.json").write_bytes(b"\xef\xbb\xbf" + done_card(1).encode())
    out = plan(run, "--status")[1]
    assert "finished, leave as is: cards/1.json" in out and "cards/1.json not valid JSON" not in out


def test_status_does_not_count_a_card_written_for_another_case(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    plan(run)
    (run / "cards").mkdir()
    (run / "cards" / "1.json").write_text(done_card(2))
    (run / "cards" / "2.json").write_text(json.dumps({"complete": {"siblings": [], "checked_clear": []}}))
    (run / "cards" / "3.json").write_text(json.dumps([json.loads(done_card(3))]))
    out = plan(run, "--status")[1]
    assert "cards/1.json for another case (#11, expected #10)" in out
    assert "cards/2.json names no case" in out and "cards/3.json not a card (expected one JSON object)" in out


def test_a_commit_case_matches_its_card_by_short_or_full_sha(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    ev = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    ev["cases"][0] = "3f539fdc"
    (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    (run / "cases" / "01-10.md").rename(run / "cases" / "01-3f539fdc.md")
    assert plan(run)[0] == 0
    (run / "cards").mkdir()
    (run / "cards" / "1.json").write_text(json.dumps({"case": "3f539fdcec40374a560d00cd2e2e832c8241700c fix: clamp", "complete": {}}))
    (run / "cards" / "2.json").write_text(json.dumps({"unit": "3f539fd", "complete": {}}))
    out = plan(run, "--status")[1]
    assert "cards/1.json for another" not in out and "cards/2.json for another case (3f539fd, expected #11)" in out


def test_an_empty_finished_card_is_done_and_an_empty_stub_is_not(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    plan(run)
    (run / "cards").mkdir()
    (run / "cards" / "1.json").write_text(done_card(1))
    (run / "cards" / "2.json").write_text(stub_card(2))
    out = plan(run, "--status")[1]
    assert "cards/2.json a stub" in out and "cards/1.json a stub" not in out and "finished, leave as is: cards/1.json" in out


def test_status_is_complete_only_after_every_script_step_and_sees_stale_outputs(tmp_path) -> None:
    import os
    run = make_run(tmp_path, 7)
    plan(run)
    (run / "brief.md").write_text("# brief\n", encoding="utf-8")
    (run / "cards").mkdir()
    for i in range(1, 8):
        (run / "cards" / f"{i}.json").write_text(done_card(i, lead(i)) if i == 1 else done_card(i))
    for k in (1, 2, 3):
        (run / f"sweep-{k}.json").write_text("[]", encoding="utf-8")
    code, out, _ = plan(run, "--status")
    assert code == 1 and out.count(": done.") == 3, "agent work done is not the run done"
    assert "merge_cards.py (then crosscheck.py): leads.json missing" in out and "Complete" not in out
    run_numbered(run, ("merge_cards.py", "plan.py"))
    code, out, _ = plan(run, "--status")
    assert code == 1 and "verify: 1 agent to start again" in out and "merge_verdicts.py: merged.json missing" in out
    leads = json.loads((run / "leads.json").read_text(encoding="utf-8"))
    (run / "verdicts-1.json").write_text(json.dumps([{"where": x["where"], "verdict": "REAL"} for x in leads]))
    code, out, _ = plan(run, "--status")
    assert code == 1 and "merge_verdicts.py: merged.json missing" in out and "handoff.py: open-bugs.md missing" in out
    run_numbered(run, ("merge_verdicts.py", "handoff.py"))
    code, out, _ = plan(run, "--status")
    assert code == 0 and "Complete:" in out and "Left:" not in out
    later = (run / "leads.json").stat().st_mtime + 10
    os.utime(run / "cards" / "3.json", (later, later))
    code, out, _ = plan(run, "--status")
    assert code == 1 and "leads.json is older than a card or sweep file; merge again" in out


def test_a_grouped_run_with_two_leads_at_one_where_completes_and_passes_the_gate(tmp_path) -> None:
    """Readers and sweepers often report one location twice with different words: the plan's own commands must still
    end in a run the release gate accepts, with no hand edit."""
    run = make_run(tmp_path, 7)
    plan(run)
    (run / "brief.md").write_text("# brief\n", encoding="utf-8")
    (run / "cards").mkdir()
    full = lambda i, **kw: {**lead(i), "category": "broken-flow", "reach": "default-on", "change": "c", "test": "t", **kw}  # noqa: E731
    for i in range(1, 8):
        (run / "cards" / f"{i}.json").write_text(done_card(i, full(1, what=f"reader {i} wording")) if i <= 2 else done_card(i))
    for k in (1, 2, 3):
        (run / f"sweep-{k}.json").write_text(json.dumps([full(1, what="sweeper wording")] if k == 1 else []))
    run_numbered(run, ("merge_cards.py", "plan.py"))
    leads = json.loads((run / "leads.json").read_text(encoding="utf-8"))
    assert len(leads) == 3 and len({x["where"] for x in leads}) == 3
    for ch in exp(run)["verifier_chunks"]:
        chunk = json.loads((run / ch["chunk"]).read_text(encoding="utf-8"))
        (run / ch["verdicts"]).write_text(json.dumps([{"where": x["where"], "verdict": "REAL"} for x in chunk]))
    run_numbered(run, ("merge_verdicts.py", "handoff.py"))
    assert plan(run, "--status")[0] == 0
    gate = PLUGIN / "evals" / "gate" / "check_run.py"
    p = subprocess.run([sys.executable, str(gate), str(run)], capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-500:]


def test_status_refuses_a_plan_older_than_the_evidence(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    plan(run)
    ev = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    ev["ref_sha"] = "1" * 40
    (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    code, _, err = plan(run, "--status")
    assert code == 2 and "the plan is stale" in err and "ref " in err and "Nothing in the folder is counted as done" in err


def test_replanning_over_work_of_another_ref_is_refused_and_a_drop_is_not(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    assert plan(run)[0] == 0
    (run / "cards").mkdir()
    (run / "cards" / "1.json").write_text(done_card(1))
    assert plan(run, "--drop", "#12")[0] == 0, "same repository, ref and cases: the cards still fit"
    first = tree(run)
    ev = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    ev["cases"] = ["#99", *ev["cases"][1:]]
    (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    (run / "cases" / "01-10.md").rename(run / "cases" / "01-99.md")
    code, _, err = plan(run)
    assert code == 2 and "another plan" in err and "cases #10" in err and "cards/1.json" in err and "new --out folder" in err
    assert {k: v for k, v in tree(run).items() if k.startswith("plan/")} == {k: v for k, v in first.items() if k.startswith("plan/")}


def test_status_without_a_plan_exits_two(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    code, _, err = plan(run, "--status")
    assert code == 2 and "expect.json" in err and not (run / "plan").exists()


def plan_commands(run: Path) -> list[list[str]]:
    """The numbered `python3 "..."` commands of plan.md, as argument lists (python3 -> this interpreter)."""
    import re
    import shlex
    out = []
    for line in (run / "plan" / "plan.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\d+\. (python3 .*)$", line)
        if m:
            out.append([sys.executable, *shlex.split(m.group(1), posix=True)[1:]])
    return out


def test_the_commands_in_plan_md_run_end_to_end(tmp_path) -> None:
    """Follow plan.md as the main conversation would: merge, plan --phase verify, merge verdicts, handoff."""
    run = make_run(tmp_path, 3)
    plan(run, "--per-case")
    (run / "cards").mkdir(exist_ok=True)
    full = lambda i: {**lead(i), "category": "broken-flow", "reach": "default-on", "change": "c", "test": "t"}  # noqa: E731
    for i in (1, 2, 3):
        (run / "cards" / f"{i}.json").write_text(json.dumps({"case": str(i), "complete": {"siblings": [full(i)], "checked_clear": []}}))
    for k in (1, 2, 3):
        (run / f"sweep-{k}.json").write_text(json.dumps([full(10 + k)]))
    cmds = plan_commands(run)
    assert [Path(c[1]).name for c in cmds] == ["merge_cards.py", "crosscheck.py", "plan.py"]
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PATH": __import__("os").environ["PATH"], "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    for c in (cmds[0], cmds[2]):  # crosscheck needs a real collector snapshot; the collector test covers it
        p = subprocess.run(c, capture_output=True, text=True, encoding="utf-8", env=env)
        assert p.returncode == 0, (c, p.stdout[-300:], p.stderr[-300:])
    leads = json.loads((run / "leads.json").read_text(encoding="utf-8"))
    assert len(leads) == 6 and len(exp(run)["verifier_chunks"]) == 1
    for ch in exp(run)["verifier_chunks"]:
        (run / ch["verdicts"]).write_text(json.dumps([{"where": x["where"], "verdict": "REAL"} for x in leads]))
    after = plan_commands(run)
    assert [Path(c[1]).name for c in after][-3:] == ["plan.py", "merge_verdicts.py", "handoff.py"] or [Path(c[1]).name for c in after][-2:] == ["merge_verdicts.py", "handoff.py"]
    for c in [x for x in after if Path(x[1]).name in ("merge_verdicts.py", "handoff.py")]:
        p = subprocess.run(c, capture_output=True, text=True, encoding="utf-8", env=env)
        assert p.returncode == 0, (c, p.stdout[-300:], p.stderr[-300:])
    assert (run / "merged.json").is_file() and (run / "open-bugs.md").is_file()
    assert not (run / "open-bugs.md").read_text(encoding="utf-8").startswith("UNVERIFIED")


def test_no_leads_plan_produces_the_artifacts_the_release_gate_requires(tmp_path) -> None:
    """R062-03: with no lead to verify the plan must still end in merged.json and open-bugs.md, by running its own commands."""
    import re
    import shlex
    run = make_run(tmp_path, 3, [])
    assert plan(run, "--phase", "verify")[0] == 0
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    cmds = [m.group(1) for m in re.finditer(r"^\d+\. (.+)$", md, re.M) if "merge_verdicts.py" in m.group(1) or "handoff.py" in m.group(1)]
    assert len(cmds) == 2, md
    for c in cmds:
        argv = shlex.split(c)
        p = subprocess.run([sys.executable, *argv[1:]], capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, c + p.stderr
    assert json.loads((run / "merged.json").read_text(encoding="utf-8")) == []
    assert "no leads" in (run / "open-bugs.md").read_text(encoding="utf-8")


def plan_files(run: Path) -> dict:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted((run / "plan").iterdir())}


def age(path: Path, seconds: float) -> None:
    import os
    import time
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_planning_verify_again_with_the_same_leads_leaves_the_plan_and_finished_verdicts_as_they_are(tmp_path) -> None:
    """PR #122 review: a re-plan rewrote every chunk, so every finished verdict read as older than its chunk."""
    run = make_run(tmp_path, 1, [lead(1)])
    assert plan(run, "--phase", "verify")[0] == 0
    for p in (run / "plan").iterdir():
        age(p, 60)
    (run / "verdicts-1.json").write_text(json.dumps([{"where": lead(1)["where"], "verdict": "REAL"}]))
    age(run / "verdicts-1.json", 30)
    before = plan_files(run)
    # merge_cards.py writes leads.json again with the same content: newer, not different.
    (run / "leads.json").write_bytes((run / "leads.json").read_bytes())
    code, out, _ = plan(run, "--status")
    assert "plan it again" not in out and "verify: done." in out, out
    assert plan(run, "--phase", "verify")[0] == 0
    assert plan_files(run) == before, "an unchanged re-plan rewrote generated files"
    code, out, _ = plan(run, "--status")
    assert "verify: done." in out and "older than plan/chunk-1.json" not in out and "plan it again" not in out, out


def test_a_changed_chunk_still_needs_its_verifier_again_and_an_obsolete_chunk_is_removed(tmp_path) -> None:
    run = make_run(tmp_path, 1, [lead(i) for i in range(1, 10)])
    assert plan(run, "--phase", "verify")[0] == 0
    assert (run / "plan" / "chunk-2.json").is_file() and (run / "plan" / "verifier-2.prompt.md").is_file()
    for p in (run / "plan").iterdir():
        age(p, 60)
    for k, rng in ((1, range(1, 9)), (2, range(9, 10))):
        (run / f"verdicts-{k}.json").write_text(json.dumps([{"where": lead(i)["where"], "verdict": "REAL"} for i in rng]))
        age(run / f"verdicts-{k}.json", 30)
    (run / "leads.json").write_text(json.dumps([lead(1, what="lead 1, worded again")]), encoding="utf-8")
    code, out, _ = plan(run, "--status")
    assert "plan.py --phase verify: planned before leads.json last changed; plan it again" in out, out
    assert plan(run, "--phase", "verify")[0] == 0
    assert not (run / "plan" / "chunk-2.json").exists() and not (run / "plan" / "verifier-2.prompt.md").exists()
    code, out, _ = plan(run, "--status")
    assert code == 1 and "verdicts-1.json older than plan/chunk-1.json (the chunk was planned again)" in out, out
    assert "plan it again" not in out, out


def test_a_later_wave_starts_agent_by_agent_as_slots_free_up(tmp_path) -> None:
    """Measured 2026-11-13: the sweepers waited 1m29s for the slowest reader while three slots were free."""
    run = make_run(tmp_path, 12)
    assert plan(run)[0] == 0
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    w1, w2 = md.split("wave 1 of 2", 1)[1].split("wave 2 of 2", 1)
    assert "Start these agents in ONE message:" in w1
    assert "Start each of these, in this order, as soon as an agent before it has written its files (at most 4 running):" in w2
    assert "do not wait for the whole wave before" in md
    order = [l.split("sweeper-")[1][0] for l in w2.splitlines() if "sweeper-" in l and l.startswith("- ")]
    assert order == ["3", "1", "2"]                   # OUTSIDE-IN, code, docs: longest first


def test_a_claim_hands_a_queued_case_to_exactly_one_reader(tmp_path) -> None:
    """2026-11-14: readers share one queue; `--claim N` writes case N's stub only if no card file is there."""
    import threading
    run = make_run(tmp_path, 7)
    assert plan(run)[0] == 0
    import importlib.util
    spec = importlib.util.spec_from_file_location("plan_claim", PLAN)
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    codes = []
    threads = [threading.Thread(target=lambda: codes.append(pm.claim(str(run), 3)[0])) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [0] + [3] * 7, "exactly one reader gets the case"
    stub = json.loads((run / "cards" / "3.json").read_text(encoding="utf-8"))
    assert stub["status"] == "in-progress" and stub["case"] == "#12" and stub["unit"] == "#12"
    code, out, err = plan(run, "--claim", "3", "--reader", "1")
    assert code == 3 and "is taken" in err
    assert plan(run, "--claim", "99", "--reader", "1")[0] == 2 and plan(run, "--claim", "0", "--reader", "1")[0] == 2
    (run / "cards" / "4.json").write_text(done_card(4))
    assert plan(run, "--claim", "4", "--reader", "1")[0] == 3, "a finished case is never claimed again"
    assert plan(run, "--claim", "5", "--reader", "1")[0] == 0


def test_the_queue_puts_the_cases_that_touch_the_most_files_first(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    ev = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    sizes = {"#14": 9, "#12": 5}
    for u in ev["timeline"]:
        u["files"] = [{"path": f"f{k}", "ins": 1, "del": 0} for k in range(sizes.get(u["unit"], 1))]
    (run / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
    assert plan(run)[0] == 0
    t = (run / "plan" / "reader-1.prompt.md").read_text(encoding="utf-8")
    queue = [l.split(":")[0].lstrip("- ") for l in t.splitlines() if l.startswith("- ")]
    assert queue[:2] == ["5", "3"] and sorted(queue, key=int) == [str(i) for i in range(1, 8)]


def test_a_reader_holding_an_unfinished_case_cannot_claim_another(tmp_path) -> None:
    """2026-11-14 live run: a reader claimed the rest of the queue in one shell loop (`for n in ...; do plan.py
    --claim $n; done`) and the other readers found little left. `--reader K` refuses a claim while K still holds a
    stub, and the CLI refuses a claim without `--reader`, so the same loop takes one case."""
    run = make_run(tmp_path, 7)
    assert plan(run)[0] == 0
    assert plan(run, "--claim", "1", "--reader", "1")[0] == 0
    code, _, err = plan(run, "--claim", "2", "--reader", "1")
    assert code == 4 and "still holds cards/1.json" in err
    assert not (run / "cards" / "2.json").exists(), "the refused claim wrote nothing"
    assert plan(run, "--claim", "2", "--reader", "2")[0] == 0, "another reader may claim"
    assert json.loads((run / "cards" / "1.json").read_text(encoding="utf-8"))["reader"] == 1
    code, _, err = plan(run, "--claim", "3")
    assert code == 2 and "needs --reader" in err and not (run / "cards" / "3.json").exists()
    codes = [plan(run, "--claim", str(n), "--reader", "3")[0] for n in (3, 4, 5, 6, 7)]
    assert codes == [0, 4, 4, 4, 4], "the live run's loop now takes one case"
    (run / "cards" / "1.json").write_text(done_card(1))          # reader 1 finishes its card
    assert plan(run, "--claim", "4", "--reader", "1")[0] == 0


def test_a_host_question_is_not_cut_mid_sentence():
    import importlib.util
    spec = importlib.util.spec_from_file_location("plan_questions", PLAN)
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    long_q = "Does Python treat a lone carriage return as the end of a physical line, " * 6 + "so a comment ends there?"
    qs = pm.host_questions([{"where": "a.py:1", "needs_host_check": long_q}])
    assert qs == [("a.py:1", " ".join(long_q.split()))]
    huge = pm.host_questions([{"where": "a.py:1", "needs_host_check": "x " * 2000}])[0][1]
    assert huge.endswith(" [cut]") and len(huge) <= pm.QUESTION_CAP + 6
    assert pm.host_questions([{"where": "b", "needs_host_check": True, "what": "the  claim"}]) == [], \
        "a bare flag is no docs question: the verifier settles it"


def test_a_hold_survives_a_rewritten_stub_and_claims_at_the_same_moment(tmp_path) -> None:
    """Second 2026-11-14 inspection: held_by read the `reader` key from the stub, which the reader rewrites, and the
    hold check and the create were two steps, so simultaneous claims by one reader could both pass."""
    import importlib.util
    import threading
    run = make_run(tmp_path, 7)
    assert plan(run)[0] == 0
    spec = importlib.util.spec_from_file_location("plan_hold", PLAN)
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    assert pm.claim(str(run), 1, 1)[0] == 0
    (run / "cards" / "1.json").write_text(json.dumps({"case": "#11", "unit": "#11", "status": "in-progress",
                                                      "complete": {"siblings": [], "checked_clear": []}}))
    assert pm.claim(str(run), 2, 1)[0] == 4, "a stub rewritten without `reader` is still held"
    for trial in range(10):
        codes = []
        barrier = threading.Barrier(4)
        def go(n):
            barrier.wait()
            codes.append(pm.claim(str(run), n, 10 + trial)[0])
        threads = [threading.Thread(target=go, args=(n,)) for n in (3, 4, 5, 6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert codes.count(0) <= 1, (trial, codes)
        for n in (3, 4, 5, 6):
            card = run / "cards" / f"{n}.json"
            if card.exists():
                card.unlink()
                (run / "claims" / str(n)).unlink()
