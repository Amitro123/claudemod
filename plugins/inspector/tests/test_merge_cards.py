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
        "1,2", {"sweep.json": [lead("a.py:158", TEXT_A2, "reproduced", probe="ran it")]})
    assert code == 0 and len(leads) == 1
    assert leads[0]["level"] == "reproduced" and leads[0]["found_by"] == "sweeper"
    assert leads[0]["also_found_by"] == ["1"] and leads[0]["merged_from"] == ["a.py:154-160,60-62"]
    assert "raw: 2" in log and "final: 1" in log and "similarity" in log
    assert "raw: 2" in cap.out


def test_tie_prefers_more_filled_fields(tmp_path, capsys) -> None:
    _, leads, _, _ = run(tmp_path, capsys,
                         {"1": card(1, lead("a.py:5", level="read")),
                          "2": card(2, lead("a.py:7", TEXT_A2, "read", probe="x", reach_when="always"))}, "1,2")
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
