"""Tests for evals/gate/check_run.py on synthetic run folders (nothing here touches a real run)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

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
