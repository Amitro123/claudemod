"""Tests for lint_leads.py: each rule has a lead that triggers it and one that does not."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import lint_leads as L  # noqa: E402

CLEAN = {"where": "src/a.py:1", "what": "the loop skips the last item", "level": "read", "probe": "src/a.py:1 read",
         "reach": "default-on", "category": "broken-flow", "impact": {"what": "x", "level": "read"}}
SEC = {**CLEAN, "category": "security", "security_actor": "an outside PR author", "security_sink": "src/a.py:9"}


def rules(lead):
    return {r for r, _, _ in L.lint(lead)}


def with_(base, **kw):
    return {**base, **kw}


NO_SINK = {k: v for k, v in SEC.items() if k != "security_sink"}
FORCE = "the --force flag deletes files"
CASES = [
    ("L1", with_(SEC, security_actor="the repository owner"), SEC),
    ("L1", with_(SEC, security_actor="anyone with dashboard access"), SEC),
    ("L1", {k: v for k, v in SEC.items() if k != "security_actor"}, SEC),
    ("L2", with_(NO_SINK, needs_host_check=True, level="read"), with_(SEC, needs_host_check=True)),
    ("L3", with_(CLEAN, reach_when="format drift"), with_(CLEAN, reach="conditional", reach_when="format drift")),
    ("L3", with_(CLEAN, what="fails when model output varies"), CLEAN),
    ("L4", {k: v for k, v in CLEAN.items() if k != "probe"}, CLEAN),
    ("L5", with_(CLEAN, test_kind="text-pin", test="assert the text is present"),
     with_(CLEAN, test_kind="text-pin", test="assert the text, and exercise the function")),
    ("L6", with_(CLEAN, level="reproduced", impact={"what": "x", "level": "unverified"}),
     with_(CLEAN, level="reproduced", needs_host_check=True, impact={"what": "x", "level": "unverified"})),
    ("L7", with_(CLEAN, what="the check is by design wrong"),
     with_(CLEAN, what="the check is by design wrong", documented="README")),
    ("L7", with_(CLEAN, breaks="the pinned version"),
     with_(CLEAN, breaks="the pinned version", reconcile="compare lockfile")),
    ("L8", with_(CLEAN, what=FORCE, level="suspect", probe=""),
     with_(CLEAN, what=FORCE, probe="tool --help lists --force")),
    ("L8", with_(CLEAN, what="the CLI option is ignored", level="suspect", probe=""), CLEAN),
]


@pytest.mark.parametrize("rule,bad,good", CASES)
def test_rule_fires_and_stays_quiet(rule, bad, good) -> None:
    assert rule in rules(bad)
    assert rule not in rules(good)


def test_clean_lead_has_no_findings() -> None:
    assert L.lint(CLEAN) == [] and L.lint(SEC) == []


def test_l5_is_info_only() -> None:
    assert [s for r, s, _ in L.lint(with_(CLEAN, test_kind="text-pin")) if r == "L5"] == ["info"]


def test_l8_probe_for_other_tool_still_warns() -> None:
    assert "L8" in rules(with_(CLEAN, what=FORCE, probe="ran other --help"))


def run(monkeypatch, capsys, data, *args, raw=None):
    monkeypatch.setattr("sys.stdin", io.StringIO(raw if raw is not None else json.dumps(data)))
    code = L.main(["-", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


BAD = with_(CLEAN, probe="")


def test_output_line_format_and_default_exit(monkeypatch, capsys) -> None:
    code, out, _ = run(monkeypatch, capsys, [BAD])
    assert code == 0
    assert out.splitlines() == [f"src/a.py:1 | L4 | warn | {L.lint(BAD)[0][2]}"]


def test_strict_exit_codes(monkeypatch, capsys) -> None:
    assert run(monkeypatch, capsys, [BAD], "--strict")[0] == 1
    assert run(monkeypatch, capsys, [CLEAN], "--strict")[0] == 0
    code, out, _ = run(monkeypatch, capsys, [with_(CLEAN, test_kind="text-pin")], "--strict")
    assert code == 0 and "L5 | info" in out


def test_invalid_json_exits_2(monkeypatch, capsys) -> None:
    code, out, err = run(monkeypatch, capsys, None, raw="{not json")
    assert code == 2 and out == "" and "invalid input" in err


def test_empty_array_and_empty_stdin(monkeypatch, capsys) -> None:
    assert run(monkeypatch, capsys, [], "--strict")[:2] == (0, "")
    assert run(monkeypatch, capsys, None, raw="  ")[0] == 2


def test_file_and_case_card_input(tmp_path, capsys) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps([{"case": "x", "complete": {"siblings": [BAD]}}]), encoding="utf-8")
    assert L.main([str(p)]) == 0
    assert "L4" in capsys.readouterr().out
    assert L.main([str(tmp_path / "missing.json")]) == 2
