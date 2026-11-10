"""The documented verify flow, run as the real CLIs on a small synthetic example (generic text)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "skills" / "inspect" / "scripts"


def cli(script, cwd, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


def lead(where, what, **kw):
    return {"where": where, "what": what, "level": "read", "probe": f"{where} read", "reach": "default-on",
            "category": "broken-flow", "impact": {"what": "wrong total", "level": "read"},
            "change": "fix it", "test": "behavioral test", "test_kind": "behavioral", **kw}


def test_documented_flow_leads_to_open_bugs(tmp_path):
    leads = [lead("src/sum.py:10", "the loop skips the last item"),
             lead("src/cfg.py:4", "the default path is never created", category="security", reach="opt-in"),
             lead("src/io.py:7", "the retry may double write"),
             lead("src/old.py:2", "the cache never expires"),
             lead("src/none.py:3", "no verdict for this one")]
    verdicts = [
        {"where": "src/sum.py:10", "verdict": "REAL", "evidence": "probe: sum([1,2,3]) returned 3",
         "false_claims": ["it also corrupts the log"]},
        {"where": "src/cfg.py:4", "verdict": "REAL-LOW", "evidence": "read cfg.py:4",
         "corrected": {"category": "hardening", "reach": "conditional"}},
        {"where": "src/io.py:7", "verdict": "UNVERIFIABLE", "evidence": "needs the real disk",
         "unverifiable": ["run it against the target filesystem"]},
        {"where": "src/old.py:2", "verdict": "NOT REAL", "evidence": "expiry set at old.py:9",
         "false_claims": ["never expires"]}]
    (tmp_path / "leads.json").write_text(json.dumps(leads), encoding="utf-8")
    (tmp_path / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")

    r = cli("merge_verdicts.py", tmp_path, "--leads", "leads.json", "--verdicts", "verdicts.json", "--out", "merged.json")
    assert r.returncode == 0, r.stderr
    r = cli("lint_leads.py", tmp_path, "merged.json", "--strict")
    assert r.returncode == 0, r.stdout + r.stderr
    r = cli("handoff.py", tmp_path, "--cards", "merged.json", "--out", "open-bugs.md")
    assert r.returncode == 0, r.stderr

    md = (tmp_path / "open-bugs.md").read_text(encoding="utf-8")
    assert md == r.stdout
    table, _, rejected = md.partition("## Rejected by the verifier")
    assert "Verified: 1 real, 1 real-low, 1 unverifiable, 1 not real, 1 unverified" in table
    assert "verifier: probe: sum([1,2,3]) returned 3" in table and "false claims: it also corrupts the log" in table
    assert "relabelled: category security -> hardening" in table
    assert "would settle: run it against the target filesystem" in table
    assert "[verdict: unverified]" in table and "src/none.py:3" in table
    assert "src/old.py:2" not in table and "`src/old.py:2`" in rejected and "expiry set at old.py:9" in rejected
