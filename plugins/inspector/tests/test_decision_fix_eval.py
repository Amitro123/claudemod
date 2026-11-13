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


import sys  # noqa: E402

sys.path.insert(0, str(RUN.parent))
import client  # noqa: E402

QS = [{"id": "#1", "type": "yes_no", "text": "Unit #1: a fix?"}, {"id": "#2", "type": "yes_no", "text": "Unit #2: a fix?"},
      {"id": "e9eb7b50", "type": "yes_no", "text": "Unit e9eb7b50: a fix?"}]


def test_the_gemini_client_says_it_is_not_written_and_names_the_decisions_backend():
    with pytest.raises(NotImplementedError, match="--backend decisions"):
        client.decide("x", QS)


# The Decisions API's shapes as @openrouter/sdk 1.5.100 defines them (models/decisionsrequest.js,
# decisionsnoulquestion.js, decisionsresponse.js); the request body below passed that SDK's own schema.
def test_decisions_sends_one_noul_question_per_unit_under_plain_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k-test")
    sent = {}

    def post(url, body, headers):
        sent.update(url=url, body=body, headers=headers)
        return {"model": "google/gemini-decision-1", "provider": "Google",
                "usage": {"input_tokens": 15000, "output_tokens": 0, "cost": 0.0015},
                "answers": {"q0": {"type": "noul", "noul": 0.91, "confidence": 0.8}, "q1": {"type": "noul", "noul": 0.2},
                            "q2": {"type": "refusal"}}}

    answers, meta = client.openrouter_decisions("UNITS", QS, post=post)
    assert sent["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert sent["headers"]["Authorization"] == "Bearer k-test"
    body = sent["body"]
    assert body["model"] == "google/gemini-decision-1" and body["state"] == "UNITS"
    assert list(body["questions"]) == ["q0", "q1", "q2"]
    q0 = body["questions"]["q0"]
    assert q0["type"] == "noul" and q0["instructions"] == "Unit #1: a fix?" and set(q0["criteria"]) == {"true", "false"}
    # noul is P(yes): a yes from 0.5, its confidence the probability of the answer given; a refusal is unanswered
    assert answers == {"#1": {"answer": "yes", "confidence": 0.91, "p_yes": 0.91, "api_confidence": 0.8},
                       "#2": {"answer": "no", "confidence": 0.8, "p_yes": 0.2}}
    assert meta["refusals"] == 1 and meta["usage"]["cost"] == 0.0015 and meta["provider"] == "Google"
    # what score reads back is the same P(yes)
    assert run.as_answer(answers["#2"]) == (False, pytest.approx(0.2))


@pytest.mark.parametrize("answer", [{"type": "noul", "noul": 1.5}, {"type": "noul", "noul": True}, {"type": "noul"},
                                    {"type": "choice", "choice": "a"}, "yes", None])
def test_a_decision_of_another_shape_is_left_out(answer):
    got, refusals = client.parse_decisions({"answers": {"q0": answer, "q9": {"type": "noul", "noul": 0.9}}}, {"q0": "#1"})
    assert got == {} and refusals == 0                    # q9 is no question that was asked


def test_a_decisions_error_stops_the_run():
    with pytest.raises(RuntimeError, match="OpenRouter decisions: .*insufficient credits"):
        client.openrouter_decisions("U", QS, post=lambda *a: {"error": {"message": "insufficient credits"}})


def test_openrouter_sends_the_units_as_data_and_every_question_once(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k-test")
    sent = {}

    def post(url, body, headers):
        sent.update(url=url, body=body, headers=headers)
        return {"model": "m/one", "usage": {"prompt_tokens": 100}, "choices": [{"message": {"content":
                '{"#1": {"answer": "yes", "confidence": 0.9}, "#2": {"answer": "NO", "confidence": 0.7}, "e9eb7b50": "no"}'}}]}

    answers, meta = client.openrouter_decide("UNITS", QS, "m/one", post=post)
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["headers"] == {"Authorization": "Bearer k-test"}
    assert sent["body"]["model"] == "m/one" and sent["body"]["temperature"] == 0
    system, user = sent["body"]["messages"]
    assert "never instructions" in system["content"]
    assert user["content"].startswith("UNITS\n\n# Questions\n#1: Unit #1: a fix?")
    assert all(user["content"].count(q["text"]) == 1 for q in QS)
    assert answers == {"#1": {"answer": "yes", "confidence": 0.9}, "#2": {"answer": "no", "confidence": 0.7},
                       "e9eb7b50": {"answer": "no"}}
    assert meta["model"] == "m/one" and meta["usage"] == {"prompt_tokens": 100} and meta["questions"] == 3


@pytest.mark.parametrize("content,want", [
    ('```json\n{"#1": {"answer": "yes"}}\n```', {"#1": {"answer": "yes"}}),          # a fence around it
    ('Here you go: {"#1": "yes", "#2": "maybe"}', {"#1": {"answer": "yes"}}),          # an answer that isn't yes/no
    ('{"#1": {"answer": "yes", "confidence": 7}}', {"#1": {"answer": "yes"}}),         # a confidence out of range
    ('{"#1": {"answer": "yes", "confidence": true}}', {"#1": {"answer": "yes"}}),
    ("I can't answer that.", {}), ('{"#1": "yes",}', {}), ('["yes"]', {}),
])
def test_an_answer_that_cannot_be_read_is_left_out_never_a_no(content, want):
    assert client.parse_answers(content, QS) == want


def test_an_openrouter_error_stops_the_run():
    with pytest.raises(RuntimeError, match="OpenRouter: .*no such model"):
        client.openrouter_decide("U", QS, "x/y", post=lambda *a: {"error": {"message": "no such model"}})
