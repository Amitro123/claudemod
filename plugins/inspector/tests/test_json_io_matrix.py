"""The run folder's JSON as an agent on another platform writes it (issue #200), read by every script that reads it.

The invariant: a file one script of the run accepts, every other script accepts, and a file one rejects, the others
reject with a message that says what to rewrite. Before #200 `lint_leads.py` (through leadsio, `utf-8-sig`) passed a
`leads.json` with a UTF-8 BOM that `plan.py --phase verify` (`utf-8`) then refused, and the orchestrator repaired it
with PowerShell, which broke it a second time.

Each row names why it was chosen. The table covers these shapes, not every way a file can be broken.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "inspect" / "scripts"))
from test_plan import exp, lead, make_run, plan  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN / "skills" / "inspect" / "scripts"
LINT = SCRIPTS / "lint_leads.py"

GOOD = json.dumps([lead(1), lead(2)])

# (id, bytes of leads.json, accepted?, words the rejection must hold, why this row)
ROWS = [
    ("bom", b"\xef\xbb\xbf" + GOOD.encode(), True, None,
     "the #200 failure: Windows PowerShell 5.1 Out-File/Set-Content -Encoding utf8 write a BOM"),
    ("bom-crlf", b"\xef\xbb\xbf" + json.dumps([lead(1), lead(2)], indent=2).replace("\n", "\r\n").encode(), True, None,
     "the same writer on Windows also writes CRLF line ends"),
    ("plain", GOOD.encode(), True, None, "the control: what merge_cards.py writes"),
    ("no-opener", GOOD[1:].encode(), False, "`[` may be missing",
     "the second #200 failure: a BOM strip that ate the `[` too"),
    ("trailing", (GOOD + GOOD).encode(), False, "trailing data",
     "two arrays in one file: an agent appended instead of rewriting"),
    ("object", json.dumps(lead(1)).encode(), False, "JSON array",
     "one lead written bare, not in an array"),
    ("empty-where", json.dumps([{**lead(1), "where": ""}]).encode(), False, "where",
     "a lead with no place to verify"),
    ("utf16", GOOD.encode("utf-16"), False, "UTF-8",
     "PowerShell 5.1's default for `>`: UTF-16 LE with its own BOM"),
]


def lint(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LINT), str(path)], capture_output=True, text=True, encoding="utf-8")


@pytest.mark.parametrize("raw,ok,words", [r[1:4] for r in ROWS], ids=[r[0] for r in ROWS])
def test_plan_verify_and_the_lint_agree_on_leads_json(tmp_path, raw, ok, words) -> None:
    run = make_run(tmp_path, 3)
    (run / "leads.json").write_bytes(raw)
    code, out, err = plan(run, "--phase", "verify")
    assert (code == 0) == ok, out + err
    if words not in ("JSON array", "where"):   # the lint also reads cards: a bare object or a card with no `where` is its input
        lint_ok = lint(run / "leads.json").returncode != 2   # 2: input the lint could not read; 1: label findings
        assert lint_ok == ok, "lint_leads.py and plan.py --phase verify must accept the same encodings and syntax"
    if ok:
        assert exp(run)["verifier_chunks"], "both leads reached a verifier"
        assert (run / "leads.json").read_bytes() == raw, "the planner reads leads.json; it never rewrites it"
    else:
        assert words.lower() in err.lower(), err
        assert "leads.json" in err and len(err.strip().splitlines()) == 1, "one line naming the file"
        assert not (run / "plan" / "expect.json").exists(), "nothing planned from a broken file"


def test_evidence_json_with_a_bom_is_read_by_the_planner(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    ev = run / "evidence.json"
    ev.write_bytes(b"\xef\xbb\xbf" + ev.read_bytes())
    code, out, err = plan(run)
    assert code == 0, out + err


def test_the_planner_writes_its_json_without_a_bom(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    (run / "leads.json").write_bytes(b"\xef\xbb\xbf" + GOOD.encode())
    assert plan(run, "--phase", "verify")[0] == 0
    for p in (run / "plan").glob("*.json"):
        assert not p.read_bytes().startswith(b"\xef\xbb\xbf"), p.name


# --- Windows 8.3 short names (issue #200 item 6) -------------------------------------------------------------------

import plan as planmod  # noqa: E402


def test_posix_expands_a_short_name_on_windows(monkeypatch) -> None:
    # The prompts of the #200 run named C:/Users/AMIT~1.ROS/...: TEMP in its short form, as Windows often sets it.
    monkeypatch.setattr(planmod, "_WINDOWS", True)
    monkeypatch.setattr(planmod.os.path, "abspath", lambda p: p)
    monkeypatch.setattr(planmod.os.path, "realpath", lambda p: p.replace("AMIT~1.ROS", "amit.rosen"))
    assert planmod.posix(r"C:\Users\AMIT~1.ROS\AppData\Local\Temp\inspector-x") == \
        "C:/Users/amit.rosen/AppData/Local/Temp/inspector-x"


def test_posix_keeps_the_path_when_expanding_fails(monkeypatch) -> None:
    # A path that does not exist yet, or a network share realpath cannot read: the absolute form, never an error.
    def boom(p):
        raise OSError("unreadable")
    monkeypatch.setattr(planmod, "_WINDOWS", True)
    monkeypatch.setattr(planmod.os.path, "abspath", lambda p: p)
    monkeypatch.setattr(planmod.os.path, "realpath", boom)
    assert planmod.posix(r"C:\X~1\run") == "C:/X~1/run"


def test_posix_leaves_other_platforms_and_long_names_alone(monkeypatch, tmp_path) -> None:
    # No `~`: no realpath, so a symlinked folder (macOS /var -> /private/var) keeps the name the user gave.
    called = []
    monkeypatch.setattr(planmod.os.path, "realpath", lambda p: called.append(p) or p)
    monkeypatch.setattr(planmod, "_WINDOWS", True)
    planmod.posix(str(tmp_path / "run"))
    monkeypatch.setattr(planmod, "_WINDOWS", False)
    planmod.posix(str(tmp_path / "RUN~1"))
    assert called == []


@pytest.mark.skipif(os.name != "nt", reason="a real 8.3 name exists only on Windows")
def test_posix_expands_a_real_short_name(tmp_path) -> None:
    import ctypes
    long_dir = tmp_path / "a folder with a long name"
    long_dir.mkdir()
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(long_dir), buf, len(buf))
    if not n or "~" not in buf.value:
        pytest.skip("8.3 names are turned off on this volume")
    assert planmod.posix(buf.value).lower() == str(long_dir.resolve()).replace("\\", "/").lower()
