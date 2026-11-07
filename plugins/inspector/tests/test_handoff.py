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
    assert "the pane open is skipped [unverified: no source]" in row and "commands" not in row
    assert row.endswith("| case-reader, card 1 (#40 a346aef) |"), "who claimed it"
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
    assert code == 0 and "| read | `a.py:3` | x | not stated [unverified: no source] |" in out
    assert "[one direction only, what it breaks not stated]" in out and "kind not stated: z" in out
    assert out.rstrip().endswith("| investigator |")


def test_an_impact_without_a_source_is_unverified_whatever_its_level(monkeypatch, capsys) -> None:
    lead = {"where": "b.py:9", "what": "m", "level": "read", "impact": {"what": "the commands don't register", "level": "read"}}
    code, out, _ = run(monkeypatch, capsys, [lead])
    assert "the commands don't register [unverified: no source]" in out
    lead["impact"]["source"] = "b.py:12 registers after the call"
    code, out, _ = run(monkeypatch, capsys, [lead])
    assert "[read: b.py:12 registers after the call]" in out


def test_two_ways_to_fix_and_a_test_the_harness_cant_run(monkeypatch, capsys) -> None:
    lead = {"where": "c.py:1", "what": "exclude anchored at the top", "level": "read", "by": "investigator",
            "changes": [{"what": "prefix with git rev-parse --show-prefix", "breaks": "nothing outside this project"},
                        {"what": "unanchored **/.claude/brain/", "breaks": "also excludes other projects' .claude/brain/"}],
            "test": {"kind": "function-level", "how": "the pattern for prefix sub/", "why_not_automated": "a hook that throws is skipped"}}
    code, out, _ = run(monkeypatch, capsys, [lead])
    assert "A) prefix with git rev-parse --show-prefix (breaks: nothing outside this project) · B) unanchored" in out
    assert "function-level: the pattern for prefix sub/ (not automated: a hook that throws is skipped)" in out
