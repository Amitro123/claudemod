"""Tests for evals/scorecard.py with synthetic data only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

import scorecard  # noqa: E402


def lead(where, verdict=None, what="something breaks", **kw):
    d = {"where": where, "what": what, "category": "broken-flow", "reach": "default-on"}
    if verdict:
        d["verdict"] = verdict
    d.update(kw)
    return d


LEADS = [lead("src/up.py:1", "REAL", "the retry counter never resets", category="security"),
         lead("src/up.py:9", "REAL-LOW", "a log line is lost"),
         lead("cfg/c.py:4", "NOT REAL", "settings rewrite on error"),
         lead("cfg/c.py:8", "UNVERIFIABLE"),
         lead("src/x.py:2")]
GOLD = [{"id": "G1", "title": "retry never resets", "paths_any": ["SRC/UP"], "words_any": ["RETRY"], "severity": "high"},
        {"id": "G2", "title": "settings rewrite", "paths_any": ["cfg/"], "words_any": ["rewrite"]}]


def score(tmp_path, leads=LEADS, *args):
    m = tmp_path / "merged.json"
    m.write_text(json.dumps(leads), encoding="utf-8")
    return scorecard.main(["score", "--merged", str(m), "--format", "json", *args])


def test_counts_precision_and_security(capsys, tmp_path) -> None:
    assert score(tmp_path, LEADS, "--date", "2026-01-01") == 0
    row = json.loads(capsys.readouterr().out)
    assert row["verdicts"] == {"REAL": 1, "REAL-LOW": 1, "UNVERIFIABLE": 1, "unverified": 1, "NOT REAL": 1}
    assert row["precision"] == 0.5 and row["unverifiable"] == 1 and row["not_real"] == 1  # 2 / (5 - 1)...
    assert row["security"] == {"labelled": 1, "survived": 1}
    assert row["gold"] is None and row["cost"] is None
    assert row["version"] == json.loads(scorecard.PLUGIN_JSON.read_text(encoding="utf-8"))["version"]


def test_gold_covered_and_uncovered(capsys, tmp_path) -> None:
    g = tmp_path / "gold.json"
    g.write_text(json.dumps(GOLD), encoding="utf-8")
    score(tmp_path, LEADS, "--gold", str(g))
    gold = json.loads(capsys.readouterr().out)["gold"]
    assert gold["items"] == 2 and gold["covered"] == 1 and gold["recall"] == 0.5
    assert gold["covered_items"][0]["id"] == "G1" and gold["covered_items"][0]["lead"] == "src/up.py:1"
    # G2 matches only a NOT REAL lead, which covers nothing
    assert [i["id"] for i in gold["uncovered_items"]] == ["G2"]


def test_same_lead_must_match_path_and_word() -> None:
    gold = [{"id": "G", "paths_any": ["a.py"], "words_any": ["leak"]}]
    split = [lead("a.py:1", what="other"), lead("b.py:1", what="a leak")]
    assert scorecard.score_gold(split, gold)["covered"] == 0
    assert scorecard.score_gold([lead("a.py:1", what="A LEAK")], gold)["covered"] == 1


def test_metrics_flat_and_nested(capsys, tmp_path) -> None:
    mt = tmp_path / "m.json"
    mt.write_text(json.dumps({"cost_usd": 3.0, "requests": 40, "minutes": 12}), encoding="utf-8")
    score(tmp_path, LEADS, "--metrics", str(mt))
    cost = json.loads(capsys.readouterr().out)["cost"]
    assert cost["cost_per_verified_lead"] == 1.5 and cost["requests"] == 40
    mt.write_text(json.dumps({"report": {"totals": {"cost_usd": 2.0, "requests": 7}}}), encoding="utf-8")
    score(tmp_path, LEADS, "--metrics", str(mt))
    cost = json.loads(capsys.readouterr().out)["cost"]
    assert cost["cost_per_verified_lead"] == 1.0 and cost["minutes"] is None


def test_no_verified_lead_gives_no_division(capsys, tmp_path) -> None:
    mt = tmp_path / "m.json"
    mt.write_text(json.dumps({"cost_usd": 1}), encoding="utf-8")
    score(tmp_path, [lead("a.py:1"), lead("b.py:1", "UNVERIFIABLE")], "--metrics", str(mt))
    row = json.loads(capsys.readouterr().out)
    assert row["cost"]["cost_per_verified_lead"] is None and row["precision"] == 0.0
    score(tmp_path, [lead("a.py:1", "UNVERIFIABLE")])
    assert json.loads(capsys.readouterr().out)["precision"] is None


def test_duplicate_clusters_are_connected_groups() -> None:
    leads = [lead("a.py:1", possible_duplicate_of=["a.py:2"]), lead("a.py:2", possible_duplicate_of=["a.py:1"]),
             lead("b.py:1", possible_duplicate_of=["b.py:2"]), lead("b.py:2"),
             lead("b.py:3", possible_duplicate_of="b.py:2"), lead("c.py:1")]
    assert scorecard.duplicate_clusters(leads) == [["a.py:1", "a.py:2"], ["b.py:1", "b.py:2", "b.py:3"]]
    assert scorecard.build_row(leads, version="x")["duplicate_clusters"] == 2


def test_markdown_table_shows_unverifiable_and_gold(capsys, tmp_path) -> None:
    row = scorecard.build_row(LEADS, GOLD, {"cost_usd": 3.0}, version="9.9.9")
    md = scorecard.markdown(row)
    assert "version 9.9.9" in md and "UNVERIFIABLE 1 left out" in md and "G1: retry never resets <- lead `src/up.py:1`" in md
    assert "Uncovered gold items:\n- G2" in md
    assert "n/a (no gold file)" in scorecard.markdown(scorecard.build_row(LEADS, version="v"))


def test_append_and_compare(capsys, tmp_path) -> None:
    h = tmp_path / "hist.jsonl"
    score(tmp_path, LEADS, "--append", str(h), "--plugin-json", str(_pj(tmp_path, "0.1.0")))
    assert scorecard.main(["compare", "--history", str(h)]) == 2  # one row is not enough
    better = LEADS + [lead("src/y.py:1", "REAL")]
    score(tmp_path, better, "--append", str(h), "--plugin-json", str(_pj(tmp_path, "0.2.0")))
    capsys.readouterr()
    rows = [json.loads(l) for l in h.read_text(encoding="utf-8").splitlines()]
    assert [r["version"] for r in rows] == ["0.1.0", "0.2.0"]
    assert scorecard.main(["compare", "--history", str(h)]) == 0
    out = capsys.readouterr().out
    assert "| version | 0.1.0 | 0.2.0 |" in out and "| leads | 5 | 6 | +1 |" in out and "| precision | 0.5 | 0.6 | +0.1 |" in out


def _pj(tmp_path, version) -> Path:
    p = tmp_path / "plugin.json"
    p.write_text(json.dumps({"version": version}), encoding="utf-8")
    return p
