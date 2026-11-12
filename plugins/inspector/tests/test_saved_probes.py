"""Saved reader probes: a runnable reproduction kept in <run>/probes/ and named on its lead (`probe_file`).

The fixture (tests/fixtures/saved_probes) is a run folder with three cards: one with a saved probe, one legacy
card with only probe text, and one whose saved probe file is missing. No model is called.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "skills" / "inspect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import handoff  # noqa: E402
import leadsio  # noqa: E402
import lint_leads  # noqa: E402
import merge_cards  # noqa: E402
import merge_verdicts  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "saved_probes"
SHA = "0632e9aaa3174689c1312d5b84e4b3e4b44c2eca"


def copy_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    shutil.copytree(FIXTURE, run)
    return run


def merged_leads(run: Path, capsys, expect="1,2,3"):
    code = merge_cards.main(["--cards", str(run / "cards"), "--expect", expect,
                             "--out", str(run / "leads.json"), "--log", str(run / "dedupe.md")])
    cap = capsys.readouterr()
    leads = json.loads((run / "leads.json").read_text(encoding="utf-8")) if (run / "leads.json").exists() else None
    return code, {x["where"]: x for x in leads or []}, cap


def pf(**kw):
    base = {"path": "probes/1-1.py", "leads": ["src/size.py:3"], "ref": "0632e9a", "command": "python3 probes/1-1.py",
            "requires": "Python 3", "expect": "exits 1"}
    return {**base, **kw}


def test_a_saved_probe_is_kept_verbatim_on_its_lead_and_listed_in_the_log(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    code, leads, cap = merged_leads(run, capsys)
    assert code == 0
    card = json.loads((FIXTURE / "cards" / "1.json").read_text(encoding="utf-8"))
    assert leads["src/size.py:3"]["probe_file"] == card["complete"]["siblings"][0]["probe_file"]
    assert "probe_file_problems" not in leads["src/size.py:3"]
    log = (run / "dedupe.md").read_text(encoding="utf-8")
    probes = log.split("## Saved probes")[1].split("\n## ")[0]
    assert "- 1 src/size.py:3: probes/1-1.py (ok)" in probes
    assert "saved probes: 2 (1 with a problem; see the log)" in cap.out


def test_a_missing_probe_file_is_reported_and_its_lead_kept_at_its_level(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    code, leads, _ = merged_leads(run, capsys)
    assert code == 0
    lead = leads["src/redact.py:7"]
    assert lead["level"] == "reproduced" and lead["probe_file"]["path"] == "probes/3-1.py"
    assert lead["probe_file_problems"] == ["probe_file.path probes/3-1.py: missing from the run folder"]
    assert "- 3 src/redact.py:7: probes/3-1.py (probe_file.path probes/3-1.py: missing from the run folder)" in \
        (run / "dedupe.md").read_text(encoding="utf-8")


def test_a_legacy_card_with_no_saved_probe_merges_exactly_as_before(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    code, leads, cap = merged_leads(run, capsys, expect="2")
    assert code == 0
    sib = json.loads((FIXTURE / "cards" / "2.json").read_text(encoding="utf-8"))["complete"]["siblings"][0]
    assert leads == {"src/retry.py:12": {**sib, "found_by": "2", "case": "#2"}}
    assert "## Saved probes" not in (run / "dedupe.md").read_text(encoding="utf-8")
    assert "saved probes" not in cap.out


def test_probe_file_problems_name_each_fault() -> None:
    lead = {"where": "src/size.py:3 [lead 4]"}
    run = str(FIXTURE)
    assert leadsio.probe_file_problems({**lead, "probe_file": pf()}, run, SHA) == []
    assert leadsio.probe_file_problems({"where": "a.py:1"}, run, SHA) == []
    assert leadsio.probe_file_problems({**lead, "probe_file": "probes/1-1.py"}, run, SHA) == \
        ["probe_file: expected an object with path, leads, ref, command, requires, expect"]
    for bad in ("../1-1.py", "/tmp/1-1.py", "C:/x/1-1.py", "cards/1.json", "probes", "probes/../cards/1.json"):
        assert leadsio.probe_file_problems({**lead, "probe_file": pf(path=bad)}, run, SHA) == \
            [f"probe_file.path {bad}: not a path under probes/ in the run folder"], bad
    assert leadsio.probe_file_problems({**lead, "probe_file": pf(command="", expect=None)}, run, SHA) == \
        ["probe_file.command: missing or empty", "probe_file.expect: missing or empty"]
    assert leadsio.probe_file_problems({**lead, "probe_file": pf(leads=["src/other.py:1"])}, run, SHA) == \
        ["probe_file.leads: does not name this lead (src/size.py:3)"]
    assert leadsio.probe_file_problems({**lead, "probe_file": pf(leads="src/size.py:3")}, run, SHA) == \
        ["probe_file.leads: expected a list of the leads' `where`"]
    assert leadsio.probe_file_problems({**lead, "probe_file": pf(ref="1234567")}, run, SHA) == \
        ["probe_file.ref 1234567: not the run's ref 0632e9aaa317"]
    assert leadsio.probe_file_problems({**lead, "probe_file": pf(ref="1234567")}, run, None) == []


def test_a_probe_made_at_another_ref_is_reported_from_the_runs_evidence(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    ev = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    (run / "evidence.json").write_text(json.dumps({**ev, "ref_sha": "f" * 40}), encoding="utf-8")
    _, leads, _ = merged_leads(run, capsys)
    assert leads["src/size.py:3"]["probe_file_problems"] == ["probe_file.ref 0632e9a: not the run's ref ffffffffffff"]


def test_the_saved_probe_runs_in_a_disposable_copy_and_shows_what_its_card_expects(tmp_path) -> None:
    """What a verifier does with it: copy, read, run its command from the copy, compare with `expect`."""
    before = sorted(p.relative_to(FIXTURE).as_posix() for p in FIXTURE.rglob("*"))
    box = copy_run(tmp_path)
    probe = json.loads((box / "cards" / "1.json").read_text(encoding="utf-8"))["complete"]["siblings"][0]["probe_file"]
    argv = shlex.split(probe["command"])
    assert argv[0] == "python3" and (box / argv[1]).is_file()
    p = subprocess.run([sys.executable, *argv[1:]], cwd=box, capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert p.returncode == 1 and "-> None, want 'large'" in p.stdout
    assert sorted(p.relative_to(FIXTURE).as_posix() for p in FIXTURE.rglob("*")) == before, "the fixture is never written"


def verdicts(run: Path, items: list[dict]):
    (run / "v.json").write_text(json.dumps(items), encoding="utf-8")
    code = merge_verdicts.main(["--leads", str(run / "leads.json"), "--verdicts", str(run / "v.json"),
                                "--out", str(run / "merged.json")])
    return code, {x["where"]: x for x in json.loads((run / "merged.json").read_text(encoding="utf-8"))}


def test_a_real_verdict_resting_on_the_readers_probe_alone_is_marked_not_confirmed(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    merged_leads(run, capsys)
    check = {"read_first": True, "ran": "yes", "exercises_claim": "yes", "observed": "-> None"}
    code, m = verdicts(run, [{"where": "src/size.py:3", "verdict": "REAL", "evidence": "ran the reader's probe", "probe_check": check},
                             {"where": "src/retry.py:12", "verdict": "REAL-LOW", "evidence": "read retry.py:10-14"},
                             {"where": "src/redact.py:7", "verdict": "REAL", "evidence": "own probe: unchanged",
                              "probe_check": {"ran": "no: missing", "independent": "own redact copy: SECRET_KEY=abc unchanged"}}])
    err = capsys.readouterr().err
    assert code == 0
    size = m["src/size.py:3"]
    assert size["verdict"] == "REAL" and size["verifier_probe_check"] == check
    assert size["verdict_basis"] == "reader probe only"
    assert merge_verdicts.PROBE_ONLY in size["not_verified"]
    assert "src/size.py:3: REAL rests on the reader's saved probe alone" in err
    assert "verdict_basis" not in m["src/redact.py:7"] and m["src/redact.py:7"]["verifier_probe_check"]["independent"]
    legacy = m["src/retry.py:12"]
    assert "verifier_probe_check" not in legacy and "verdict_basis" not in legacy


def test_handoff_shows_the_saved_probe_its_problems_and_a_probe_only_verdict(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    merged_leads(run, capsys)
    verdicts(run, [{"where": "src/size.py:3", "verdict": "REAL", "evidence": "ran it",
                    "probe_check": {"ran": "yes", "exercises_claim": "yes"}},
                   {"where": "src/retry.py:12", "verdict": "REAL-LOW", "evidence": "read"},
                   {"where": "src/redact.py:7", "verdict": "UNVERIFIABLE", "evidence": "probe file missing"}])
    leads = json.loads((run / "merged.json").read_text(encoding="utf-8"))
    for x in leads:
        x.pop("probe", None)
    warns: list[str] = []
    text, errors = handoff.build(leads, {}, set(), {}, "t", warns)
    assert errors == []
    row = {w: next(r for r in text.splitlines() if f"`{w}`" in r) for w in ("src/size.py:3", "src/retry.py:12", "src/redact.py:7")}
    assert "probe file: probes/1-1.py (run: python3 probes/1-1.py; expect: prints -> None, want 'large' and exits 1)" in row["src/size.py:3"]
    assert "[verdict: REAL, on the reader's probe only]" in row["src/size.py:3"]
    assert "probe file: probes/3-1.py, not to be run: probe_file.path probes/3-1.py: missing from the run folder" in row["src/redact.py:7"]
    assert "probe file" not in row["src/retry.py:12"]
    no_probe = [w for w in warns if "but no probe" in w]
    assert no_probe == ["src/retry.py:12: level read but no probe; give the exact input and output, the command run, "
                        "or the path:line read (for a claim about an external tool, its --help), or lower the "
                        "level / move the claim to not_verified"], "a saved probe file counts as a probe"


def test_a_real_with_no_probe_check_is_not_recorded_as_independent_and_code_reading_counts_as_independent(tmp_path, capsys) -> None:
    """No `probe_check` at all is a different fact from a check that used only the reader's probe."""
    run = copy_run(tmp_path)
    merged_leads(run, capsys)
    _, m = verdicts(run, [{"where": "src/size.py:3", "verdict": "REAL", "evidence": "read size.py:1-5 at the ref"},
                          {"where": "src/retry.py:12", "verdict": "REAL-LOW", "evidence": "read"},
                          {"where": "src/redact.py:7", "verdict": "REAL-LOW", "evidence": "read",
                           "probe_check": {"ran": "no: missing", "independent": "code path: redact.py:7 regex needs the key at the end; hooks.py:4 writes it"}}])
    err = capsys.readouterr().err
    assert m["src/size.py:3"]["verdict"] == "REAL" and m["src/size.py:3"]["verdict_basis"] == "independent check not recorded"
    assert merge_verdicts.NOT_RECORDED in m["src/size.py:3"]["not_verified"]
    assert "src/size.py:3: REAL has no recorded independent check" in err
    assert "verdict_basis" not in m["src/redact.py:7"], "a justified code-path analysis is an independent check"


def test_summary_counts_keep_verdicts_but_say_how_many_lack_an_independent_check(tmp_path, capsys) -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))
    import scorecard
    run = copy_run(tmp_path)
    merged_leads(run, capsys)
    verdicts(run, [{"where": "src/size.py:3", "verdict": "REAL", "evidence": "ran it", "probe_check": {"ran": "yes"}},
                   {"where": "src/retry.py:12", "verdict": "REAL-LOW", "evidence": "read"},
                   {"where": "src/redact.py:7", "verdict": "REAL", "evidence": "x", "probe_check": {"independent": "own copy"}}])
    leads = json.loads((run / "merged.json").read_text(encoding="utf-8"))
    text, _ = handoff.build(leads, {}, set(), {}, "t", [])
    assert "Verified: 2 real, 1 real-low, 0 unverifiable, 0 not real, 0 unverified " \
           "(1 of the 3 real or real-low without a recorded independent check)" in text
    row = scorecard.build_row(leads, version="x", date="d")
    assert row["verdicts"]["REAL"] == 2 and row["confirmed"] == 3 and row["confirmed_not_independent"] == 1
    assert "1 of them without a recorded independent check" in scorecard.markdown(row)
    assert scorecard.flatten(row)["confirmed_not_independent"] == 1


def test_probe_file_null_is_no_saved_probe_like_an_omitted_one_while_malformed_metadata_is_still_named(tmp_path, capsys) -> None:
    """PR #122 review: `"probe_file": null` was counted as a saved probe without an independent check."""
    run = copy_run(tmp_path)
    card = json.loads((run / "cards" / "2.json").read_text(encoding="utf-8"))
    assert "probe_file" not in card["complete"]["siblings"][0]
    out = {}
    for name, extra in (("omitted", {}), ("null", {"probe_file": None})):
        card["complete"]["siblings"][0] = {k: v for k, v in card["complete"]["siblings"][0].items() if k != "probe_file"} | extra
        (run / "cards" / "2.json").write_text(json.dumps(card), encoding="utf-8")
        code, leads, cap = merged_leads(run, capsys, expect="2")
        assert code == 0, name
        lead = leads["src/retry.py:12"]
        assert "probe_file_problems" not in lead, name
        assert "## Saved probes" not in (run / "dedupe.md").read_text(encoding="utf-8") and "saved probes" not in cap.out, name
        _, m = verdicts(run, [{"where": "src/retry.py:12", "verdict": "REAL", "evidence": "read retry.py:10-14"}])
        err = capsys.readouterr().err
        merged = m["src/retry.py:12"]
        assert "verdict_basis" not in merged and "independent check" not in err, name
        text, _ = handoff.build(list(m.values()), {}, set(), {}, "t", [])
        assert "[verdict: REAL]" in text and "without a recorded independent check" not in text and "probe file" not in text, name
        out[name] = {k: v for k, v in merged.items() if k != "probe_file"}
    assert out["null"] == out["omitted"]
    for bad in ("", {}, "probes/1-1.py"):
        assert leadsio.probe_file_problems({"where": "a.py:1", "probe_file": bad}, str(run), SHA), bad


def test_handoff_gives_no_run_command_for_a_probe_with_a_problem(tmp_path, capsys) -> None:
    run = copy_run(tmp_path)
    merged_leads(run, capsys)
    leads = json.loads((run / "leads.json").read_text(encoding="utf-8"))
    text, _ = handoff.build(leads, {}, set(), {}, "t", [])
    row = next(r for r in text.splitlines() if "`src/redact.py:7`" in r)
    assert "probe file: probes/3-1.py, not to be run" in row and "python3 probes/3-1.py" not in row


def test_probe_paths_are_contained_after_resolving_links_and_platform_forms(tmp_path) -> None:
    run = copy_run(tmp_path)
    lead = {"where": "src/size.py:3"}
    for bad in ("probes/1-1.py:stream", "\\\\server\\share\\1-1.py", "//server/share/1-1.py", "c:probes/1-1.py", "probes\\..\\cards\\1.json"):
        assert leadsio.probe_file_problems({**lead, "probe_file": pf(path=bad)}, str(run), SHA) == \
            [f"probe_file.path {bad}: not a path under probes/ in the run folder"], bad

def link_dir(link: Path, target: Path) -> None:
    """A directory link: a symlink, or on Windows without the symlink privilege a junction."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


def test_a_probe_folder_linked_outside_the_run_is_refused(tmp_path) -> None:
    run = copy_run(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.py").write_text("print('outside')\n", encoding="utf-8")
    shutil.rmtree(run / "probes")
    link_dir(run / "probes", outside)
    assert (run / "probes" / "x.py").is_file()
    assert leadsio.probe_file_problems({"where": "src/size.py:3", "probe_file": pf(path="probes/x.py")}, str(run), SHA) == \
        ["probe_file.path probes/x.py: resolves outside probes/ in the run folder (a link?)"]


def test_a_probe_file_symlinked_outside_the_run_is_refused(tmp_path) -> None:
    import pytest
    run = copy_run(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    try:
        os.symlink(outside, run / "probes" / "link.py")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks unavailable here: {exc}")
    assert leadsio.probe_file_problems({"where": "src/size.py:3", "probe_file": pf(path="probes/link.py")}, str(run), SHA) == \
        ["probe_file.path probes/link.py: resolves outside probes/ in the run folder (a link?)"]


def test_lint_counts_a_saved_probe_file_as_a_probe() -> None:
    assert lint_leads.rule_l4({"where": "a.py:1", "level": "reproduced", "probe_file": pf()}) == []
    assert lint_leads.rule_l4({"where": "a.py:1", "level": "reproduced"})[0][0] == "L4"
