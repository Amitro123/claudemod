"""Shared reader/validator (leadsio) as used by lint_leads, handoff and crosscheck: file, folder, stdin."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import crosscheck  # noqa: E402
import handoff  # noqa: E402
import leadsio  # noqa: E402
import lint_leads  # noqa: E402
import merge_cards  # noqa: E402
import merge_verdicts  # noqa: E402

GOOD = {"where": "a.py:1", "what": "w", "level": "read", "probe": "a.py:1 read"}
BAD_PAYLOADS = [
    {"complete": {"siblings": "NOT_AN_ARRAY"}},
    {"complete": {"siblings": [None]}},
    {"complete": "x"},
    [GOOD, {"complete": {"siblings": "NOT_AN_ARRAY"}}],     # mixed: no partial success
    [GOOD, 17],
    {"complete": None},                                      # explicit null is present, hence invalid
    {"complete": {"siblings": None}},
    [GOOD, {"complete": None}],
    {"complete": {"siblings": [], "checked_clear": None}},
]
VALID_PAYLOADS = [[], {}, {"complete": {"siblings": []}}, [GOOD]]


def feed(kind, tmp_path, monkeypatch, payload):
    text = json.dumps(payload)
    if kind == "stdin":
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        return "-"
    if kind == "file":
        p = tmp_path / "merged.json"
        p.write_text(text, encoding="utf-8")
        return str(p)
    d = tmp_path / "cards"
    d.mkdir()
    (d / "merged.json").write_text(text, encoding="utf-8")
    return str(d)


def run(tool, src, tmp_path, out):
    if tool == "lint":
        return lint_leads.main([src, "--strict"])
    if tool == "handoff":
        return handoff.main(["--cards", src, "--out", str(out)])
    return crosscheck.main(["--evidence", str(tmp_path / "none.json"), "--cards", src])


@pytest.mark.parametrize("tool", ["lint", "handoff", "crosscheck"])
@pytest.mark.parametrize("kind", ["file", "folder", "stdin"])
@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_malformed_container_exits_2_and_keeps_output(tool, kind, payload, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.md"
    out.write_text("previous")
    src = feed(kind, tmp_path, monkeypatch, payload)
    assert run(tool, src, tmp_path, out) == 2
    assert out.read_text() == "previous"
    assert "expected" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["file", "folder", "stdin"])
@pytest.mark.parametrize("payload", VALID_PAYLOADS)
def test_valid_containers_pass_lint(kind, payload, tmp_path, monkeypatch):
    assert lint_leads.main([feed(kind, tmp_path, monkeypatch, payload), "--strict"]) == 0


def test_error_names_file_and_item_path(tmp_path):
    p = tmp_path / "merged.json"
    p.write_text(json.dumps([GOOD, GOOD, GOOD, {"complete": {"siblings": "x"}}]))
    with pytest.raises(leadsio.LeadsError) as e:
        leadsio.read_items(str(p))
    assert "merged.json[3].complete.siblings: expected a list" in str(e.value)


def test_not_strict_does_not_downgrade_container_errors(tmp_path, capsys):
    p = tmp_path / "a.json"
    p.write_text('{"complete":{"siblings":"NOT_AN_ARRAY"}}')
    assert lint_leads.main([str(p)]) == 2


def test_handoff_accepts_a_file_path(tmp_path, capsys):
    p = tmp_path / "merged.json"
    p.write_text(json.dumps([GOOD]))
    assert handoff.main(["--cards", str(p)]) == 0
    assert "a.py:1" in capsys.readouterr().out


def test_missing_path_is_an_error(tmp_path):
    with pytest.raises(leadsio.LeadsError):
        leadsio.read_items(str(tmp_path / "nope.json"))


@pytest.mark.parametrize("payload", [{"complete": None}, {"complete": {"siblings": None}}])
@pytest.mark.parametrize("flags", [[], ["--strict"]])
def test_explicit_null_containers_exit_2_with_and_without_strict(payload, flags, tmp_path, capsys):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(payload))
    assert lint_leads.main([str(p), *flags]) == 2
    assert "expected" in capsys.readouterr().err


def test_absent_containers_are_fine_and_leads_of_ignores_nothing_valid():
    assert leadsio.leads_of([GOOD]) == [{**GOOD, "case": ""}]
    assert leadsio.leads_of([{"complete": {"siblings": []}}]) == []


def test_merge_verdicts_rejects_null_containers_in_leads(tmp_path, capsys):
    leads, verdicts = tmp_path / "l.json", tmp_path / "v.json"
    leads.write_text(json.dumps([{**GOOD, "complete": None}]))
    verdicts.write_text("[]")
    out = tmp_path / "m.json"
    out.write_text("previous")
    assert merge_verdicts.main(["--leads", str(leads), "--verdicts", str(verdicts), "--out", str(out)]) == 2
    assert out.read_text() == "previous"


@pytest.mark.parametrize("where", ["card", "sweep"])
@pytest.mark.parametrize("bad", [{"complete": None}, {"complete": {"siblings": None}}])
def test_merge_cards_rejects_null_containers(where, bad, tmp_path, capsys):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "1.json").write_text(json.dumps({"complete": {"siblings": [GOOD]}}))
    args = ["--cards", str(cards), "--expect", "1", "--out", str(tmp_path / "o.json")]
    if where == "card":
        (cards / "1.json").write_text(json.dumps(bad))
    else:
        sw = tmp_path / "s.json"
        sw.write_text(json.dumps([{**GOOD, **bad}]))
        args += ["--sweep", str(sw)]
    assert merge_cards.main(args) == 2
    assert not (tmp_path / "o.json").exists()
