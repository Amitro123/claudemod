"""evals/gate/timeline.py: phase timings from file mtimes, on synthetic run folders planned by plan.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from test_plan import lead, make_run, plan

TIMELINE = Path(__file__).resolve().parent.parent / "evals" / "gate" / "timeline.py"
T0 = 1_800_000_000.0


def tl(run: Path, *args):
    p = subprocess.run([sys.executable, str(TIMELINE), "--run", str(run), *args],
                       capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout, p.stderr


def at(run: Path, rel: str, sec: float, body: str = "{}") -> None:
    p = run / rel
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    os.utime(p, (T0 + sec, T0 + sec))


def parallel_run(tmp: Path, n_leads: int = 3) -> tuple[Path, dict]:
    """7 cases (3 readers + 3 sweepers), planned through verify, every file at a known second."""
    run = make_run(tmp, 7)
    assert plan(run)[0] == 0
    at(run, "evidence.json", 0)
    at(run, "brief.md", 60, "brief")
    exp = json.loads((run / "plan" / "expect.json").read_text(encoding="utf-8"))
    readers = [d for p in exp["phases"] for d in p["dispatch"] if d["agent"] == "inspector:case-reader"]
    for k, d in enumerate(readers):
        for j, out in enumerate(d["outputs"]):
            at(run, out, 60 + 100 + 10 * k + j)  # reader-3 ends last: 60 + 120 + its last card
    for k in (1, 2, 3):
        at(run, f"sweep-{k}.json", 60 + 200 + k * 10, "[]")  # sweep-3 at +230 is the slowest of the phase
    (run / "leads.json").write_text(json.dumps([lead(i) for i in range(n_leads)]), encoding="utf-8")
    at(run, "leads.json", 300)
    at(run, "dedupe.md", 301, "log")
    assert plan(run, "--phase", "verify")[0] == 0
    at(run, "plan/chunk-1.json", 310)
    at(run, "plan/expect.json", 310)
    at(run, "verdicts-1.json", 500, "[]")
    at(run, "merged.json", 505, "[]")
    at(run, "open-bugs.md", 510, "# bugs")
    return run, json.loads((run / "plan" / "expect.json").read_text(encoding="utf-8"))


def test_json_gives_each_phase_its_duration_and_the_critical_path(tmp_path) -> None:
    run, _ = parallel_run(tmp_path)
    code, out, err = tl(run, "--json")
    assert code == 0, err
    d = json.loads(out)
    assert d["seconds"] == 510 and d["missing"] == []
    steps = {s["name"]: s for s in d["steps"]}
    assert list(steps) == ["collect", "brief", "investigate (wave 1 of 2)", "investigate (wave 2 of 2)", "merge",
                           "plan verify", "verify", "merge verdicts", "handoff"]
    assert steps["brief"]["seconds"] == 60
    w1, w2 = steps["investigate (wave 1 of 2)"], steps["investigate (wave 2 of 2)"]
    # 3 readers and the longest sweeper (OUTSIDE-IN, sweep-3) in wave 1; code and docs take slots as they free up,
    # so wave 2 starts when wave 1's first agent finished (reader-1's last card, +162), not when wave 1 ended.
    assert [a["label"] for a in w1["agents"]][-1] == "sweeper-3"
    assert w1["end"] - T0 == 290 and w2["start"] - T0 == 162 and w2["start"] < w1["end"]
    assert w2["end"] - T0 == 280 and w2["seconds"] == 118
    assert steps["merge"]["seconds"] == 11 and steps["verify"]["seconds"] == 190
    assert steps["handoff"]["seconds"] == 5
    rel = {a["label"]: a["rel"] for a in w2["agents"]}
    assert rel["sweeper-2"] == max(rel.values())
    crit = {c["phase"]: (c["agent"], c["seconds"]) for c in d["critical_path"]}
    assert crit["brief"] == ("brief-writer", 60)
    assert crit["verify"] == ("verifier-1", 190)
    assert crit["investigate (wave 1 of 2)"][0] == "sweeper-3" and crit["investigate (wave 2 of 2)"][0] == "sweeper-2"
    assert any("stub" in n for n in d["notes"])


def test_text_lists_phases_agents_and_the_limit_of_mtimes(tmp_path) -> None:
    run, _ = parallel_run(tmp_path)
    code, out, _ = tl(run)
    assert code == 0
    assert "8m30.0s" in out  # the whole run
    assert "Critical path" in out and "- verify: verifier-1 3m10.0s" in out
    assert "brief-writer" in out and "+1m00.0s" in out
    assert "cards/" in out and "stub write is not recoverable" in out


def test_missing_planned_files_are_named_and_exit_one(tmp_path) -> None:
    run, _ = parallel_run(tmp_path)
    (run / "sweep-2.json").unlink()
    (run / "open-bugs.md").unlink()
    code, out, _ = tl(run, "--json")
    assert code == 1
    d = json.loads(out)
    assert set(d["missing"]) == {"sweep-2.json", "open-bugs.md"}
    agent = [a for s in d["steps"] if s["kind"] == "agents" for a in s["agents"] if a["label"] == "sweeper-2"][0]
    assert agent["end"] is None and agent["missing"] == ["sweep-2.json"]
    code, out, _ = tl(run)
    assert code == 1 and "Missing planned files (2)" in out


def test_before_the_verify_plan_the_timeline_stops_at_the_merge(tmp_path) -> None:
    run = make_run(tmp_path, 7)
    assert plan(run)[0] == 0
    at(run, "evidence.json", 0)
    at(run, "brief.md", 30, "brief")
    code, out, _ = tl(run, "--json")
    d = json.loads(out)
    assert code == 1  # cards and sweeps not written yet
    assert [s["name"] for s in d["steps"]][-1] == "merge"
    assert any("verify not planned" in n for n in d["notes"])
    assert d["steps"][1]["seconds"] == 30


def test_single_investigator_has_no_merge_step(tmp_path) -> None:
    run = make_run(tmp_path, 3)
    assert plan(run)[0] == 0
    at(run, "evidence.json", 0)
    (run / "leads.json").write_text("[]", encoding="utf-8")
    at(run, "leads.json", 400)
    assert plan(run, "--phase", "verify")[0] == 0
    at(run, "plan/expect.json", 405)
    at(run, "merged.json", 406, "[]")
    at(run, "open-bugs.md", 407, "# none")
    code, out, err = tl(run, "--json")
    assert code == 0, err
    d = json.loads(out)
    assert [s["name"] for s in d["steps"]] == ["collect", "investigate", "plan verify", "merge verdicts", "handoff"]
    assert d["critical_path"] == [{"phase": "investigate", "agent": "investigator", "seconds": 400}]


def test_unreadable_input_exits_two(tmp_path) -> None:
    assert tl(tmp_path / "nope")[0] == 2
    run = make_run(tmp_path, 7)
    assert tl(run)[0] == 2  # no plan/expect.json
    (run / "plan").mkdir()
    (run / "plan" / "expect.json").write_text("{not json", encoding="utf-8")
    code, _, err = tl(run)
    assert code == 2 and "expect.json" in err
