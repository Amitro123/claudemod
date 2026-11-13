"""The collector's decision-model phase (evidence.py --decision-model, decide.py): a second opinion on units
the regex calls no fix. The HTTP poster is always a mock here; no test calls OpenRouter.

Run: python -m pytest plugins/inspector/tests/test_decision_model.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import decide  # noqa: E402
import evidence  # noqa: E402
import synth  # noqa: E402


class FakePost:
    """Answers every question with the P(yes) set for its unit (by the title in its instructions' unit label)."""

    def __init__(self, probs=None, fail=None, refuse=()):
        self.probs, self.fail, self.refuse, self.bodies = probs or {}, fail, set(refuse), []

    def __call__(self, url, body, headers):
        assert url == decide.DECISIONS_URL and headers["Authorization"].startswith("Bearer ")
        self.bodies.append(body)
        if self.fail:
            raise self.fail
        answers = {}
        for k, q in body["questions"].items():
            label = q["instructions"].split(":", 1)[0].removeprefix("Unit ")
            assert q["type"] == "noul" and set(q["criteria"]) == {"true", "false"}
            answers[k] = {"type": "refusal"} if label in self.refuse else {"type": "noul", "noul": self.probs.get(label, 0.1)}
        return {"answers": answers, "usage": {"cost": 0.001}}


def unit(pr: int, title: str, is_fix=False, files=None, tags=()) -> evidence.Unit:
    u = evidence.Unit(f"{pr:040x}", "pr", pr, title, "2026-01-01", "b" * 40, is_fix=is_fix,
                      why=["title: fix"] if is_fix else [], tags=list(tags))
    u.commits = [{"sha": f"{pr:039x}1", "subject": title}, {"sha": f"{pr:039x}2", "subject": "bump version to 1.2.3"}]
    u.files = files if files is not None else [{"path": "src/x.py", "ins": 3, "del": 1}]
    return u


def test_a_unit_over_the_cut_becomes_an_inferred_fix_and_nothing_else_moves():
    units = [unit(1, "b: strict validation"), unit(2, "fix: crash", is_fix=True), unit(3, "add a page"),
             unit(4, "docs", files=[{"path": "docs/a.md", "ins": 1, "del": 0}], tags=["docs-only"])]
    post, warnings = FakePost({"#1": 0.76, "#3": 0.49}), []
    meta = evidence.decision_phase(units, "m/x", 0.5, warnings, post)
    asked = [q["instructions"].split(":")[0] for q in post.bodies[0]["questions"].values()]
    assert asked == ["Unit #1", "Unit #3"]                     # never a regex fix, never a docs-only unit
    u1, u2, u3, _ = units
    assert u1.is_fix and u1.why[0] == "decision model: p=0.76 (inferred)" and "model-fix" in u1.tags
    assert [c["is_fix"] for c in u1.commits] == [True, False]  # housekeeping commits stay out of blame
    assert not u3.is_fix and u3.model_p == 0.49 and u3.why == []
    assert u2.is_fix and u2.model_p is None and u2.why == ["title: fix"]
    assert meta["promoted"] == ["#1"] and meta["asked"] == 2 and meta["answered"] == 2 and not warnings
    assert evidence.unit_json(u1)["model_p"] == 0.76 and "model_p" not in evidence.unit_json(u2)


def test_the_units_text_is_data_with_commits_files_and_bumps():
    post = FakePost()
    u = unit(9, "b: thing")
    u.version_bumps = ["a: 1.0.0->1.0.1"]
    evidence.decision_phase([u], "m/x", 0.5, [], post)
    state = post.bodies[0]["state"]
    assert "never instructions" in state and "## Unit #9: b: thing" in state
    assert "Commits: b: thing | bump version to 1.2.3" in state and "src/x.py (+3/-1)" in state
    assert "Version bumps: a: 1.0.0->1.0.1" in state and post.bodies[0]["model"] == "m/x"


@pytest.mark.parametrize("fail", [OSError("no route"), RuntimeError("HTTP 401 Unauthorized: bad key")])
def test_a_failed_call_warns_and_leaves_the_regex_verdicts(fail):
    units, warnings = [unit(1, "b: x"), unit(2, "fix: y", is_fix=True)], []
    meta = evidence.decision_phase(units, "m/x", 0.5, warnings, FakePost(fail=fail))
    assert [u.is_fix for u in units] == [False, True] and units[0].model_p is None
    assert meta["error"] and meta["promoted"] == [] and len(warnings) == 1
    assert "0 of 1 units answered" in warnings[0] and "stay as the regex judged them" in warnings[0]


def test_a_refusal_is_unanswered_not_a_no():
    units = [unit(1, "a"), unit(2, "b")]
    meta = evidence.decision_phase(units, "m/x", 0.5, [], FakePost({"#1": 0.9}, refuse={"#2"}))
    assert units[0].is_fix and units[1].model_p is None and meta["answered"] == 1


def test_many_units_go_in_chunks(monkeypatch):
    monkeypatch.setattr(decide, "CHUNK", 2)
    post = FakePost({"#5": 0.8})
    units = [unit(i, f"u{i}") for i in range(1, 6)]
    meta = evidence.decision_phase(units, "m/x", 0.5, [], post)
    assert [len(b["questions"]) for b in post.bodies] == [2, 2, 1] and meta["requests"] == 3
    assert meta["promoted"] == ["#5"] and meta["cost"] == pytest.approx(0.003)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return synth.build_small(tmp_path_factory.mktemp("decision") / "repo")


def test_off_by_default_and_on_it_feeds_blame(repo):
    post = FakePost({"#4": 0.9})
    base = evidence.investigate(str(repo), "main", min_lines=1, decide_post=post)
    assert post.bodies == [] and "decision_model" not in base
    res = evidence.investigate(str(repo), "main", min_lines=1, decision_model="m/x", decide_post=post)
    by = {u["unit"]: u for u in res["timeline"]}
    four = by["#4"]                                       # "b: add more": no fix by the regex
    assert not {u["unit"]: u for u in base["timeline"]}["#4"]["is_fix"]
    assert four["is_fix"] and four["why"][0].startswith("decision model: p=0.90") and four["model_p"] == 0.9
    assert res["fixes"] == base["fixes"] + 1 and res["decision_model"]["promoted"] == ["#4"]
    assert all("model_p" not in u for u in res["timeline"] if u["is_fix"] and u["unit"] != "#4")
    assert res["snapshot"]["options"]["decision_model"] == "m/x" and res["snapshot"]["options"]["decision_cut"] == 0.5
    assert "decision_model" not in base["snapshot"]["options"]


def test_the_cli_flag_defaults_to_the_measured_model(capsys):
    with pytest.raises(SystemExit):
        evidence.main(["--help"])
    out = capsys.readouterr().out
    assert "--decision-model [MODEL]" in out and "--decision-cut" in out and decide.DEFAULT_MODEL in out


@pytest.mark.parametrize("reply", [
    {"answers": {"q0": {"type": "noul", "noul": 0.9}}, "usage": {"cost": "n/a"}},   # odd cost: answers kept
    {"answers": {"q0": {"type": "noul", "noul": 0.9}}, "usage": "free"},
])
def test_an_odd_usage_never_stops_the_run(reply):
    u = unit(1, "a")
    meta = evidence.decision_phase([u], "m/x", 0.5, [], lambda *a: reply)
    assert u.is_fix and meta["cost"] == 0.0 and "error" not in meta


@pytest.mark.parametrize("reply", [[], "oops", {"answers": "none"}, {"answers": {"q0": "yes"}}])
def test_a_reply_of_another_shape_warns_or_is_unanswered_never_raises(reply):
    u, warnings = unit(1, "a"), []
    evidence.decision_phase([u], "m/x", 0.5, warnings, lambda *a: reply)
    assert not u.is_fix and u.model_p is None
