"""Tests for evals/gate/check_run.py on synthetic run folders (nothing here touches a real run)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).parent.parent / "evals" / "gate"
CHECK = GATE / "check_run.py"
PROFILE = GATE / "profile.json"

ALL = ["artifacts.present", "artifacts.valid_json", "leads.source", "inputs.match_log_raw", "leads.count",
       "verdicts.no_orphans", "verdicts.coverage", "merged.matches_leads", "handoff.counts"]


def lead(where, what="something breaks here", **kw):
    return {"where": where, "what": what, "level": "read", **kw}


def w(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def handoff(rows: int, banner: str = "") -> str:
    head = "| Level | Where |\n|---|---|\n"
    body = "".join(f"| read | `r{i}` |\n" for i in range(rows))
    return (banner + "\n\n" if banner else "") + "# Open bugs\n\n" + head + body


def build(tmp: Path, unverified: int = 0) -> Path:
    """Two cards (2 + 1 leads), two sweeps (2 + 3), one exact duplicate merged: 8 raw, 7 final."""
    run = tmp / "run"
    c1 = [lead("a.py:1"), lead("a.py:50")]
    c2 = [lead("b.py:1")]
    s1 = [lead("c.py:1"), lead("a.py:50")]  # duplicate of card 1's second lead
    s2 = [lead("d.py:1"), lead("e.py:1"), lead("f.py:1")]
    w(run / "cards" / "1.json", {"case": "1", "complete": {"siblings": c1}})
    w(run / "cards" / "2.json", {"case": "2", "complete": {"siblings": c2}})
    w(run / "sweep-1.json", s1)
    w(run / "sweep-2.json", s2)
    final = [{**c1[0], "found_by": "1"}, {**c1[1], "found_by": "1", "merged_from": ["a.py:50"]},
             {**c2[0], "found_by": "2"}, {**s1[0], "found_by": "sweeper"}] + [{**x, "found_by": "sweeper"} for x in s2]
    w(run / "leads.json", final)
    w(run / "dedupe.md", "# Dedupe log\n\n## Merges\n- 1 a.py:50 + sweeper a.py:50 (exact duplicate)\n\n"
      "## Possible duplicates (kept)\n- none\n\n## Counts\n- raw: 8\n- merged: 1\n- final: 7\n")
    wheres = [x["where"] for x in final]
    ver = [{"where": x, "verdict": "REAL"} for x in wheres[: len(wheres) - unverified]]
    w(run / "verdicts-1.json", ver[:3])
    w(run / "verdicts-2.json", ver[3:])
    merged = [{**x, "verdict": "REAL" if i < len(wheres) - unverified else "unverified"} for i, x in enumerate(final)]
    w(run / "merged.json", merged)
    banner = f"UNVERIFIED: {unverified} of 7 leads were not checked by an independent verifier; x." if unverified else ""
    w(run / "open-bugs.md", handoff(7, banner))
    return run


def run_check(run: Path, *extra):
    p = subprocess.run([sys.executable, str(CHECK), str(run), "--expect", "1,2", *extra], capture_output=True, text=True)
    try:
        rep = json.loads(p.stdout)
    except ValueError:
        rep = None
    return p.returncode, rep, p.stderr


def status(rep):
    return {i["id"]: i["status"] for i in rep["invariants"]}


def failing(rep):
    return sorted(k for k, v in status(rep).items() if v == "fail")


def test_good_run_passes(tmp_path):
    code, rep, _ = run_check(build(tmp_path))
    assert code == 0 and rep["ok"], rep
    assert list(status(rep)) == ALL and set(status(rep).values()) == {"pass"}


def test_report_has_evidence_per_invariant(tmp_path):
    _, rep, _ = run_check(build(tmp_path))
    assert all(i["evidence"] and set(i) == {"id", "status", "evidence"} for i in rep["invariants"])


def test_unverified_with_banner_passes(tmp_path):
    code, rep, _ = run_check(build(tmp_path, unverified=2))
    assert code == 0, rep


def test_unverified_without_banner_fails(tmp_path):
    run = build(tmp_path, unverified=2)
    w(run / "open-bugs.md", handoff(7))
    code, rep, _ = run_check(run)
    assert code == 1 and failing(rep) == ["verdicts.coverage"]


def test_banner_count_must_match(tmp_path):
    run = build(tmp_path, unverified=2)
    w(run / "open-bugs.md", handoff(7, "UNVERIFIED: 1 of 7 leads were not checked"))
    assert failing(run_check(run)[1]) == ["verdicts.coverage"]


def test_missing_card_fails_and_is_named(tmp_path):
    run = build(tmp_path)
    (run / "cards" / "2.json").unlink()
    code, rep, _ = run_check(run)
    assert code == 1 and "artifacts.present" in failing(rep)
    assert "cards/2.json" in next(i for i in rep["invariants"] if i["id"] == "artifacts.present")["evidence"]


def test_invalid_card_fails(tmp_path):
    run = build(tmp_path)
    w(run / "cards" / "1.json", '{"complete": {"siblings": [{"where": "a\\q"}]}}')  # invalid escape
    assert "artifacts.valid_json" in failing(run_check(run)[1])


def test_agent_files_with_a_utf8_bom_pass(tmp_path):
    run = build(tmp_path)
    for p in (run / "cards" / "1.json", run / "sweep-1.json", run / "verdicts-1.json"):
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    code, rep, _ = run_check(run)
    assert code == 0 and rep["ok"], rep


def test_nan_is_not_strict_json(tmp_path):
    run = build(tmp_path)
    w(run / "sweep-2.json", '[{"where": "d.py:1", "what": NaN}]')
    assert "artifacts.valid_json" in failing(run_check(run)[1])


def test_silent_drop_of_a_sweep_file_is_flagged_and_named(tmp_path):
    """leads.json and the log were produced from the cards and the last sweep only; sweep-1.json was dropped."""
    run = build(tmp_path)
    keep = [x for x in json.loads((run / "leads.json").read_text()) if x["where"] not in ("c.py:1",)]
    w(run / "leads.json", keep)
    log = (run / "dedupe.md").read_text().replace("- raw: 8", "- raw: 6").replace("## Merges\n- 1 a.py:50 + sweeper a.py:50 (exact duplicate)", "## Merges\n- none")
    w(run / "dedupe.md", log)
    code, rep, _ = run_check(run)
    assert code == 1
    ev = next(i for i in rep["invariants"] if i["id"] == "inputs.match_log_raw")
    assert ev["status"] == "fail" and "sweep-1.json" in ev["evidence"] and "inputs hold 8" in ev["evidence"]
    assert "leads.count" in failing(rep)


def test_leads_without_source_fail(tmp_path):
    run = build(tmp_path)
    leads = json.loads((run / "leads.json").read_text())
    leads[0]["where"] = "ghost.py:9"
    w(run / "leads.json", leads)
    assert "leads.source" in failing(run_check(run)[1])


def test_lead_count_mismatch_fails(tmp_path):
    run = build(tmp_path)
    w(run / "dedupe.md", (run / "dedupe.md").read_text().replace("- 1 a.py:50 + sweeper a.py:50 (exact duplicate)", "- none"))
    assert "leads.count" in failing(run_check(run)[1])


def test_orphan_verdict_fails(tmp_path):
    run = build(tmp_path)
    w(run / "verdicts-3.json", [{"where": "nowhere.py:1", "verdict": "REAL"}])
    assert failing(run_check(run)[1]) == ["verdicts.no_orphans"]


def test_merged_not_consistent_with_leads_fails(tmp_path):
    run = build(tmp_path)
    merged = json.loads((run / "merged.json").read_text())[:-1]
    w(run / "merged.json", merged)
    assert "merged.matches_leads" in failing(run_check(run)[1])


def test_not_real_may_be_dropped_from_merged(tmp_path):
    run = build(tmp_path)
    merged = json.loads((run / "merged.json").read_text())
    gone = merged.pop()["where"]
    w(run / "merged.json", merged)
    w(run / "verdicts-3.json", [{"where": gone, "verdict": "NOT REAL"}])
    w(run / "open-bugs.md", handoff(6))
    code, rep, _ = run_check(run)
    assert code == 0, rep


def test_handoff_row_count_mismatch_fails(tmp_path):
    run = build(tmp_path)
    w(run / "open-bugs.md", handoff(4))
    assert failing(run_check(run)[1]) == ["handoff.counts"]


def test_profile_expecting_a_missing_file_fails(tmp_path):
    run = build(tmp_path)
    prof = json.loads(PROFILE.read_text())
    prof["artifacts"]["timeline"] = {"path": "timeline.json", "required": True, "kind": "json"}
    p = tmp_path / "p.json"
    w(p, prof)
    code, rep, _ = run_check(run, "--profile", str(p))
    assert code == 1 and "artifacts.present" in failing(rep)


def test_override_renames_files(tmp_path):
    run = build(tmp_path)
    (run / "leads.json").rename(run / "leads-x.json")
    ov = tmp_path / "ov.json"
    w(ov, {"artifacts": {"leads": {"path": "leads-x.json"}}})
    assert run_check(run)[0] == 1  # default layout: leads.json missing
    code, rep, _ = run_check(run, "--override", str(ov))
    assert code == 0, rep


def test_dropped_invariant_is_not_run(tmp_path):
    run = build(tmp_path)
    prof = json.loads(PROFILE.read_text())
    prof["invariants"] = ["artifacts.present"]
    p = tmp_path / "p.json"
    w(p, prof)
    _, rep, _ = run_check(run, "--profile", str(p))
    assert list(status(rep)) == ["artifacts.present"]


def test_missing_inputs_are_skipped_not_failed(tmp_path):
    run = build(tmp_path)
    (run / "dedupe.md").unlink()
    _, rep, _ = run_check(run)
    s = status(rep)
    assert s["inputs.match_log_raw"] == s["leads.count"] == "skipped" and s["artifacts.present"] == "fail"


def test_exit_2_on_invalid_input(tmp_path):
    run = build(tmp_path)
    assert run_check(tmp_path / "nope")[0] == 2
    bad = tmp_path / "bad.json"
    w(bad, "{not json")
    assert run_check(run, "--profile", str(bad))[0] == 2
    unk = tmp_path / "unk.json"
    prof = json.loads(PROFILE.read_text())
    prof["invariants"].append("made.up")
    w(unk, prof)
    code, _, err = run_check(run, "--profile", str(unk))
    assert code == 2 and "made.up" in err
    ov = tmp_path / "ov.json"
    w(ov, [1])
    assert run_check(run, "--override", str(ov))[0] == 2


def snapshot(folder: Path):
    return sorted((str(p.relative_to(folder)), hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                  for p in folder.rglob("*") if p.is_file()), sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


def test_never_writes_inside_the_run_folder(tmp_path):
    for bad in (False, True):
        run = build(tmp_path / ("b" if bad else "g"), unverified=1 if bad else 0)
        if bad:
            (run / "cards" / "2.json").unlink()
        before = snapshot(run)
        run_check(run)
        assert snapshot(run) == before


def test_report_inside_run_folder_is_refused(tmp_path):
    run = build(tmp_path)
    before = snapshot(run)
    code, rep, err = run_check(run, "--report", str(run / "report.json"))
    assert code == 2 and "report" in err and snapshot(run) == before
    out = tmp_path / "report.json"
    assert run_check(run, "--report", str(out))[0] == 0
    assert json.loads(out.read_text())["ok"] is True


def test_profile_is_self_consistent():
    prof = json.loads(PROFILE.read_text())
    assert prof["invariants"] == ALL
    assert set(prof["artifacts"]) >= {"cards", "sweeps", "leads", "dedupe_log", "verdicts", "merged", "handoff"}


# ---------------------------------------------------------------- plan/expect.json (written by plan.py)
def add_plan(run: Path, *, verify: bool = True, mode: str = "parallel", sweepers=("sweep-1.json", "sweep-2.json"),
             chunks=("verdicts-1.json", "verdicts-2.json")) -> Path:
    w(run / "brief.md", "# brief\nP1 ...\n")
    phases = [{"name": "brief", "agents": {"general-purpose": 1}, "min_agents": 1, "outputs": ["brief.md"]},
              {"name": "investigate", "agents": {"inspector:case-reader": 2, "inspector:sweeper": len(sweepers)},
               "min_agents": 2 + len(sweepers), "outputs": ["cards/1.json", "cards/2.json", *sweepers]}]
    if verify:
        phases.append({"name": "verify", "agents": {"inspector:verifier": len(chunks)}, "min_agents": len(chunks), "outputs": list(chunks)})
    doc = {"plan_version": 1, "mode": mode, "cases": 4, "phases": phases, "reader_ids": ["1", "2"], "sweeper_files": list(sweepers),
           "verifier_chunks": [{"id": str(i), "chunk": f"plan/chunk-{i}.json", "verdicts": c, "size": 4} for i, c in enumerate(chunks, 1)] if verify else [],
           "docs_checker": {"needed": False, "questions": 0}}
    w(run / "plan" / "expect.json", doc)
    return run


def run_plan_check(run: Path, *extra):
    """No --expect: the plan supplies the ids."""
    p = subprocess.run([sys.executable, str(CHECK), str(run), *extra], capture_output=True, text=True)
    try:
        rep = json.loads(p.stdout)
    except ValueError:
        rep = None
    return p.returncode, rep, p.stderr


def test_complete_run_with_a_plan_passes(tmp_path):
    run = add_plan(build(tmp_path))
    code, rep, _ = run_plan_check(run)
    assert code == 0 and rep["ok"], rep
    assert list(status(rep)) == ALL + ["plan.phases"] and set(status(rep).values()) == {"pass"}
    assert "3 phases" in next(i for i in rep["invariants"] if i["id"] == "plan.phases")["evidence"]


def test_the_plan_replaces_the_command_line(tmp_path):
    """--expect 7,8 would look for cards 7 and 8; with a plan the readers are 1 and 2."""
    run = add_plan(build(tmp_path))
    p = subprocess.run([sys.executable, str(CHECK), str(run), "--expect", "7,8"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout[-400:]


def test_a_stub_card_left_in_the_run_fails_the_plan_check(tmp_path):
    """A stopped reader's stub is partial work: the gate must not call that phase finished."""
    run = add_plan(build(tmp_path))
    card = json.loads((run / "cards" / "2.json").read_text())
    w(run / "cards" / "2.json", {**card, "status": "in-progress"})
    code, rep, _ = run_plan_check(run)
    assert code == 1 and "plan.phases" in failing(rep)
    ev = next(i for i in rep["invariants"] if i["id"] == "plan.phases")["evidence"]
    assert "stub cards" in ev and "cards/2.json" in ev and "cards/1.json" not in ev


def test_skipped_verifier_phase_fails(tmp_path):
    """The model stopped after the merge: no verdicts, no merged.json, no handoff."""
    run = add_plan(build(tmp_path))
    for f in ("verdicts-1.json", "verdicts-2.json", "merged.json", "open-bugs.md"):
        (run / f).unlink()
    code, rep, _ = run_plan_check(run)
    assert code == 1 and "plan.phases" in failing(rep)
    ev = next(i for i in rep["invariants"] if i["id"] == "plan.phases")["evidence"]
    assert "phase 'verify' skipped" in ev and "verdicts-1.json" in ev


def test_a_missing_sweeper_output_fails_even_with_one_sweep_file(tmp_path):
    run = add_plan(build(tmp_path), sweepers=("sweep-1.json", "sweep-2.json", "sweep-3.json"))
    code, rep, _ = run_plan_check(run)
    assert code == 1 and "plan.phases" in failing(rep) and "artifacts.present" in failing(rep)
    assert "sweep-3.json" in next(i for i in rep["invariants"] if i["id"] == "plan.phases")["evidence"]


def test_a_plan_without_a_verify_phase_fails(tmp_path):
    run = add_plan(build(tmp_path), verify=False)
    code, rep, _ = run_plan_check(run)
    assert code == 1 and "plan.phases" in failing(rep)
    assert "no verify phase was planned" in next(i for i in rep["invariants"] if i["id"] == "plan.phases")["evidence"]


def test_a_skipped_reader_phase_fails(tmp_path):
    run = add_plan(build(tmp_path))
    (run / "cards" / "2.json").unlink()
    code, rep, _ = run_plan_check(run)
    assert code == 1 and "plan.phases" in failing(rep)
    assert "phase 'investigate'" in next(i for i in rep["invariants"] if i["id"] == "plan.phases")["evidence"]


def test_single_investigator_plan_needs_no_cards(tmp_path):
    run = build(tmp_path)
    for p in (run / "cards").glob("*.json"):
        p.unlink()
    for p in run.glob("sweep-*.json"):
        p.unlink()
    (run / "dedupe.md").unlink()
    doc = {"plan_version": 1, "mode": "single", "cases": 2, "reader_ids": [], "sweeper_files": [], "docs_checker": {"needed": False, "questions": 0},
           "phases": [{"name": "investigate", "agents": {"inspector:investigator": 1}, "min_agents": 1, "outputs": ["leads.json"]},
                      {"name": "verify", "agents": {"inspector:verifier": 2}, "min_agents": 2, "outputs": ["verdicts-1.json", "verdicts-2.json"]}],
           "verifier_chunks": [{"id": "1", "verdicts": "verdicts-1.json"}, {"id": "2", "verdicts": "verdicts-2.json"}]}
    w(run / "plan" / "expect.json", doc)
    code, rep, _ = run_plan_check(run)
    assert code == 0, rep
    (run / "verdicts-2.json").unlink()
    assert "plan.phases" in failing(run_plan_check(run)[1])


@pytest.mark.parametrize("breakage", ["not json", {"plan_version": 2}, "path", "reader"])
def test_a_malformed_plan_is_invalid_input(tmp_path, breakage):
    run = add_plan(build(tmp_path))
    doc = json.loads((run / "plan" / "expect.json").read_text())
    if breakage == "path":
        doc["phases"][0]["outputs"] = ["../outside.json"]
    elif breakage == "reader":
        doc["reader_ids"] = ["../x"]
    else:
        doc = breakage
    w(run / "plan" / "expect.json", doc)
    code, rep, err = run_plan_check(run)
    assert code == 2 and rep is None and err.startswith("check_run.py:")


def _suffix_run(tmp_path, suffixes=("[lead 0]", "[lead 1]")):
    """Two leads share one `where`; the run disambiguates them as merge_verdicts.py asks, then merges."""
    run = tmp_path / "run"
    a, b = lead("src/b.py:12", "first problem"), lead("src/b.py:12", "second, different problem")
    w(run / "cards" / "1.json", {"case": "1", "complete": {"siblings": [a, b]}})
    w(run / "sweep-1.json", [lead("c.py:1")])
    leads = [{**a, "found_by": "1"}, {**b, "found_by": "1"}, {**lead("c.py:1"), "found_by": "sweeper"}]
    w(run / "leads.json", leads)
    w(run / "dedupe.md", "# Dedupe log\n\n## Merges\n- none\n\n## Counts\n- raw: 3\n- merged: 0\n- final: 3\n")
    uniq = [dict(x) for x in leads]
    uniq[0]["where"] += " " + suffixes[0]
    uniq[1]["where"] += " " + suffixes[1]
    w(run / "merged.json", [{**x, "verdict": "REAL"} for x in uniq])
    w(run / "open-bugs.md", handoff(3))
    return run


def test_lead_suffix_is_normalised(tmp_path):
    code, rep, _ = run_check(_suffix_run(tmp_path), "--expect", "1")
    assert status(rep)["merged.matches_leads"] == "pass", rep


def test_repeated_lead_suffix_fails(tmp_path):
    rep = run_check(_suffix_run(tmp_path, ("[lead 0]", "[lead 0]")), "--expect", "1")[1]
    assert failing(rep) == ["merged.matches_leads"] and "suffixed wheres repeat" in str(rep)


def test_suffixed_where_absent_from_leads_fails(tmp_path):
    run = _suffix_run(tmp_path)
    merged = json.loads((run / "merged.json").read_text())
    merged[2]["where"] = "nowhere.py:9 [lead 2]"
    w(run / "merged.json", merged)
    rep = run_check(run, "--expect", "1")[1]
    assert failing(rep) == ["merged.matches_leads"] and "not in leads.json" in str(rep)


def test_unknown_where_still_fails(tmp_path):
    run = build(tmp_path)
    merged = json.loads((run / "merged.json").read_text())
    merged[0]["where"] = "nowhere.py:9"
    w(run / "merged.json", merged)
    assert "merged.matches_leads" in failing(run_check(run)[1])


def test_suffixed_verdict_is_not_an_orphan(tmp_path):
    """A verdict carries the ` [lead N]` suffix of its lead; verdicts.no_orphans compares on the base `where`."""
    run = _suffix_run(tmp_path)
    w(run / "verdicts-1.json", [{"where": "src/b.py:12 [lead 0]", "verdict": "REAL"},
                                {"where": "src/b.py:12 [lead 1]", "verdict": "REAL"},
                                {"where": "c.py:1", "verdict": "REAL"}])
    rep = run_check(run, "--expect", "1")[1]
    assert status(rep)["verdicts.no_orphans"] == "pass", rep


def test_suffixed_verdict_with_no_matching_lead_is_still_an_orphan(tmp_path):
    run = _suffix_run(tmp_path)
    w(run / "verdicts-1.json", [{"where": "nowhere.py:9 [lead 0]", "verdict": "REAL"}])
    assert status(run_check(run, "--expect", "1")[1])["verdicts.no_orphans"] == "fail"
