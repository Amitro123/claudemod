"""Tests for handoff.py: the leads go out word for word; levels only ever go down."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import handoff  # noqa: E402

# The lead behind the 2026-11-07 mistake: the readers wrote "suspect" and an untraced impact; the
# hand-written handoff said "read" and added "the commands included", which was wrong.
CARD = {"case": "#40 a346aef", "unit": "#40", "complete": {"siblings": [
    {"where": "plugins/followups/hooks/register.tsx:508", "what": "`await sync($)` in session.start has no .catch",
     "breaks": "sibling of #40", "level": "suspect",
     "impact": {"what": "session.start throws before return next(e); the pane open is skipped", "level": "unverified"},
     "change": "`.catch(() => {})` as in turn.start", "test": "a store whose get rejects"},
    {"where": "plugins/followups/hooks/register.tsx:400", "what": "`where` is not quoted in the CLAUDE.md export",
     "breaks": "P1", "level": "reproduced",
     "impact": {"what": "a backtick and a newline in where write a prose line into CLAUDE.md", "level": "reproduced",
                "source": "probe on a copy of section()"},
     "change": "quoted(i.where)", "test": "export a where holding ` and a newline"}]}}
W = "plugins/followups/hooks/register.tsx:508"


def run(monkeypatch, capsys, data, *args):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
    code = handoff.main(["--cards", "-", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_words_and_levels_go_out_as_given(monkeypatch, capsys) -> None:
    code, out, _ = run(monkeypatch, capsys, [CARD])
    assert code == 0
    row = next(l for l in out.splitlines() if W in l)
    assert row.startswith("| suspect |")
    assert "the pane open is skipped [unverified]" in row and "commands" not in row
    lines = [l for l in out.splitlines() if l.startswith("| reproduced") or l.startswith("| suspect")]
    assert lines[0].startswith("| reproduced"), "the strongest lead first"
    assert "[reproduced: probe on a copy of section()]" in out


def test_a_level_can_be_lowered_never_raised(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, [CARD], "--lower", f"{W}=read")
    assert code == 2 and "may not raise suspect to read" in err
    code, out, _ = run(monkeypatch, capsys, [CARD], "--lower", "plugins/followups/hooks/register.tsx:400=read")
    assert code == 0 and "| read | `plugins/followups/hooks/register.tsx:400`" in out


def test_notes_are_marked_and_drops_drop(monkeypatch, capsys) -> None:
    code, out, _ = run(monkeypatch, capsys, [CARD], "--note", f"{W}=the commands may not register", "--drop",
                       "plugins/followups/hooks/register.tsx:400")
    assert code == 0
    assert "**Note added after the readers, unverified:** the commands may not register" in out
    assert ":400" not in out


def test_an_investigators_leads_and_a_missing_impact(monkeypatch, capsys) -> None:
    leads = [{"where": "a.py:3", "what": "x", "level": "read", "breaks": "P2", "change": "y", "test": "z"}]
    code, out, _ = run(monkeypatch, capsys, leads)
    assert code == 0 and "| read | `a.py:3` | x | not stated [unverified] |" in out


HOST = {"case": "#9", "complete": {"siblings": [
    {"where": "a/b.ts:3", "what": "deny-list misses a kind", "breaks": "P1", "level": "read", "category": "security",
     "needs_host_check": True,
     "impact": {"what": "depends on which kinds the host sends", "level": "unverified"},
     "change": "allow-list", "test": "send kind x"},
    {"where": "a/c.ts:4", "what": "flagged by string", "breaks": "P1", "level": "suspect", "flags": ["needs-host-check"],
     "impact": {"what": "x", "level": "unverified"}, "change": "c", "test": "t"},
    {"where": "a/d.ts:5", "what": "plain", "breaks": "P1", "level": "read", "category": "broken-flow",
     "impact": {"what": "y", "level": "read", "source": "a/d.ts:9"}, "change": "c", "test": "t"}]}}


def test_needs_host_check_is_shown_next_to_the_level_and_never_raises_it(monkeypatch, capsys) -> None:
    code, out, err = run(monkeypatch, capsys, [HOST])
    assert code == 0
    rows = {l.split("`")[1]: l for l in out.splitlines() if l.startswith("| ") and "`" in l}
    assert rows["a/b.ts:3"].startswith("| read [needs-host-check] |")
    assert rows["a/c.ts:4"].startswith("| suspect [needs-host-check] |")
    assert rows["a/d.ts:5"].startswith("| read |")


def test_security_with_an_unverified_impact_warns_but_does_not_fail(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, [HOST])
    assert code == 0
    assert "a/b.ts:3" in err and "security" in err and "unverified" in err
    assert "a/d.ts:5" not in err


def _rows(out):
    return {l.split("`")[1]: l for l in out.splitlines() if l.startswith("| ") and "`" in l}


def test_change_status_unverified_for_host_checked_leads_by_default(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [HOST])
    rows = _rows(out)
    assert "| allow-list [change unverified] |" in rows["a/b.ts:3"]
    assert "[change unverified]" in rows["a/c.ts:4"]
    assert "[change unverified]" not in rows["a/d.ts:5"]


def test_explicit_change_status_wins(monkeypatch, capsys) -> None:
    card = {"case": "#9", "complete": {"siblings": [
        {**HOST["complete"]["siblings"][0], "change_status": "verified"},
        {**HOST["complete"]["siblings"][2], "change_status": "unverified"}]}}
    _, out, _ = run(monkeypatch, capsys, [card])
    rows = _rows(out)
    assert "[change unverified]" not in rows["a/b.ts:3"]
    assert "[change unverified]" in rows["a/d.ts:5"]


def test_garbage_change_status_never_raises(monkeypatch, capsys) -> None:
    lead = {"where": "a.py:1", "what": "x", "level": "read", "change": "c", "change_status": ["?"], "reach": 5}
    code, out, _ = run(monkeypatch, capsys, [lead])
    assert code == 0 and "a.py:1" in out


def test_reach_is_shown_in_the_level_cell_and_breaks_ties(monkeypatch, capsys) -> None:
    def lead(w, reach=None, lvl="read"):
        d = {"where": w, "what": "x", "level": lvl, "breaks": "P1", "change": "c", "test": "t"}
        if reach is not None:
            d["reach"] = reach
        return d
    leads = [lead("o.py:1", "opt-in: flag defaults off"), lead("m.py:1"), lead("d.py:1", "default-on"),
             lead("u.py:1", "unknown"), lead("s.py:1", "opt-in", "suspect")]
    _, out, _ = run(monkeypatch, capsys, leads)
    rows = _rows(out)
    assert rows["o.py:1"].endswith("| opt-in: flag defaults off |")
    assert rows["d.py:1"].endswith("| default-on |")
    assert rows["m.py:1"].endswith("| unknown |") and rows["u.py:1"].endswith("| unknown |")
    assert rows["o.py:1"].startswith("| read |"), "the level cell is unchanged"
    order = [l.split("`")[1] for l in out.splitlines() if l.startswith("| ") and "`" in l]
    assert order == ["d.py:1", "m.py:1", "u.py:1", "o.py:1", "s.py:1"], "default-on before opt-in; unknown keeps input order"


def test_reach_next_to_needs_host_check(monkeypatch, capsys) -> None:
    lead = {**HOST["complete"]["siblings"][0], "reach": "opt-in"}
    _, out, _ = run(monkeypatch, capsys, [{"case": "x", "complete": {"siblings": [lead]}}])
    row = _rows(out)["a/b.ts:3"]
    assert row.startswith("| read [needs-host-check] |") and row.endswith("| opt-in |")


RULE_FILES = ["skills/inspect/SKILL.md", "agents/case-reader.md", "agents/investigator.md",
              "skills/inspect/references/case-file.md"]
PLUGIN = Path(__file__).parent.parent


def test_the_new_rule_text_is_in_all_four_files() -> None:
    for f in RULE_FILES:
        t = " ".join((PLUGIN / f).read_text(encoding="utf-8").split())
        assert "name the input, the boundary and the sink" in t.lower(), f
        assert "change_status" in t, f
        assert "`reach`" in t, f


def test_skill_md_stays_within_its_size_budget() -> None:
    words = len((PLUGIN / "skills/inspect/SKILL.md").read_text(encoding="utf-8").split())
    assert words <= 4450, words
