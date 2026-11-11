"""Tests for crosscheck.py: cards from a reader against the collector's evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import crosscheck  # noqa: E402

EV = {"timeline": [
    {"unit": "#2", "sha": "aaa1111", "commits": [{"sha": "c2c2c2c", "introduced_by": [{"unit": "#1", "lines": 3}],
                                                 "left_behind": [{"line": "render(x, escape=False)", "at": ["b.py:2", "c.py:9"]}]}],
     "introduced_by": [{"unit": "#1"}]},
    {"unit": "#3", "sha": "bbb2222", "commits": [{"sha": "c3c3c3c", "introduced_by": [{"unit": "#2", "lines": 1}]}],
     "introduced_by": [{"unit": "#2"}]},
    {"unit": "#4", "sha": "ddd4444", "commits": [{"sha": "c4c4c4c"}], "introduced_by": []},
], "left_behind": [{"unit": "#2", "commit": "c2c2c2c", "line": "render(x, escape=False)", "at": ["b.py:2", "c.py:9"]}]}


def card(unit, commit, culprit, siblings=(), clear=()):
    return {"case": f"{unit} {commit}", "unit": unit, "commit": commit, "culprit": {"unit": culprit, "level": "read"},
            "mechanism": {"where": "a.py:2", "level": "read"},
            "complete": {"verdict": "no" if siblings else "yes", "siblings": list(siblings), "checked_clear": list(clear)}}


def test_culprits_agree_disagree_and_unknown() -> None:
    r = crosscheck.crosscheck(EV, [card("#2", "c2c2c2c", "#1"), card("#3", "c3c3c3c", "#1"), card("#4", "c4c4c4c", "unknown")])
    got = {c["case"].split()[0]: c["culprit"] for c in r["cases"]}
    assert got["#2"] == "agree"
    assert got["#3"].startswith("disagree") and "#2" in got["#3"]
    assert got["#4"] == "both unknown"
    assert r["culprits_agree"] == 1
    assert r["culprits_both_unknown"] == 1


def test_siblings_by_source_and_unchecked_copies() -> None:
    sib = {"where": "b.py:3", "level": "reproduced", "breaks": "P1"}
    own = {"where": "z.py:40", "level": "read", "breaks": "sibling of #2"}
    r = crosscheck.crosscheck(EV, [card("#2", "c2c2c2c", "#1", siblings=[sib, own])])
    assert [s["source"] for s in r["cases"][0]["siblings"]] == ["both", "reader only"]
    assert r["copies_left_unchecked"][0]["at"] == ["c.py:9"]
    r2 = crosscheck.crosscheck(EV, [card("#2", "c2c2c2c", "#1", clear=["c.py:9: escaped by its caller"])])
    assert r2["copies_left_unchecked"][0]["at"] == ["b.py:2"]
    r3 = crosscheck.crosscheck(EV, [card("#2", "c2c2c2c", "#1")])
    assert len(r3["copies_left_unchecked"]) == 1


def test_cli_reads_cards_and_reports_bad_ones(tmp_path: Path, capsys) -> None:
    (tmp_path / "ev.json").write_text(json.dumps(EV))
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "01.json").write_text(json.dumps(card("#2", "c2c2c2c", "#1")))
    (cards / "02.json").write_text("not json")
    assert crosscheck.main(["--evidence", str(tmp_path / "ev.json"), "--cards", str(cards), "--json", str(tmp_path / "x.json")]) == 2
    assert "02.json" in capsys.readouterr().err
    assert not (tmp_path / "x.json").exists()


def test_cards_on_stdin_and_evidence_collected_again(tmp_path: Path, capsys, monkeypatch) -> None:
    import io
    import subprocess
    r = tmp_path / "r"
    r.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    g("init", "-q", "-b", "main"); g("config", "user.email", "t@e"); g("config", "user.name", "t")
    (r / "a.py").write_text("x = 1\ny = 2\nz = 3\n"); g("add", "-A"); g("commit", "-qm", "Add a")
    (r / "a.py").write_text("x = 1\ny = 20\nz = 3\n"); g("commit", "-qam", "fix: y was wrong")
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip()
    first = subprocess.run(["git", "-C", str(r), "rev-parse", "--short=8", "HEAD~1"], capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(card(head, head, first)) + "\n" + json.dumps([card(head, head, "unknown")])))
    assert crosscheck.main(["--repo", str(r), "--cards", "-"]) == 0
    out = capsys.readouterr().out
    assert "Cards: 2; culprit agrees with blame: 1" in out


def test_pr_numbers_do_not_match_by_prefix() -> None:
    result = crosscheck.crosscheck(EV, [card("#2", "c2c2c2c", "#12")])
    assert result["cases"][0]["culprit"].startswith("disagree")
    assert crosscheck.same_unit("#1", "1")
    assert not crosscheck.same_unit("#1", "#12")
    assert crosscheck.same_unit("abcdef123", "abcdef123456")


def test_all_copy_locations_must_be_decided() -> None:
    result = crosscheck.crosscheck(EV, [card("#2", "c2c2c2c", "#1", clear=["b.py:2", "c.py:9"])])
    assert result["copies_left_unchecked"] == []


def test_saved_evidence_never_recollects(tmp_path: Path, monkeypatch) -> None:
    import io
    import evidence
    saved = tmp_path / 'evidence.json'
    saved.write_text(json.dumps(EV))
    def forbidden(*args, **kwargs):
        raise AssertionError('saved evidence must not trigger git collection')
    monkeypatch.setattr(evidence, 'investigate', forbidden)
    monkeypatch.setattr('sys.stdin', io.StringIO('[]'))
    assert crosscheck.main(['--evidence', str(saved), '--cards', '-']) == 0


def test_fallback_preserves_scope_and_limits(monkeypatch) -> None:
    import io
    import evidence
    seen = {}
    def collect(repo, **kwargs):
        seen.update(kwargs)
        return EV
    monkeypatch.setattr(evidence, 'investigate', collect)
    monkeypatch.setattr('sys.stdin', io.StringIO('[]'))
    assert crosscheck.main(['--cards', '-', '--ref', 'abcdef123', '--unit', '#2',
                            '--max', '10', '--history', '20', '--max-blame-lines', '30',
                            '--min-lines', '2']) == 0
    assert seen['ref'] == 'abcdef123' and seen['unit'] == '#2'
    assert (seen['limit'], seen['history'], seen['max_blame'], seen['min_lines']) == (10, 20, 30, 2)


def _two_util_files() -> dict:
    left = [{"line": "render(x, escape=False)", "at": ["a/util.py:10", "b/util.py:11"]}]
    return {"timeline": [{"unit": "#2", "sha": "aaa1111", "introduced_by": [],
                          "commits": [{"sha": "c2c2c2c", "left_behind": left}]}],
            "left_behind": [{"unit": "#2", "commit": "c2c2c2c", "line": left[0]["line"], "at": left[0]["at"]}]}


def test_near_matches_on_path_components_only() -> None:
    assert crosscheck.near(("util.py", 10), ("a/util.py", 10))
    assert crosscheck.near(("a/util.py", 10), ("a/util.py", 12))
    assert not crosscheck.near(("a/util.py", 10), ("b/util.py", 10))
    assert not crosscheck.near(("til.py", 10), ("a/util.py", 10))              # not on a component boundary
    assert not crosscheck.near(("util.py", 10), ("a/util.py", 20))
    # a bare basename two copies share is ambiguous: it names neither
    paths = {"a/util.py", "b/util.py"}
    assert not crosscheck.near(("util.py", 10), ("a/util.py", 10), paths=paths)
    assert crosscheck.near(("a/util.py", 10), ("a/util.py", 10), paths=paths)
    assert crosscheck.near(("b/util.py", 10), ("b/util.py", 10), paths=paths)


def test_a_bare_basename_does_not_clear_two_different_files() -> None:
    ev = _two_util_files()
    r = crosscheck.crosscheck(ev, [card("#2", "c2c2c2c", "#1", siblings=[{"where": "util.py:10", "level": "read"}])])
    assert r["cases"][0]["siblings"][0]["source"] == "reader only"
    assert r["copies_left_unchecked"][0]["at"] == ["a/util.py:10", "b/util.py:11"]
    r = crosscheck.crosscheck(ev, [card("#2", "c2c2c2c", "#1", clear=["util.py:10: escaped"])])
    assert r["copies_left_unchecked"][0]["at"] == ["a/util.py:10", "b/util.py:11"]
    r = crosscheck.crosscheck(ev, [card("#2", "c2c2c2c", "#1", siblings=[{"where": "b/util.py:11", "level": "read"}])])
    assert r["cases"][0]["siblings"][0]["source"] == "both"
    assert r["copies_left_unchecked"][0]["at"] == ["a/util.py:10"]
