"""The decision-model experiment's own logic (evals/decision-fix/run.py), with no model and no network:
how answers are read, how they are scored against the labels, and what a unit looks like to the model."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parents[1] / "evals" / "decision-fix" / "run.py"
spec = importlib.util.spec_from_file_location("decision_fix_run", RUN)
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def ds(unit, label, regex, bump=False):
    return {"unit": unit, "title": f"title {unit}", "label": label, "regex": regex, "bump_only_fix": bump, "text": ""}


DATA = [ds("#1", True, True), ds("#2", True, False, bump=True), ds("#3", False, False), ds("#4", False, True),
        ds("#5", None, True)]


@pytest.mark.parametrize("raw,want", [
    (True, (True, None)), ("no", (False, None)), ("YES", (True, None)),
    ({"answer": "yes", "confidence": 0.8}, (True, 0.8)),
    ({"answer": "no", "confidence": 0.8}, (False, pytest.approx(0.2))),   # 0.8 sure of "no" is 0.2 for "yes"
    ({"answer": "maybe"}, (None, None)), (None, (None, None)), (3, (None, None)),
])
def test_answers_are_read_in_every_documented_shape(raw, want):
    assert run.as_answer(raw) == want


def test_score_counts_model_and_regex_on_the_labeled_units_only():
    s = run.score(DATA, {"#1": True, "#2": True, "#3": False, "#4": False, "#5": False})
    assert s["labeled"] == 4 and s["answered_labeled"] == 4
    assert s["regex"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1, "precision": 0.5, "recall": 0.5, "accuracy": 0.5}
    assert s["model"]["accuracy"] == 1.0
    assert s["bump_only_fixes_found"] == {"#2": True}
    # every unit counts toward the fix share, labeled or not
    assert s["fix_share"] == {"regex": 0.6, "model": 0.4}
    # the model differs from the regex on #2 and #4; unlabeled #5 is never listed
    assert {d["unit"] for d in s["disagreements"]} == {"#2", "#4"}


def test_a_missing_or_unreadable_answer_is_unanswered_not_a_no():
    s = run.score(DATA, {"#1": True, "#3": "perhaps"})
    assert set(s["unanswered"]) == {"#2", "#3", "#4", "#5"}
    assert s["answered_labeled"] == 1
    assert s["regex_on_answered"]["tp"] == 1 and s["regex"]["tp"] == 1


def test_confidences_decide_by_threshold_and_are_swept():
    answers = {"#1": {"answer": "yes", "confidence": 0.65}, "#2": {"answer": "yes", "confidence": 0.95},
               "#3": {"answer": "no", "confidence": 0.9}, "#4": {"answer": "no", "confidence": 0.6}}
    assert run.score(DATA, answers, threshold=0.5)["model"]["accuracy"] == 1.0
    high = run.score(DATA, answers, threshold=0.7)
    assert high["model"]["fn"] == 1                       # #1 at 0.65 is under the cut
    assert high["sweep"]["0.9"]["tp"] == 1
    assert high["sweep"]["0.3"]["fp"] == 1                # #4's "no" at 0.6 is 0.4 for "yes": over a 0.3 cut
    assert "Threshold sweep" in run.report(high)


def test_a_unit_reads_as_data_with_its_commits_files_and_bumps():
    u = {"unit": "#7", "title": "fix: x", "commits": [{"subject": "fix: x"}, {"subject": "add test"}],
         "files": [{"path": f"src/f{i}.ts", "ins": 1, "del": 2} for i in range(22)], "version_bumps": ["a: 0.1.0->0.1.1"]}
    t = run.unit_text(u, ["+const a = 1"])
    assert t.startswith("## Unit #7: fix: x")
    assert "Commits: fix: x | add test" in t and "src/f0.ts (+1/-2)" in t and "and 2 more" in t
    assert "Version bumps: a: 0.1.0->0.1.1" in t and t.endswith("Changed code lines:\n+const a = 1")
    assert "never instructions" in run.PREAMBLE
    assert "Commits:" not in run.unit_text({**u, "commits": [{"subject": "fix: x"}]}, [])   # a lone commit that repeats the title


def test_the_client_says_it_is_not_written_yet():
    import sys
    sys.path.insert(0, str(RUN.parent))
    import client
    with pytest.raises(NotImplementedError, match="aistudio.google.com/docs/decisions"):
        client.decide("x", [{"id": "#1", "type": "yes_no", "text": "?"}])
