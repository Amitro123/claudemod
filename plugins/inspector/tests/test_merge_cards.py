"""Tests for merge_cards.py: cards and sweeper leads merged without a model, missing cards caught."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import merge_cards  # noqa: E402

TEXT_A = "the parser swallows invalid settings silently and rewrites the whole settings file"
TEXT_A2 = "the parser swallows invalid settings silently then rewrites the whole settings file"
TEXT_B = "retry counter never resets after a successful upload so later uploads give up early"


def lead(where, what=TEXT_A, level="read", **kw):
    return {"where": where, "what": what, "level": level, "category": "broken-flow", "reach": "default-on", **kw}


def card(n, *sibs):
    return {"case": f"#{n}", "unit": f"#{n}", "complete": {"siblings": list(sibs), "checked_clear": []}}


def setup(tmp_path, cards: dict, sweeps: dict | None = None):
    d = tmp_path / "cards"
    d.mkdir(exist_ok=True)
    for cid, c in cards.items():
        (d / f"{cid}.json").write_text(c if isinstance(c, str) else json.dumps(c), encoding="utf-8")
    paths = []
    for name, s in (sweeps or {}).items():
        p = tmp_path / name
        p.write_text(json.dumps(s), encoding="utf-8")
        paths.append(str(p))
    return d, paths


def run(tmp_path, capsys, cards, expect, sweeps=None):
    d, paths = setup(tmp_path, cards, sweeps)
    out, log = tmp_path / "leads.json", tmp_path / "dedupe.md"
    argv = ["--cards", str(d), "--expect", expect, "--out", str(out), "--log", str(log)]
    if paths:
        argv += ["--sweep", *paths]
    code = merge_cards.main(argv)
    cap = capsys.readouterr()
    leads = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return code, leads, (log.read_text(encoding="utf-8") if log.exists() else None), cap


def test_missing_card_exits_2_and_writes_nothing(tmp_path, capsys) -> None:
    code, leads, log, cap = run(tmp_path, capsys, {"1": card(1, lead("a.py:5")), "3": card(3)}, "1,2,3")
    assert code == 2 and leads is None and log is None
    assert "card 2: missing" in cap.err and "card 1" not in cap.err


def test_unparsable_card_exits_2_and_writes_nothing(tmp_path, capsys) -> None:
    code, leads, log, cap = run(tmp_path, capsys, {"1": card(1), "2": "{not json"}, "1,2")
    assert code == 2 and leads is None and log is None and "card 2" in cap.err


def test_write_failure_keeps_the_previous_leads_and_says_so(tmp_path, capsys, monkeypatch) -> None:
    d, _ = setup(tmp_path, {"1": card(1, lead("a.py:5"))})
    out = tmp_path / "leads.json"
    out.write_text("previous", encoding="utf-8")

    def refuse(src, dst):
        raise PermissionError(13, "denied", dst)
    monkeypatch.setattr(merge_cards.os, "replace", refuse)
    code = merge_cards.main(["--cards", str(d), "--expect", "1", "--out", str(out)])
    assert code == 1 and "merge_cards.py: not saved" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "previous"
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["leads.json"], "no temp file left behind"


def test_invalid_sweeper_exits_2(tmp_path, capsys) -> None:
    d, _ = setup(tmp_path, {"1": card(1)})
    bad = tmp_path / "sw.json"
    bad.write_text('{"where": "a.py:1"}', encoding="utf-8")
    code = merge_cards.main(["--cards", str(d), "--sweep", str(bad), "--expect", "1", "--out", str(tmp_path / "o.json")])
    assert code == 2 and not (tmp_path / "o.json").exists()


def test_same_defect_keeps_stronger_and_records_finders(tmp_path, capsys) -> None:
    code, leads, log, cap = run(
        tmp_path, capsys,
        {"1": card(1, lead("a.py:154-160,60-62", TEXT_A, "read")), "2": card(2)},
        "1,2", {"sweep.json": [lead("a.py:60-62, 154-160", TEXT_A.upper() + ".", "reproduced", probe="ran it")]})
    assert code == 0 and len(leads) == 1
    assert leads[0]["level"] == "reproduced" and leads[0]["found_by"] == "sweeper"
    assert leads[0]["also_found_by"] == ["1"] and leads[0]["merged_from"] == ["a.py:154-160,60-62"]
    assert "raw: 2" in log and "final: 1" in log and "exact duplicate" in log
    assert "raw: 2" in cap.out


def test_tie_prefers_more_filled_fields(tmp_path, capsys) -> None:
    _, leads, _, _ = run(tmp_path, capsys,
                         {"1": card(1, lead("a.py:5", level="read")),
                          "2": card(2, lead("a.py:5", TEXT_A, "read", probe="x", reach_when="always"))}, "1,2")
    assert len(leads) == 1 and leads[0]["found_by"] == "2" and leads[0]["also_found_by"] == ["1"]


def test_near_lines_different_mechanism_not_merged_but_logged(tmp_path, capsys) -> None:
    code, leads, log, _ = run(tmp_path, capsys,
                              {"1": card(1, lead("a.py:100-104", TEXT_A)), "2": card(2, lead("a.py:110", TEXT_B))}, "1,2")
    assert code == 0 and len(leads) == 2
    assert "Possible duplicates" in log and "a.py:100-104" in log and "a.py:110" in log
    assert "- none" not in log.split("## Possible duplicates")[1].split("##")[0]


def test_far_lines_or_other_file_not_listed(tmp_path, capsys) -> None:
    _, leads, log, _ = run(tmp_path, capsys,
                           {"1": card(1, lead("a.py:10", TEXT_A), lead("a.py:200", TEXT_A), lead("b.py:10", TEXT_A))}, "1")
    assert len(leads) == 3 and "- none" in log.split("## Possible duplicates")[1]


def test_unparsable_where_never_merged(tmp_path, capsys) -> None:
    w = "a.py:1-5 vs b.py:3-9"
    _, leads, log, _ = run(tmp_path, capsys,
                           {"1": card(1, lead(w, TEXT_A), lead(w, TEXT_A)), "2": card(2, lead("no-line-here", TEXT_A))}, "1,2")
    assert len(leads) == 3 and "Unparsable where" in log


def test_fields_preserved_byte_for_byte(tmp_path, capsys) -> None:
    odd = lead("a.py:5", "Wörd  with   spacesé and 'quotes' \"x\"", "suspect", probe="line1\nline2", extra={"k": [1, None]})
    _, leads, _, _ = run(tmp_path, capsys, {"1": card(1, odd)}, "1", {"s.json": [lead("z.py:1")]})
    got = {k: v for k, v in leads[0].items() if k not in ("found_by", "case")}
    assert got == odd
    assert json.dumps(got, sort_keys=True) == json.dumps(odd, sort_keys=True)


def test_card_without_siblings_and_sweeper_only(tmp_path, capsys) -> None:
    code, leads, _, _ = run(tmp_path, capsys, {"1": {"case": "#1", "complete": {}}, "2": card(2)}, "1,2",
                            {"s.json": [lead("z.py:1")]})
    assert code == 0 and [x["found_by"] for x in leads] == ["sweeper"]


def test_expect_ids_not_one_to_n(tmp_path, capsys) -> None:
    code, leads, _, _ = run(tmp_path, capsys, {"3": card(3, lead("a.py:1")), "7": card(7, lead("b.py:1"))}, "3,7")
    assert code == 0 and [x["found_by"] for x in leads] == ["3", "7"]
    (tmp_path / "again").mkdir()
    code, *_ = run(tmp_path / "again", capsys, {"3": card(3)}, "3,7")
    assert code == 2


def test_bad_expect_values(tmp_path, capsys) -> None:
    for e in ("", "1,1", "../x"):
        assert run(tmp_path, capsys, {"1": card(1)}, e)[0] == 2


def test_lint_findings_printed_not_applied(tmp_path, capsys) -> None:
    sec = lead("a.py:5", level="reproduced", category="security", probe="")
    code, leads, _, cap = run(tmp_path, capsys, {"1": card(1, sec)}, "1")
    assert code == 0 and " | L" in cap.out
    assert {k: v for k, v in leads[0].items() if k not in ("found_by", "case")} == sec


def test_parse_where_shapes() -> None:
    assert merge_cards.parse_where("a/b.py:154-160,60-62") == ("a/b.py", [(154, 160), (60, 62)])
    assert merge_cards.parse_where("a.py:111") == ("a.py", [(111, 111)])
    assert merge_cards.parse_where("a.py") is None and merge_cards.parse_where(None) is None


BS = chr(92)  # one backslash; built here so the test file has no escape ambiguity


def _raw_card(n, what_json):
    return ('{"case": "#%d", "unit": "#%d", "complete": {"siblings": [{"where": "a.py:%d", "what": %s, '
            '"level": "read", "category": "broken-flow", "reach": "default-on"}], "checked_clear": []}}'
            % (n, n, n * 100, what_json))


BAD_ESC = _raw_card(1, '"regex ' + BS + 's+ and ' + BS + 'd are matched"')


def _run_repair(tmp_path, capsys, cards, flag):
    d, _ = setup(tmp_path, cards)
    out, log = tmp_path / "leads.json", tmp_path / "dedupe.md"
    argv = ["--cards", str(d), "--expect", ",".join(cards), "--out", str(out), "--log", str(log)] + flag
    code = merge_cards.main(argv)
    return code, d, out, log, capsys.readouterr()


def test_invalid_escape_refused_by_default(tmp_path, capsys) -> None:
    code, d, out, _, cap = _run_repair(tmp_path, capsys, {"1": BAD_ESC}, [])
    assert code == 2 and "1.json" in cap.err and not out.exists()
    assert not (d / "1.json.orig").exists()


def test_repair_escapes_fixes_logs_and_keeps_orig(tmp_path, capsys) -> None:
    code, d, out, log, cap = _run_repair(tmp_path, capsys, {"1": BAD_ESC}, ["--repair-escapes"])
    assert code == 0
    assert (d / "1.json.orig").read_text(encoding="utf-8") == BAD_ESC
    what = json.loads(out.read_text(encoding="utf-8"))[0]["what"]
    assert what == "regex " + BS + "s+ and " + BS + "d are matched"
    assert "1.json" in log.read_text(encoding="utf-8") and "repaired" in cap.out


def test_repair_escapes_leaves_valid_escapes_alone(tmp_path, capsys) -> None:
    good = _raw_card(1, '"a' + BS + 'nb ' + BS + '" c ' + BS * 2 + ' d ' + BS + 'u00e9"')
    code, d, out, log, _ = _run_repair(tmp_path, capsys, {"1": good}, ["--repair-escapes"])
    assert code == 0 and (d / "1.json").read_text(encoding="utf-8") == good
    assert not (d / "1.json.orig").exists() and "Repaired" not in log.read_text(encoding="utf-8")


def test_repair_escapes_fixes_bad_unicode(tmp_path, capsys) -> None:
    bad = _raw_card(1, '"bad ' + BS + 'u12 here"')
    code, d, out, _, _ = _run_repair(tmp_path, capsys, {"1": bad}, ["--repair-escapes"])
    assert code == 0 and (d / "1.json.orig").exists()
    assert json.loads(out.read_text(encoding="utf-8"))[0]["what"] == "bad " + BS + "u12 here"


def test_repair_escapes_does_not_hide_other_errors(tmp_path, capsys) -> None:
    code, d, out, _, cap = _run_repair(tmp_path, capsys, {"1": "{not json"}, ["--repair-escapes"])
    assert code == 2 and "1.json" in cap.err and not (d / "1.json.orig").exists()


def _two(tmp_path, capsys, w1, w2):
    sibs = [lead(w1, TEXT_A), lead(w2, TEXT_B)]
    return run(tmp_path, capsys, {"1": card(1, sibs[0]), "2": card(2, sibs[1])}, "1,2")


def _dup_section(log: str) -> str:
    return log.split("## Possible duplicates")[1].split("\n## ")[0]


def test_overlapping_ranges_flagged_each_way_with_reason(tmp_path, capsys) -> None:
    _, leads, log, _ = _two(tmp_path, capsys, "a.py:12-20", "a.py:15")
    assert len(leads) == 2
    by = {x["where"]: x for x in leads}
    assert by["a.py:12-20"]["possible_duplicate_of"] == ["a.py:15"]
    assert by["a.py:15"]["possible_duplicate_of"] == ["a.py:12-20"]
    sec = _dup_section(log)
    assert "(kept)" in log and "lines overlap" in sec and "similar wording" not in sec


def test_adjacent_ranges_not_flagged_as_overlap(tmp_path, capsys) -> None:
    _, leads, log, _ = _two(tmp_path, capsys, "a.py:10-12", "a.py:13")
    assert len(leads) == 2 and "lines overlap" not in log
    assert "within 10 lines" in _dup_section(log) and "similar wording" not in _dup_section(log)  # TEXT_A vs TEXT_B share no words


def test_overlap_in_different_files_not_flagged(tmp_path, capsys) -> None:
    _, leads, log, _ = _two(tmp_path, capsys, "a.py:12-20", "b.py:15")
    assert all("possible_duplicate_of" not in x for x in leads) and "- none" in _dup_section(log)


def test_overlap_drops_and_merges_nothing(tmp_path, capsys) -> None:
    sibs = [lead("a.py:12-20", TEXT_A, probe="p1"), lead("a.py:15", TEXT_B, probe="p2"), lead("a.py:14-16", TEXT_A2)]
    _, leads, log, _ = run(tmp_path, capsys, {"1": card(1, *sibs[:2]), "2": card(2, sibs[2])}, "1,2")
    # the third is worded like the first but is not an exact duplicate: all three stay, each flagged
    assert [x["what"] for x in leads if x["where"] == "a.py:15"] == [TEXT_B]
    assert len(leads) == 3 and all("possible_duplicate_of" in x for x in leads)
    assert all("merged_from" not in x for x in leads)


def test_exact_duplicates_still_merge_without_flag(tmp_path, capsys) -> None:
    _, leads, _, _ = run(tmp_path, capsys, {"1": card(1, lead("a.py:5")), "2": card(2, lead("a.py:5"))}, "1,2")
    assert len(leads) == 1 and "possible_duplicate_of" not in leads[0]


def _sweep_files(tmp_path):
    paths = []
    for k, (w, t) in enumerate([("a.py:10", TEXT_A), ("b.py:20", TEXT_B), ("c.py:30", "cache entry never expires after the source file changes on disk")], 1):
        p = tmp_path / f"sweep-{k}.json"
        p.write_text(json.dumps([lead(w, t)]), encoding="utf-8")
        paths.append(str(p))
    return paths


def _merge(tmp_path, capsys, sweep_args):
    d, _ = setup(tmp_path, {"1": card(1)})
    out = tmp_path / "leads.json"
    code = merge_cards.main(["--cards", str(d), "--expect", "1", "--out", str(out), *sweep_args])
    err = capsys.readouterr().err
    return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None), err


def test_repeated_sweep_flags_load_every_file(tmp_path, capsys) -> None:
    p = _sweep_files(tmp_path)
    code, leads, err = _merge(tmp_path, capsys, ["--sweep", p[0], "--sweep", p[1], "--sweep", p[2]])
    assert code == 0 and len(leads) == 3


def test_mixed_sweep_forms_load_every_file(tmp_path, capsys) -> None:
    p = _sweep_files(tmp_path)
    code, leads, err = _merge(tmp_path, capsys, ["--sweep", p[0], p[1], "--sweep", p[2]])
    assert code == 0 and len(leads) == 3


def test_missing_sweep_path_exits_2_even_among_repeats(tmp_path, capsys) -> None:
    p = _sweep_files(tmp_path)
    code, leads, err = _merge(tmp_path, capsys, ["--sweep", p[0], "--sweep", str(tmp_path / "nope.json")])
    assert code == 2 and leads is None and "nope.json" in err


def test_per_file_counts_reported_on_stderr(tmp_path, capsys) -> None:
    p = _sweep_files(tmp_path)
    code, _, err = _merge(tmp_path, capsys, ["--sweep", p[0], "--sweep", p[1]])
    assert code == 0
    assert f"sweep file {p[0]}: 1 leads" in err and f"sweep file {p[1]}: 1 leads" in err
    assert "sweep files loaded: 2" in err


TENANT = {"where": "cache.py:10", "what": "cache key ignores tenant identity", "level": "read", "found_by": "1",
          "probe": "p-tenant", "impact": {"what": "tenant data mixes", "level": "read"}, "change": "add tenant", "test": "t-tenant"}
LOCALE = {"where": "cache.py:12", "what": "cache key ignores locale identity", "level": "read", "found_by": "2",
          "probe": "p-locale", "impact": {"what": "wrong language", "level": "read"}, "change": "add locale", "test": "t-locale"}


def chunks(leads: list[dict], size: int = 8) -> list[list[dict]]:
    """references/verify.md step 1: split the open leads into chunks of at most 8, `where` untouched."""
    return [leads[i:i + size] for i in range(0, len(leads), size)]


def test_distinct_similar_leads_both_reach_the_verifier_chunk(tmp_path, capsys) -> None:
    final, merges, possible = merge_cards.dedupe([dict(TENANT), dict(LOCALE)])
    assert merges == [] and len(final) == 2 and len(possible) == 1
    code, leads, log, _ = run(tmp_path, capsys, {"1": card(1, {k: v for k, v in TENANT.items() if k != "found_by"}),
                                                 "2": card(2, {k: v for k, v in LOCALE.items() if k != "found_by"})}, "1,2")
    assert code == 0
    chunk = chunks(leads)[0]
    assert [x["where"] for x in chunk] == ["cache.py:10", "cache.py:12"]
    for orig, got in zip((TENANT, LOCALE), chunk):  # every field of every kept lead survives
        assert {k: v for k, v in got.items() if k not in ("case", "possible_duplicate_of")} == orig
    assert chunk[0]["possible_duplicate_of"] == ["cache.py:12"] and chunk[1]["possible_duplicate_of"] == ["cache.py:10"]
    assert "cache.py:10" in _dup_section(log) and "cache.py:12" in _dup_section(log)
    verdicts = [{"where": x["where"], "verdict": "REAL"} for x in chunk]
    import merge_verdicts
    merged, _ = merge_verdicts.merge(chunk, verdicts)
    assert [m["verdict"] for m in merged] == ["REAL", "REAL"]


def test_exact_duplicates_merge_with_provenance_kept() -> None:
    a, b = dict(TENANT), {**TENANT, "found_by": "sweeper", "what": "Cache key ignores tenant identity.", "where": "cache.py:10"}
    final, merges, possible = merge_cards.dedupe([a, b])
    assert len(final) == 1 and merges == [(0, 1, 1.0)] and possible == []
    assert final[0]["found_by"] == "1" and final[0]["also_found_by"] == ["sweeper"] and final[0]["merged_from"] == ["cache.py:10"]


def test_high_word_overlap_with_other_lines_is_flagged_not_merged() -> None:
    near = {**TENANT, "where": "cache.py:11", "found_by": "2", "what": TENANT["what"] + " too"}
    final, merges, possible = merge_cards.dedupe([dict(TENANT), near])
    assert merges == [] and len(final) == 2 and possible[0][2] >= 0.5
    assert all("merged_from" not in x for x in final) and final[0]["possible_duplicate_of"] == ["cache.py:11"]


def test_parallel_md_promise_matches_behaviour() -> None:
    doc = (Path(__file__).parent.parent / "skills" / "inspect" / "references" / "parallel.md").read_text(encoding="utf-8")
    flat = " ".join(doc.split())
    assert "merges only exact duplicates (same locations, same text)" in flat
    assert "keeps similar nearby leads" in flat and "possible_duplicate_of" in flat
    # the documented promise, as behaviour: same locations and text merge; similar nearby text does not
    assert len(merge_cards.dedupe([dict(TENANT), {**TENANT, "found_by": "2"}])[0]) == 1
    assert len(merge_cards.dedupe([dict(TENANT), dict(LOCALE)])[0]) == 2


def test_reason_matches_the_case() -> None:
    def reasons(w1, t1, w2, t2):
        return [r[3] for r in merge_cards.dedupe([{"where": w1, "what": t1, "found_by": "1"},
                                                  {"where": w2, "what": t2, "found_by": "2"}])[2]]
    assert reasons("a.py:10", TEXT_A, "a.py:18", TEXT_B) == ["within 10 lines"]       # similarity 0.0
    assert reasons("a.py:10", TEXT_A, "a.py:18", TEXT_A2) == ["similar wording"]
    assert reasons("a.py:10-20", TEXT_A, "a.py:15", TEXT_B) == ["lines overlap"]


def _variant_pair(**loser):
    a = {"where": "a.py:10", "what": "parser swallows invalid settings", "found_by": "1", "level": "suspect",
         "impact": {"what": "i1"}, "probe": "p1", "change": "c1"}
    b = {**a, "found_by": "2", "level": "read", "impact": {"what": "i2"}, "probe": "p2", "test": "t2",
         "not_verified": ["x"], **loser}
    del b["change"]
    return a, b


def test_exact_duplicate_merge_unions_missing_fields_and_records_conflicts() -> None:
    a, b = _variant_pair()
    final, merges, _ = merge_cards.dedupe([a, b])
    (out,) = final
    assert out["level"] == "read" and out["found_by"] == "2" and out["also_found_by"] == ["1"]
    assert out["change"] == "c1"                      # the winner lacked it: filled from the loser
    assert out["impact"] == {"what": "i2"} and out["probe"] == "p2"   # winner's value kept
    assert out["merged_variants"] == [{"found_by": "1", "where": "a.py:10", "level": "suspect",
                                       "impact": {"what": "i1"}, "probe": "p1"}]
    assert out["test"] == "t2" and out["not_verified"] == ["x"]


def test_identical_exact_duplicates_have_no_variants_and_winner_fields_never_change() -> None:
    a, b = _variant_pair()
    final, _, _ = merge_cards.dedupe([a, {**a, "found_by": "2"}])
    assert "merged_variants" not in final[0] and final[0]["impact"] == {"what": "i1"}


def test_leads_differing_only_by_an_operator_are_not_merged(tmp_path, capsys) -> None:
    """R062-02: `<` vs `>` (and `<=`, `==`, `!=`) are different claims; the word-only identity merged them."""
    ops = ["x < 5", "x > 5", "x <= 5", "x >= 5", "x == 5", "x != 5"]
    leads = [lead("a.py:10", f"the retry loop stops when attempts {op} limit and drops the last upload") for op in ops]
    code, out, log, cap = run(tmp_path, capsys, {"1": card(1, *leads)}, "1")
    assert code == 0 and len(out) == len(ops), "each operator is its own lead"
    assert all("merged_from" not in x for x in out)


def test_exact_duplicates_still_merge_when_only_spacing_and_case_differ(tmp_path, capsys) -> None:
    a = lead("a.py:10", "stops when attempts < limit  and drops the last upload")
    b = lead("a.py:10", "Stops when attempts<limit and drops the Last upload.")
    code, out, log, cap = run(tmp_path, capsys, {"1": card(1, a, b)}, "1")
    assert code == 0 and len(out) == 1 and out[0]["merged_from"] == ["a.py:10"]
