"""Three things a live run on Windows (2026-11-16) showed: one defect listed two and three times because its `where`
was an absolute path in one lead and a relative one in the next; verdicts merged before the last verifier had finished;
verifiers inventing categories. No network, no agents."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

import leadsio  # noqa: E402
import merge_cards  # noqa: E402
import merge_verdicts  # noqa: E402
import plan as plan_mod  # noqa: E402
from test_plan import lead as plan_lead, make_run, plan  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
ROOT = "C:/Users/amit/work/clone"
A = "the matcher is Bash only, so git commands run through PowerShell are never captured"
B = "matcher covers Bash but not PowerShell; a git reset typed there is missed"


def lead(where, what, level="read", **kw):
    return {"where": where, "what": what, "level": level, "category": "broken-flow", "reach": "conditional", "found_by": "x", **kw}


# ---------------------------------------------------------------- absolute and relative `where`
@pytest.mark.parametrize("written", [
    "C:/Users/amit/work/clone/.claude/skills/mb/../../settings.json:6",
    "C:\\Users\\amit\\work\\clone\\.claude\\settings.json:6",
    "c:/users/amit/work/clone/.claude/settings.json:6",            # a drive letter and folders in another case
    "./.claude/settings.json:6",
    ".claude/skills/../settings.json:6"])
def test_the_same_line_written_as_another_path_is_compared(written) -> None:
    final, merges, possible = merge_cards.dedupe([lead(written, A), lead(".claude/settings.json:6", B)], root=ROOT)
    assert len(final) == 2 and len(possible) == 1 and possible[0][3] == merge_cards.OVERLAP
    assert final[0]["where"] == written, "the lead keeps the `where` its author wrote"


def test_without_a_root_an_absolute_path_is_still_its_own_file() -> None:
    final, merges, possible = merge_cards.dedupe([lead(f"{ROOT}/.claude/settings.json:6", A), lead(".claude/settings.json:6", B)])
    assert possible == []


def test_exact_duplicates_merge_across_the_two_spellings() -> None:
    final, merges, _ = merge_cards.dedupe([lead(f"{ROOT}/src/a.py:10", A), lead("src/a.py:10", A)], root=ROOT)
    assert len(final) == 1 and len(merges) == 1


def test_a_path_outside_the_repository_is_not_mistaken_for_one_inside() -> None:
    final, _, possible = merge_cards.dedupe([lead("C:/Users/amit/work/other/src/a.py:10", A), lead("src/a.py:10", B)], root=ROOT)
    assert possible == [] and len(final) == 2


def test_a_function_name_with_a_drive_letter_pairs_with_a_line_in_that_file() -> None:
    final, _, possible = merge_cards.dedupe([lead(f"{ROOT}/hooks/register_pair.py:_write_atomic", A), lead("hooks/register_pair.py:77", B)], root=ROOT)
    assert len(possible) == 1 and possible[0][3] == merge_cards.NOLINE


def test_merge_cards_reads_the_root_from_the_runs_evidence(tmp_path, capsys) -> None:
    run = tmp_path / "run"
    (run / "cards").mkdir(parents=True)
    (run / "evidence.json").write_text(json.dumps({"repo_path": ROOT, "ref_sha": "a" * 40}), encoding="utf-8")
    card = {"case": "#1", "complete": {"siblings": [{k: v for k, v in lead(f"{ROOT}/.claude/settings.json:6", A).items() if k != "found_by"}]}}
    (run / "cards" / "1.json").write_text(json.dumps(card), encoding="utf-8")
    (run / "sweep-1.json").write_text(json.dumps([{k: v for k, v in lead(".claude/settings.json:6", B).items() if k != "found_by"}]), encoding="utf-8")
    assert merge_cards.main(["--cards", str(run / "cards"), "--sweep", str(run / "sweep-1.json"), "--expect", "1",
                             "--out", str(run / "leads.json"), "--log", str(run / "dedupe.md")]) == 0
    assert "possible duplicates: 1" in capsys.readouterr().out
    leads = json.loads((run / "leads.json").read_text(encoding="utf-8"))
    assert leads[0]["possible_duplicate_of"] == [".claude/settings.json:6"]


# ---------------------------------------------------------------- merging before every verifier has finished
def verify_run(tmp_path: Path, n: int = 11) -> Path:
    run = make_run(tmp_path, 2, [plan_lead(i) for i in range(1, n + 1)])       # 11 leads: chunks of 8 and 3
    assert plan(run, "--phase", "verify")[0] == 0
    return run


def verdicts(run: Path, k: int, ids) -> str:
    p = run / f"verdicts-{k}.json"
    p.write_text(json.dumps([{"where": plan_lead(i)["where"], "verdict": "REAL"} for i in ids]), encoding="utf-8")
    return str(p)


def test_merging_while_a_planned_chunk_has_no_verdict_file_is_refused(tmp_path, capsys) -> None:
    run = verify_run(tmp_path)
    v1 = verdicts(run, 1, range(1, 9))
    rc = merge_verdicts.main(["--leads", str(run / "leads.json"), "--verdicts", v1, "--out", str(run / "merged.json")])
    err = capsys.readouterr().err
    assert rc == 2 and "verdicts-2.json" in err and "--partial" in err
    assert not (run / "merged.json").exists(), "nothing is written"


def test_a_planned_file_that_exists_but_was_not_passed_is_refused_too(tmp_path, capsys) -> None:
    run = verify_run(tmp_path)
    v1 = verdicts(run, 1, range(1, 9))
    verdicts(run, 2, range(9, 12))
    rc = merge_verdicts.main(["--leads", str(run / "leads.json"), "--verdicts", v1, "--out", str(run / "merged.json")])
    assert rc == 2 and "verdicts-2.json" in capsys.readouterr().err


def test_every_planned_file_passed_merges_and_partial_overrides(tmp_path, capsys) -> None:
    run = verify_run(tmp_path)
    v1, v2 = verdicts(run, 1, range(1, 9)), verdicts(run, 2, range(9, 12))
    assert merge_verdicts.main(["--leads", str(run / "leads.json"), "--verdicts", v1, v2, "--out", str(run / "merged.json")]) == 0
    assert all(x["verdict"] == "REAL" for x in json.loads((run / "merged.json").read_text(encoding="utf-8")))
    (run / "verdicts-2.json").unlink()
    assert merge_verdicts.main(["--leads", str(run / "leads.json"), "--verdicts", v1, "--out", str(run / "m2.json"), "--partial"]) == 0
    assert "merging what exists" in capsys.readouterr().err
    assert [x["verdict"] for x in json.loads((run / "m2.json").read_text(encoding="utf-8"))].count("unverified") == 3


def test_leads_with_no_plan_beside_them_merge_as_before(tmp_path, capsys) -> None:
    (tmp_path / "l.json").write_text(json.dumps([plan_lead(1), plan_lead(2)]), encoding="utf-8")
    (tmp_path / "v.json").write_text(json.dumps([{"where": plan_lead(1)["where"], "verdict": "REAL"}]), encoding="utf-8")
    assert merge_verdicts.main(["--leads", str(tmp_path / "l.json"), "--verdicts", str(tmp_path / "v.json"), "--out", str(tmp_path / "m.json")]) == 0


# ---------------------------------------------------------------- the verifier is told the allowed labels
def test_the_verifier_prompt_and_agent_file_name_the_allowed_labels(tmp_path) -> None:
    run = verify_run(tmp_path, 3)
    prompt = (run / "plan" / "verifier-1.prompt.md").read_text(encoding="utf-8")
    agent = (PLUGIN / "agents" / "verifier.md").read_text(encoding="utf-8")
    for text in (prompt, agent):
        assert ", ".join(f"`{c}`" for c in leadsio.CATEGORIES) in text
    assert "`other`" in prompt and "docs" in prompt and "test gap" in prompt       # where a docs or test gap goes
    assert ", ".join(f"`{r}`" for r in leadsio.REACHES) in prompt
    assert plan_mod.CATEGORIES == leadsio.CATEGORIES and plan_mod.REACHES == leadsio.REACHES
