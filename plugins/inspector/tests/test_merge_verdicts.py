"""Tests for merge_verdicts.py: the verifier's verdicts are merged into the leads by `where`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import merge_verdicts  # noqa: E402


def lead(where, **kw):
    return {"where": where, "what": "w", "category": "P1", "reach": "default-on", **kw}


def verdict(where, v="REAL", **kw):
    return {"where": where, "verdict": v, "evidence": "probe", "corrected": {}, "false_claims": [], **kw}


def run(tmp_path, capsys, leads, verdicts, *args):
    lf, vf, out = tmp_path / "l.json", tmp_path / "v.json", tmp_path / "o.json"
    out.unlink(missing_ok=True)
    lf.write_text(leads if isinstance(leads, str) else json.dumps(leads), encoding="utf-8")
    vf.write_text(verdicts if isinstance(verdicts, str) else json.dumps(verdicts), encoding="utf-8")
    code = merge_verdicts.main(["--leads", str(lf), "--verdicts", str(vf), "--out", str(out), *args])
    merged = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return code, merged, capsys.readouterr().err


def test_match_and_merge(tmp_path, capsys) -> None:
    code, m, err = run(tmp_path, capsys, [lead("a.py:1", not_verified=["x"])],
                       [verdict("a.py:1", false_claims=["claim 2"], unverifiable=["host format"])])
    assert code == 0
    assert m[0]["verdict"] == "REAL" and m[0]["verified_by"] == "verifier"
    assert m[0]["false_claims"] == ["claim 2"] and m[0]["not_verified"] == ["x", "host format"]
    assert "REAL: 1" in err


def test_relabel_keeps_original(tmp_path, capsys) -> None:
    code, m, err = run(tmp_path, capsys, [lead("a.py:1")],
                       [verdict("a.py:1", corrected={"category": "P3", "reach": "opt-in", "test_kind": "behavioral"})])
    assert m[0]["category"] == "P3" and m[0]["original_category"] == "P1"
    assert m[0]["reach"] == "opt-in" and m[0]["original_reach"] == "default-on"
    assert m[0]["test_kind"] == "behavioral"
    assert "relabelled: 1" in err


def test_same_label_is_not_a_relabel(tmp_path, capsys) -> None:
    _, m, err = run(tmp_path, capsys, [lead("a.py:1")], [verdict("a.py:1", corrected={"category": "P1"})])
    assert "original_category" not in m[0] and "relabelled: 0" in err


def test_drop_not_real_option(tmp_path, capsys) -> None:
    leads, vs = [lead("a.py:1"), lead("b.py:2")], [verdict("a.py:1", "NOT REAL"), verdict("b.py:2")]
    _, kept, _ = run(tmp_path, capsys, leads, vs)
    assert [x["verdict"] for x in kept] == ["NOT REAL", "REAL"]
    _, dropped, _ = run(tmp_path, capsys, leads, vs, "--drop-not-real")
    assert [x["where"] for x in dropped] == ["b.py:2"]


def test_unmatched_verdict_exits_2(tmp_path, capsys) -> None:
    code, m, err = run(tmp_path, capsys, [lead("a.py:1")], [verdict("zzz.py:9")])
    assert code == 2 and m is None and "zzz.py:9" in err


def test_missing_verdict_is_unverified(tmp_path, capsys) -> None:
    code, m, err = run(tmp_path, capsys, [lead("a.py:1"), lead("b.py:2")], [verdict("a.py:1")])
    assert code == 0 and m[1]["verdict"] == "unverified" and "verified_by" not in m[1]
    assert "unverified: 1" in err


def test_invalid_json_exits_2(tmp_path, capsys) -> None:
    code, m, err = run(tmp_path, capsys, [lead("a.py:1")], "{not json")
    assert code == 2 and m is None and "JSON" in err
    code, m, err = run(tmp_path, capsys, '{"a": 1}', [verdict("a.py:1")])
    assert code == 2 and "array" in err


def test_duplicate_where_in_leads_is_an_error(tmp_path, capsys):
    code, merged, err = run(tmp_path, capsys, [lead("a.py:1"), lead("a.py:1")], [verdict("a.py:1", "NOT REAL")], "--drop-not-real")
    assert code == 2 and merged is None
    assert "a.py:1" in err and "unique" in err


def test_conflicting_verdicts_for_one_where_is_an_error(tmp_path, capsys):
    vs = [verdict("a.py:1", "REAL"), verdict("a.py:1", "NOT REAL")]
    code, merged, err = run(tmp_path, capsys, [lead("a.py:1")], vs)
    assert code == 2 and merged is None and "a.py:1" in err and "disagree" in err
    code, _, _ = run(tmp_path, capsys, [lead("a.py:1")], vs[::-1])
    assert code == 2


def test_identical_duplicate_verdicts_are_allowed(tmp_path, capsys):
    code, merged, _ = run(tmp_path, capsys, [lead("a.py:1")], [verdict("a.py:1"), verdict("a.py:1")])
    assert code == 0 and [m["verdict"] for m in merged] == ["REAL"]


def test_unique_locations_unchanged_and_drop_only_the_verdict_holder(tmp_path, capsys):
    code, merged, _ = run(tmp_path, capsys, [lead("a.py:1"), lead("a.py:2"), lead("a.py:3")],
                          [verdict("a.py:2", "NOT REAL")], "--drop-not-real")
    assert code == 0
    assert [(m["where"], m["verdict"]) for m in merged] == [("a.py:1", "unverified"), ("a.py:3", "unverified")]


def test_verdict_matching_no_lead_still_errors(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys, [lead("a.py:1")], [verdict("zzz:9")])
    assert code == 2 and "zzz:9" in err


def test_repeated_verdicts_flags_all_honoured_and_counted(tmp_path, capsys) -> None:
    lf, out = tmp_path / "l.json", tmp_path / "o.json"
    lf.write_text(json.dumps([lead("a.py:1"), lead("b.py:2")]), encoding="utf-8")
    v1, v2 = tmp_path / "v1.json", tmp_path / "v2.json"
    v1.write_text(json.dumps([verdict("a.py:1", "REAL")]), encoding="utf-8")
    v2.write_text(json.dumps([verdict("b.py:2", "NOT REAL")]), encoding="utf-8")
    code = merge_verdicts.main(["--leads", str(lf), "--verdicts", str(v1), "--verdicts", str(v2), "--out", str(out)])
    err = capsys.readouterr().err
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and [m["verdict"] for m in merged] == ["REAL", "NOT REAL"]
    assert f"verdicts file {v1}: 1 verdicts" in err and f"verdicts file {v2}: 1 verdicts" in err


def test_output_is_written_atomically(tmp_path, capsys, monkeypatch) -> None:
    """A write that fails part-way leaves the previous output intact and no stray temp file behind."""
    import os
    lf, vf, out = tmp_path / "l.json", tmp_path / "v.json", tmp_path / "o.json"
    lf.write_text(json.dumps([lead("a.py:1")]), encoding="utf-8")
    vf.write_text(json.dumps([verdict("a.py:1")]), encoding="utf-8")
    out.write_text("previous run", encoding="utf-8")

    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", broken)
    try:
        merge_verdicts.main(["--leads", str(lf), "--verdicts", str(vf), "--out", str(out)])
    except OSError:
        pass
    assert out.read_text(encoding="utf-8") == "previous run"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["l.json", "o.json", "v.json"]


def test_output_keeps_unix_newlines(tmp_path, capsys) -> None:
    run(tmp_path, capsys, [lead("a.py:1")], [verdict("a.py:1")])
    assert b"\r\n" not in (tmp_path / "o.json").read_bytes()


def test_empty_leads_need_no_verdict_file_and_write_an_empty_array(tmp_path) -> None:
    """R062-03: a run with no lead to verify still gets merged.json."""
    import subprocess
    import sys
    script = Path(__file__).parent.parent / "skills" / "inspect" / "scripts" / "merge_verdicts.py"
    (tmp_path / "leads.json").write_text("[]", encoding="utf-8")
    p = subprocess.run([sys.executable, str(script), "--leads", str(tmp_path / "leads.json"), "--out", str(tmp_path / "merged.json")],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads((tmp_path / "merged.json").read_text(encoding="utf-8")) == []


def test_leads_without_any_verdict_file_are_still_refused(tmp_path) -> None:
    import subprocess
    import sys
    script = Path(__file__).parent.parent / "skills" / "inspect" / "scripts" / "merge_verdicts.py"
    (tmp_path / "leads.json").write_text(json.dumps([{"where": "a.py:1", "what": "x y z w", "level": "read"}]), encoding="utf-8")
    p = subprocess.run([sys.executable, str(script), "--leads", str(tmp_path / "leads.json"), "--out", str(tmp_path / "merged.json")],
                       capture_output=True, text=True)
    assert p.returncode == 2 and not (tmp_path / "merged.json").exists()


def test_malformed_verdict_entries_exit_2_naming_each(tmp_path, capsys) -> None:
    """Second 2026-11-14 inspection: ["oops"], [null] or a string `corrected` ended in an AttributeError (exit 1)."""
    for bad, needle in (('["oops"]', "expected an object, got str"), ("[null]", "got NoneType"),
                        (json.dumps([verdict("a.py:1", corrected="x")]), "`corrected` must be an object"),
                        (json.dumps([{"verdict": "REAL"}]), "no `where`")):
        code, m, err = run(tmp_path, capsys, [lead("a.py:1")], bad)
        assert code == 2 and m is None and needle in err, (bad, err)
