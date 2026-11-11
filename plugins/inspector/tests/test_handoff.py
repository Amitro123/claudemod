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
    assert row.startswith("| suspect [production: unknown] [verdict: unverified] |")
    assert "the pane open is skipped [unverified]" in row and "commands" not in row
    lines = [l for l in out.splitlines() if l.startswith("| reproduced") or l.startswith("| suspect")]
    assert lines[0].startswith("| reproduced"), "the strongest lead first"
    assert "[reproduced: probe on a copy of section()]" in out


def test_a_level_can_be_lowered_never_raised(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, [CARD], "--lower", f"{W}=read")
    assert code == 2 and "may not raise suspect to read" in err
    code, out, _ = run(monkeypatch, capsys, [CARD], "--lower", "plugins/followups/hooks/register.tsx:400=read")
    assert code == 0 and "| read [production: unknown] [verdict: unverified] | `plugins/followups/hooks/register.tsx:400`" in out


def test_notes_are_marked_and_drops_drop(monkeypatch, capsys) -> None:
    code, out, _ = run(monkeypatch, capsys, [CARD], "--note", f"{W}=the commands may not register", "--drop",
                       "plugins/followups/hooks/register.tsx:400")
    assert code == 0
    assert "**Note added after the readers, unverified:** the commands may not register" in out
    assert ":400" not in out


def test_an_investigators_leads_and_a_missing_impact(monkeypatch, capsys) -> None:
    leads = [{"where": "a.py:3", "what": "x", "level": "read", "breaks": "P2", "change": "y", "test": "z"}]
    code, out, _ = run(monkeypatch, capsys, leads)
    assert code == 0 and "| read [production: unknown] [verdict: unverified] | `a.py:3` | x | not stated [unverified] |" in out


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
    assert rows["a/b.ts:3"].startswith("| read [needs-host-check] [production: unknown] [verdict: unverified] |")
    assert rows["a/c.ts:4"].startswith("| suspect [needs-host-check] [production: unknown] [verdict: unverified] |")
    assert rows["a/d.ts:5"].startswith("| read [production: unknown] [verdict: unverified] |")


TRIPLE = {"security_input": "req.body.url (a/b.ts:2)", "security_boundary": "no allow-list (a/b.ts:3)",
          "security_sink": "fetch(url) (a/b.ts:9)", "security_actor": "an end user who submits the url"}
FIELDS = ("security_input", "security_boundary", "security_sink", "security_actor")


COUNTER = {"security_counter": "the actor already has repo write access",
           "security_counter_refuted_by": "a/b.ts:3 accepts input from any tenant"}


def _sec(**kw):
    lead = {**HOST["complete"]["siblings"][0], "probe": "a/b.ts:3 read", **COUNTER, **kw}
    return [{"case": "#9", "complete": {"siblings": [lead]}}]


def test_security_with_the_triple_and_unverified_impact_does_not_warn(monkeypatch, capsys) -> None:
    code, out, err = run(monkeypatch, capsys, _sec(**TRIPLE))
    assert code == 0 and "warning" not in err and err == ""


def test_the_triple_is_rendered_in_the_row(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, _sec(**TRIPLE))
    row = _rows(out)["a/b.ts:3"]
    assert ("in: req.body.url (a/b.ts:2) | boundary: no allow-list (a/b.ts:3) | sink: fetch(url) (a/b.ts:9)"
            " | actor: an end user who submits the url") in row


def test_security_missing_a_field_warns_and_names_it(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, _sec(**{**TRIPLE, "security_boundary": "  "}))
    assert code == 0 and "a/b.ts:3" in err and "security_boundary" in err
    assert "security_input" not in err and "security_sink" not in err and "security_actor" not in err
    code, _, err = run(monkeypatch, capsys, _sec())
    assert code == 0 and all(k in err for k in FIELDS)


def test_security_missing_only_the_actor_warns_naming_actor(monkeypatch, capsys) -> None:
    for actor in (None, "", "  "):
        lead = {k: v for k, v in TRIPLE.items() if k != "security_actor"}
        if actor is not None:
            lead["security_actor"] = actor
        code, _, err = run(monkeypatch, capsys, _sec(**lead))
        assert code == 0 and "security_actor" in err and "a/b.ts:3" in err
        assert "security_input" not in err and "security_sink" not in err


def test_non_security_with_an_actor_does_not_warn(monkeypatch, capsys) -> None:
    _, out, err = run(monkeypatch, capsys, _sec(category="hardening", security_actor="a vendor"))
    assert err == "" and "actor: a vendor" in out


def test_non_security_with_the_fields_prints_them_without_warning(monkeypatch, capsys) -> None:
    _, out, err = run(monkeypatch, capsys, _sec(category="broken-flow", **TRIPLE))
    assert err == "" and "sink: fetch(url) (a/b.ts:9)" in out


def test_non_security_without_fields_prints_no_triple(monkeypatch, capsys) -> None:
    _, out, err = run(monkeypatch, capsys, _sec(category="broken-flow"))
    assert err == "" and "in:" not in out


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
    def lead(w, reach=None, lvl="read", when=None):
        d = {"where": w, "what": "x", "level": lvl, "breaks": "P1", "change": "c", "test": "t"}
        if reach is not None:
            d["reach"] = reach
        if when is not None:
            d["reach_when"] = when
        return d
    leads = [lead("o.py:1", "opt-in", when="flag defaults off"), lead("m.py:1"), lead("d.py:1", "default-on"),
             lead("u.py:1", "unknown"), lead("s.py:1", "opt-in", "suspect"),
             lead("c.py:1", "conditional", when="format drift")]
    _, out, _ = run(monkeypatch, capsys, leads)
    rows = _rows(out)
    assert rows["o.py:1"].endswith("| opt-in: flag defaults off |")
    assert rows["c.py:1"].endswith("| conditional: format drift |")
    assert rows["d.py:1"].endswith("| default-on |")
    assert rows["m.py:1"].endswith("| unknown |") and rows["u.py:1"].endswith("| unknown |")
    assert rows["o.py:1"].startswith("| read [production: unknown] [verdict: unverified] |"), "the level cell is unchanged"
    order = [l.split("`")[1] for l in out.splitlines() if l.startswith("| ") and "`" in l]
    assert order == ["d.py:1", "c.py:1", "m.py:1", "u.py:1", "o.py:1", "s.py:1"],         "default-on, conditional, unknown, opt-in; ties keep input order"


def test_reach_with_inline_text_still_sorts_and_prints(monkeypatch, capsys) -> None:
    leads = [{"where": "o.py:1", "what": "x", "level": "read", "reach": "opt-in: flag"},
             {"where": "c.py:1", "what": "x", "level": "read", "reach": "conditional: race"}]
    _, out, _ = run(monkeypatch, capsys, leads)
    assert [l.split("`")[1] for l in out.splitlines() if l.startswith("| ") and "`" in l] == ["c.py:1", "o.py:1"]
    assert _rows(out)["c.py:1"].endswith("| conditional: race |")


def test_not_verified_prints_under_the_impact_and_is_no_level(monkeypatch, capsys) -> None:
    lead = {"where": "a.py:1", "what": "x", "level": "read", "impact": {"what": "bad", "level": "read", "source": "a.py:2"},
            "not_verified": ["also after reload", "format Y fails"]}
    _, out, _ = run(monkeypatch, capsys, [lead])
    row = _rows(out)["a.py:1"]
    assert "bad [read: a.py:2] not verified: also after reload; format Y fails |" in row
    assert row.startswith("| read [production: unknown] [verdict: unverified] |")
    _, out, _ = run(monkeypatch, capsys, [{**lead, "not_verified": "oops"}, {**lead, "where": "b.py:1", "not_verified": 5}])
    assert "not verified: oops" in _rows(out)["a.py:1"] and "not verified" not in _rows(out)["b.py:1"]


def test_reach_next_to_needs_host_check(monkeypatch, capsys) -> None:
    lead = {**HOST["complete"]["siblings"][0], "reach": "opt-in"}
    _, out, _ = run(monkeypatch, capsys, [{"case": "x", "complete": {"siblings": [lead]}}])
    row = _rows(out)["a/b.ts:3"]
    assert row.startswith("| read [needs-host-check] [production: unknown] [verdict: unverified] |") and row.endswith("| opt-in |")


LABELS = "skills/inspect/references/labels.md"
POINTERS = ["skills/inspect/SKILL.md", "agents/case-reader.md", "agents/investigator.md",
            "skills/inspect/references/case-file.md"]
PLUGIN = Path(__file__).parent.parent


def _text(f):
    return " ".join((PLUGIN / f).read_text(encoding="utf-8").split())


def test_labels_md_is_the_single_source_of_the_rules() -> None:
    t = _text(LABELS)
    assert "name the input, the boundary, the sink and the actor" in t.lower()
    assert "`change_status`" in t and "`reach`" in t and "`reach_when`" in t and "`not_verified`" in t
    assert "could not already cross" in t and "`broken-flow`, not security" in t
    assert all(f"`{k}`" in t for k in FIELDS)
    assert "other than the repository owner or its maintainers" in t
    assert "trigger or the sink's behaviour in the real environment was not observed" in t
    for w in ("`default-on`", "`conditional`", "`opt-in`", "`unknown`"):
        assert w in t
    assert "traced or run" in t


def test_the_other_files_point_to_labels_md_and_carry_no_copy() -> None:
    for f in POINTERS:
        t = _text(f)
        assert "references/labels.md" in t, f
        assert "could not already cross" not in t, f
    for f in ("agents/case-reader.md", "agents/investigator.md"):
        assert "`security_actor`" in _text(f) and "`reach_when`" in _text(f) and "`not_verified`" in _text(f), f


def _lead(**kw):
    base = {"where": "a.py:1", "what": "w", "breaks": "P2", "level": "reproduced", "change": "c", "test": "t",
            "impact": {"what": "i", "level": "read", "source": "a.py:2"}}
    base.update(kw)
    return [base]


def test_probe_is_printed_and_no_warning(monkeypatch, capsys) -> None:
    code, out, err = run(monkeypatch, capsys, _lead(probe="tool --help: no -R flag"))
    assert code == 0 and "probe: tool --help: no -R flag" in out and "probe" not in err


def test_missing_probe_warns_for_reproduced_and_read_not_suspect(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, _lead())
    assert code == 0 and "a.py:1" in err and "probe" in err
    code, _, err = run(monkeypatch, capsys, _lead(level="read", probe=""))
    assert code == 0 and "a.py:1" in err and "probe" in err
    code, _, err = run(monkeypatch, capsys, _lead(level="suspect"))
    assert code == 0 and "probe" not in err


def test_test_kind_is_printed_and_text_pin_is_weak(monkeypatch, capsys) -> None:
    _, out, err = run(monkeypatch, capsys, _lead(probe="p", test_kind="behavioral"))
    assert "[test: behavioral]" in out and "weak" not in out
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p", test_kind="text-pin"))
    assert "[test: text-pin] [weak: pins text only]" in out
    _, out, err = run(monkeypatch, capsys, _lead(probe="p"))
    assert "[test: unknown]" in out and "test_kind" not in err
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p", test_kind="manual"))
    assert "[test: manual]" in out


def test_downstream_is_printed_only_when_given(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p", downstream="new vulns still fail the gate"))
    assert "downstream: new vulns still fail the gate" in out
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p"))
    assert "downstream" not in out


def test_skill_md_stays_within_its_size_budget() -> None:
    words = len((PLUGIN / "skills/inspect/SKILL.md").read_text(encoding="utf-8").split())
    assert words <= 3900, words


def test_the_investigator_case_file_carries_the_leads_as_a_json_block() -> None:
    for f in ["agents/investigator.md", "skills/inspect/references/case-file.md"]:
        t = " ".join((PLUGIN / f).read_text(encoding="utf-8").split())
        assert "fenced ```json block" in t and "not only a table" in t, f


def test_producer_trace_checklist_exists_and_is_pointed_to() -> None:
    t = (PLUGIN / "skills/inspect/references/producers.md").read_text(encoding="utf-8")
    assert 0 < len(t.splitlines()) <= 40
    for f in ("skills/inspect/SKILL.md", "agents/investigator.md", "agents/case-reader.md"):
        assert "references/producers.md" in _text(f), f


def test_reconcile_is_printed_only_when_given(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p", reconcile="30-day spend: table sum vs the vendor billing page"))
    assert "reconcile: 30-day spend: table sum vs the vendor billing page" in out
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p"))
    assert "reconcile" not in out


def test_reconcile_checklist_exists_and_is_pointed_to() -> None:
    t = (PLUGIN / "skills/inspect/references/reconcile.md").read_text(encoding="utf-8")
    assert 0 < len(t.splitlines()) <= 35
    for f in ("skills/inspect/SKILL.md", "agents/investigator.md", "agents/case-reader.md",
              "skills/inspect/references/case-file.md"):
        assert "references/reconcile.md" in _text(f) or "reconcile.md" in _text(f), f
        assert "Checks against the source of truth" in _text(f) or "reconcile.md" in _text(f), f


def test_security_counter_is_printed_in_the_quadruple_cell_without_warning(monkeypatch, capsys) -> None:
    _, out, err = run(monkeypatch, capsys, _sec(**TRIPLE))
    row = _rows(out)["a/b.ts:3"]
    assert "actor: an end user who submits the url | counter: the actor already has repo write access" in row
    assert "| refuted by: a/b.ts:3 accepts input from any tenant)" in row
    assert err == ""


def test_security_missing_the_counter_or_refutation_warns_naming_it(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, _sec(**TRIPLE, security_counter=""))
    assert code == 0 and "a/b.ts:3" in err and "security_counter" in err and "security_counter_refuted_by" not in err
    code, _, err = run(monkeypatch, capsys, _sec(**TRIPLE, security_counter_refuted_by=" "))
    assert code == 0 and "a/b.ts:3" in err and "security_counter_refuted_by" in err
    assert "missing: security_counter," not in err


def test_non_security_with_the_counter_fields_does_not_warn(monkeypatch, capsys) -> None:
    _, out, err = run(monkeypatch, capsys, _sec(category="hardening"))
    assert err == "" and "counter: the actor already has repo write access" in out
    _, _, err = run(monkeypatch, capsys, _sec(category="hardening", security_counter="", security_counter_refuted_by=""))
    assert err == ""


def test_production_tag_defaults_to_unknown_and_sorts_yes_first_even_above_a_higher_level(monkeypatch, capsys) -> None:
    def lead(w, prod=None, reach=None, lvl="read", **kw):
        d = {"where": w, "what": "x", "level": lvl, "probe": "p"}
        if prod:
            d["observed_in_production"] = prod
        if reach:
            d["reach"] = reach
        return {**d, **kw}
    leads = [lead("d.py:1", reach="default-on"), lead("n.py:1", "no", "default-on"),
             lead("y.py:1", "yes", "opt-in", observed_source="job history"), lead("s.py:1", "yes", lvl="suspect"),
             lead("u.py:1", "unknown", "conditional")]
    _, out, _ = run(monkeypatch, capsys, leads)
    rows = _rows(out)
    assert rows["d.py:1"].startswith("| read [production: unknown] [verdict: unverified] |")
    assert rows["n.py:1"].startswith("| read [production: no] [verdict: unverified] |")
    assert rows["y.py:1"].startswith("| read [production: yes: job history] [verdict: unverified] |")
    assert [l.split("`")[1] for l in out.splitlines() if l.startswith("| ") and "`" in l] == [
        "y.py:1", "s.py:1", "d.py:1", "n.py:1", "u.py:1"], "yes first (level, then reach, inside it), then the rest"


def test_production_tag_sits_after_needs_host_check(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, _sec(**TRIPLE, observed_in_production="yes"))
    assert _rows(out)["a/b.ts:3"].startswith("| read [needs-host-check] [production: yes] [verdict: unverified] |")


def test_documented_is_printed_under_the_impact_only_when_given(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p", documented="README: a batch with a duplicate name is refused",
                                               reconcile="rows per day vs source"))
    assert "documented: README: a batch with a duplicate name is refused" in out
    _, out, _ = run(monkeypatch, capsys, _lead(probe="p"))
    assert "documented" not in out


def test_documented_without_reconcile_or_production_yes_warns(monkeypatch, capsys) -> None:
    code, _, err = run(monkeypatch, capsys, _lead(probe="p", documented="test_x pins it"))
    assert code == 0 and "a.py:1" in err and "documented" in err and "reconcile" in err
    _, _, err = run(monkeypatch, capsys, _lead(probe="p", documented="test_x pins it", reconcile="freshness query"))
    assert err == ""
    _, _, err = run(monkeypatch, capsys, _lead(probe="p", documented="test_x pins it", observed_in_production="yes"))
    assert err == ""
    _, _, err = run(monkeypatch, capsys, _lead(probe="p", documented="test_x pins it", observed_in_production="no"))
    assert "documented" in err
    _, _, err = run(monkeypatch, capsys, _lead(probe="p", documented=""))
    assert err == ""


def test_the_agents_point_to_the_counter_and_documented_fields() -> None:
    for f in ("agents/case-reader.md", "agents/investigator.md"):
        t = _text(f)
        assert "`security_counter`" in t and "`documented`" in t and "`observed_in_production`" in t, f
        assert "references/labels.md" in t, f


def test_verdict_false_claims_and_relabel_are_printed_and_sorted(monkeypatch, capsys) -> None:
    def lead(w, verdict=None, **kw):
        d = {"where": w, "what": "x", "level": "read", "probe": "p", "reach": "default-on", "category": "broken-flow"}
        return {**d, **({"verdict": verdict} if verdict else {}), **kw}
    leads = [lead("u.py:1"), lead("n.py:1", "NOT REAL"), lead("v.py:1", "UNVERIFIABLE"), lead("l.py:1", "REAL-LOW"),
             lead("r.py:1", "REAL", false_claims=["it crashes", "it loses data"], original_category="security",
                  original_reach="opt-in")]
    _, out, _ = run(monkeypatch, capsys, leads)
    rows = _rows(out)
    assert "[verdict: unverified]" in rows["u.py:1"] and "n.py:1" not in rows   # NOT REAL: own section, not the table
    assert "false claims: it crashes; it loses data" in rows["r.py:1"]
    assert "relabelled: category security -> broken-flow" in rows["r.py:1"] and "relabelled: reach opt-in -> default-on" in rows["r.py:1"]
    assert "relabelled" not in rows["l.py:1"] and "false claims" not in rows["l.py:1"]
    assert [l.split("`")[1] for l in out.splitlines() if l.startswith("| ") and "`" in l] == [
        "r.py:1", "l.py:1", "v.py:1", "u.py:1"]
    assert out.split("## Rejected by the verifier")[1].count("`n.py:1`") == 1
    assert "Verified: 1 real, 1 real-low, 1 unverifiable, 1 not real, 1 unverified" in out


def test_no_verified_header_without_any_verdict(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [CARD])
    assert "Verified:" not in out


def test_merge_verdicts_output_renders_through_handoff(tmp_path, monkeypatch, capsys) -> None:
    import merge_verdicts
    leads = [{"where": "a.py:1", "what": "w1", "level": "read", "probe": "p", "category": "security", "reach": "opt-in"},
             {"where": "b.py:2", "what": "w2", "level": "read", "probe": "p"}]
    verdicts = [{"where": "a.py:1", "verdict": "REAL-LOW", "false_claims": ["attacker controls the input"],
                 "corrected": {"category": "broken-flow", "reach": "conditional"}, "unverifiable": ["host behaviour"]}]
    merged, _ = merge_verdicts.merge(leads, verdicts)
    code, out, _ = run(monkeypatch, capsys, merged)
    row = _rows(out)["a.py:1"]
    assert code == 0 and "[verdict: REAL-LOW]" in row and "false claims: attacker controls the input" in row
    assert "relabelled: category security -> broken-flow" in row and "not verified: host behaviour" in row
    assert "[verdict: unverified]" in _rows(out)["b.py:2"]


def _verdict_flow(monkeypatch, capsys, leads, verdicts):
    import merge_verdicts
    merged, _ = merge_verdicts.merge(leads, verdicts)
    return run(monkeypatch, capsys, merged)


def _l(where, what="w", **kw):
    return {"where": where, "what": what, "level": "read", "probe": "p", "reach": "default-on", "category": "broken-flow", **kw}


def test_unverifiable_keeps_verdict_and_what_would_settle_it(monkeypatch, capsys) -> None:
    _, out, _ = _verdict_flow(monkeypatch, capsys, [_l("a.py:1", not_verified=["own note"])],
                              [{"where": "a.py:1", "verdict": "UNVERIFIABLE", "evidence": "no host",
                                "unverifiable": ["run it on the target host"]}])
    row = _rows(out)["a.py:1"]
    assert "[verdict: UNVERIFIABLE]" in row and "would settle: run it on the target host" in row
    assert "verifier: no host" in row and "not verified: own note" in row


def test_rejected_subclaim_visible_while_mechanism_is_real(monkeypatch, capsys) -> None:
    _, out, _ = _verdict_flow(monkeypatch, capsys, [_l("a.py:1")],
                              [{"where": "a.py:1", "verdict": "REAL", "evidence": "probe shows the loop skip",
                                "false_claims": ["it also loses data"]}])
    row = _rows(out)["a.py:1"]
    assert "[verdict: REAL]" in row and "false claims: it also loses data" in row
    assert "verifier: probe shows the loop skip" in row


def test_not_real_goes_to_rejected_section_only(monkeypatch, capsys) -> None:
    _, out, _ = _verdict_flow(monkeypatch, capsys, [_l("a.py:1", "keep me"), _l("b.py:2", "claims a crash")],
                              [{"where": "a.py:1", "verdict": "REAL", "evidence": "ok"},
                               {"where": "b.py:2", "verdict": "NOT REAL", "evidence": "guarded at c.py:5",
                                "false_claims": ["crash"]}])
    table, _, rejected = out.partition("## Rejected by the verifier")
    assert "b.py:2" not in table and "a.py:1" in table
    assert "`b.py:2`" in rejected and "guarded at c.py:5" in rejected and "crash" in rejected and "claims a crash" in rejected
    assert "a.py:1" not in rejected
    assert "Verified: 1 real, 0 real-low, 0 unverifiable, 1 not real, 0 unverified" in out


def test_no_rejected_section_without_rejections(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [CARD])
    assert "Rejected by the verifier" not in out


def test_real_low_keeps_corrected_labels_and_missing_verdict_is_visibly_unverified(monkeypatch, capsys) -> None:
    _, out, _ = _verdict_flow(monkeypatch, capsys, [_l("a.py:1", category="security", reach="opt-in"), _l("b.py:2")],
                              [{"where": "a.py:1", "verdict": "REAL-LOW", "evidence": "e",
                                "corrected": {"category": "hardening", "reach": "conditional"}}])
    rows = _rows(out)
    assert "relabelled: category security -> hardening" in rows["a.py:1"]
    assert "relabelled: reach opt-in -> conditional" in rows["a.py:1"]
    assert "[verdict: unverified]" in rows["b.py:2"]


def test_drop_not_real_still_removes_the_lead_completely(tmp_path, monkeypatch, capsys) -> None:
    import merge_verdicts
    merged, _ = merge_verdicts.merge([_l("a.py:1"), _l("b.py:2")], [{"where": "b.py:2", "verdict": "NOT REAL"}])
    merged = [m for m in merged if m["verdict"] != "NOT REAL"]
    _, out, _ = run(monkeypatch, capsys, merged)
    assert "b.py:2" not in out and "Rejected by the verifier" not in out


def test_production_yes_outranks_a_higher_level_lead_of_unknown_state(monkeypatch, capsys) -> None:
    def lead(w, lvl, prod=None):
        return {"where": w, "what": "x", "level": lvl, "probe": "p", **({"observed_in_production": prod} if prod else {})}
    leads = [lead("u.py:1", "reproduced"), lead("y.py:1", "suspect", "yes"), lead("r.py:1", "read", "yes"),
             lead("n.py:1", "reproduced", "no")]
    _, out, _ = run(monkeypatch, capsys, leads)
    assert [l.split("`")[1] for l in out.splitlines() if l.startswith("| ") and "`" in l] == [
        "r.py:1", "y.py:1", "u.py:1", "n.py:1"], "within yes, level still orders; unknown or no never beat yes"


def _banner_lead(where: str, verdict: str | None = None) -> dict:
    d = {"where": where, "what": f"claim at {where}", "level": "read", "probe": "p"}
    if verdict:
        d["verdict"] = verdict
    return d


def test_banner_absent_when_every_lead_has_a_verdict(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [_banner_lead("a.py:1", "REAL"), _banner_lead("b.py:2", "REAL-LOW")])
    assert "UNVERIFIED" not in out and out.startswith("# ")


def test_banner_first_line_with_exact_counts_when_some_unverified(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [_banner_lead("a.py:1", "REAL"), _banner_lead("b.py:2"), _banner_lead("c.py:3")])
    assert out.splitlines()[0] == ("UNVERIFIED: 2 of 3 leads were not checked by an independent verifier; "
                                   "treat them as candidates, not findings.")


def test_banner_counts_all_when_none_verified(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [_banner_lead("a.py:1"), _banner_lead("b.py:2")])
    assert out.splitlines()[0].startswith("UNVERIFIED: 2 of 2 leads were not checked")


def test_banner_counts_rejected_as_verified(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [_banner_lead("a.py:1", "NOT REAL"), _banner_lead("b.py:2")])
    assert out.splitlines()[0].startswith("UNVERIFIED: 1 of 2 leads were not checked")


def test_no_banner_for_empty_input(monkeypatch, capsys) -> None:
    _, out, _ = run(monkeypatch, capsys, [])
    assert "UNVERIFIED" not in out and "no leads" in out
