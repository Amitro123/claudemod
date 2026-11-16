"""Every script that prints text an agent wrote must survive a console that cannot encode it.

Found in a live run on Windows (2026-11-16): crosscheck.py died with UnicodeEncodeError on a cp1255 console because a
card held a check mark. Only evidence.py set its streams to UTF-8; the scripts that print cards, leads and verdicts did
not. Each test runs the script as a process with PYTHONIOENCODING=cp1255 and text cp1255 cannot encode."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_crosscheck import EV, card  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "inspect" / "scripts"
MARK = "✅ done ↺"                      # a check mark and an arrow: neither is in cp1255
ENV = {**os.environ, "PYTHONIOENCODING": "cp1255", "PYTHONUTF8": "0"}
LEAD = {"where": "a.py:1", "what": f"the retry counter never resets {MARK}", "level": "read", "category": "security",
        "reach": "default-on", "reach_when": f"always {MARK}", "impact": {"text": f"uploads give up {MARK}", "level": "read"}}


def run(script: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], input=stdin.encode("utf-8"), capture_output=True, env=ENV)


def ok(p: subprocess.CompletedProcess, codes=(0,)) -> str:
    err = p.stderr.decode("utf-8", "replace")
    assert "UnicodeEncodeError" not in err and "Traceback" not in err, err
    assert p.returncode in codes, err
    return p.stdout.decode("utf-8") + err


def test_crosscheck_prints_a_card_with_a_check_mark(tmp_path) -> None:
    (tmp_path / "ev.json").write_text(json.dumps(EV), encoding="utf-8")
    cards = tmp_path / "cards"
    cards.mkdir()
    c = card("#2", "c2c2c2c", "#1")
    c["case"] = f"#2 fixed {MARK}"                           # the report prints the case, the verdict and each sibling
    c["complete"]["verdict"] = f"yes {MARK}"
    c["complete"]["siblings"] = [dict(LEAD)]
    (cards / "1.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    out = ok(run("crosscheck.py", "--evidence", str(tmp_path / "ev.json"), "--cards", str(cards)))
    assert "a.py:1" in out and MARK in out


def test_lint_leads_prints_a_message_that_quotes_the_lead(tmp_path) -> None:
    (tmp_path / "l.json").write_text(json.dumps([LEAD], ensure_ascii=False), encoding="utf-8")
    out = ok(run("lint_leads.py", str(tmp_path / "l.json")))
    assert MARK in out                                       # L3 quotes reach_when


def test_merge_cards_prints_its_lint_lines(tmp_path) -> None:
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "1.json").write_text(json.dumps({"case": "#1", "complete": {"siblings": [LEAD]}}, ensure_ascii=False), encoding="utf-8")
    out = ok(run("merge_cards.py", "--cards", str(cards), "--expect", "1", "--out", str(tmp_path / "leads.json")))
    assert MARK in out and json.loads((tmp_path / "leads.json").read_text(encoding="utf-8"))[0]["what"].endswith(MARK)


def test_merge_verdicts_and_handoff_print_to_stdout(tmp_path) -> None:
    (tmp_path / "l.json").write_text(json.dumps([LEAD], ensure_ascii=False), encoding="utf-8")
    (tmp_path / "v.json").write_text(json.dumps([{"where": "a.py:1", "verdict": "REAL", "evidence": f"ran it {MARK}"}], ensure_ascii=False), encoding="utf-8")
    out = ok(run("merge_verdicts.py", "--leads", str(tmp_path / "l.json"), "--verdicts", str(tmp_path / "v.json")))
    assert MARK in out
    (tmp_path / "m.json").write_text(out[out.index("["):out.rindex("]") + 1], encoding="utf-8")
    assert MARK in ok(run("handoff.py", "--cards", str(tmp_path / "m.json")))


@pytest.mark.parametrize("script", ["crosscheck.py", "handoff.py", "lint_leads.py", "merge_cards.py", "merge_verdicts.py",
                                    "plan.py", "premerge.py", "doctor.py", "evidence.py"])
def test_every_script_sets_its_streams_to_utf8(script) -> None:
    src = (SCRIPTS / script).read_text(encoding="utf-8")
    assert "utf8_stdio()" in src or 'reconfigure(encoding="utf-8", errors="replace")' in src, script
