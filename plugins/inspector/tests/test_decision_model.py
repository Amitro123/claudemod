"""The collector's decision-model phase (evidence.py --decision-model, decide.py): a second opinion on units
the regex calls no fix. The HTTP poster is always a mock here; no test calls OpenRouter.

Run: python -m pytest plugins/inspector/tests/test_decision_model.py -q
"""
from __future__ import annotations

import json
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
    assert u.is_fix and "error" not in meta
    assert meta["cost"] is None and meta["known_cost"] == 0.0 and meta["cost_complete"] is False, \
        "an unknown cost is not $0 (2026-11-14 review, O114-01)"


def test_a_total_cost_only_when_every_request_reported_one():
    def run(costs):
        replies = iter([{"answers": {"q0": {"type": "noul", "noul": 0.1}}, **({"usage": {"cost": c}} if c is not None else {})}
                        for c in costs])
        texts = {f"#{i}": "x" for i in range(len(costs) * decide.CHUNK)}
        return decide.ask(texts, "m/x", lambda *a: next(replies))[1]
    known = run([0.001, 0.002])
    assert known["cost"] == pytest.approx(0.003) and known["cost_complete"] is True
    assert run([0.0])["cost"] == 0.0, "a reported zero stays zero"
    missing = run([None, None])
    assert missing["cost"] is None and missing["known_cost"] == 0.0 and missing["cost_complete"] is False
    mixed = run([0.001, None])
    assert mixed["cost"] is None and mixed["known_cost"] == pytest.approx(0.001) and mixed["cost_complete"] is False
    failed = decide.ask({"#1": "x"}, "m/x", lambda *a: (_ for _ in ()).throw(OSError("down")))[1]
    assert failed["cost"] is None and failed["cost_complete"] is False


@pytest.mark.parametrize("reply", [[], "oops", {"answers": "none"}, {"answers": {"q0": "yes"}}])
def test_a_reply_of_another_shape_warns_or_is_unanswered_never_raises(reply):
    u, warnings = unit(1, "a"), []
    evidence.decision_phase([u], "m/x", 0.5, warnings, lambda *a: reply)
    assert not u.is_fix and u.model_p is None



def test_a_promoted_unit_whose_commits_say_fix_blames_only_those_commits():
    """2026-11-14 inspection: #73, a feature PR promoted by the model, had its whole-feature commit marked a fix."""
    u = unit(73, "inspector 0.2.0: a bug detective")
    u.commits = [{"sha": "1" * 40, "subject": "inspector: the bug detective (feature)", "is_fix": False},
                 {"sha": "2" * 40, "subject": "fix: run folder survives the sandbox", "is_fix": True},
                 {"sha": "3" * 40, "subject": "bump version to 0.2.0", "is_fix": False}]
    evidence.decision_phase([u], "m/x", 0.5, [], FakePost({"#73": 0.8}))
    assert u.is_fix and [c["is_fix"] for c in u.commits] == [False, True, False]


# --- 2026-11-15: one email-like string voided all 89 answers (403 "content filter: [EMAIL]") ----------------------

class FilterPost:
    """Refuses (403) any request whose state holds a unit in `bad`; answers 0.3 for the rest."""

    def __init__(self, bad=()):
        self.bad, self.calls = set(bad), 0

    def __call__(self, url, body, headers):
        self.calls += 1
        if any(f"## Unit {b}:" in body["state"] for b in self.bad):
            raise RuntimeError('HTTP 403 Forbidden: {"error":{"message":"Request blocked by content filter: [EMAIL]","code":403}}')
        return {"answers": {k: {"type": "noul", "noul": 0.3} for k in body["questions"]}, "usage": {"cost": 0.001}}


def texts_of(n: int) -> dict[str, str]:
    return {f"#{i}": f"## Unit #{i}: t{i}" for i in range(1, n + 1)}


def test_scrub_replaces_emails_in_every_string_and_keeps_the_json_valid():
    body = {"state": "## Unit 1: x - Co-Authored-By: Claude <noreply@anthropic.com>\nb\nuser@example.org",
            "q": {"k": ["a.b+c@d.co.il", 3, None]}}
    s = decide.scrub(body)
    assert "@" not in json.dumps(s) and "<[address]>" in s["state"] and s["q"]["k"] == ["[address]", 3, None]
    assert "\nb\n" in s["state"] and decide.scrub(s) == s       # a newline before an address survives; idempotent
    assert json.loads(json.dumps(s)) == s


def test_post_sends_the_scrubbed_body(monkeypatch):
    sent = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"answers": {}}'

    def fake_urlopen(req, timeout=0):
        sent["data"] = req.data
        return Reply()

    monkeypatch.setattr(decide.urllib.request, "urlopen", fake_urlopen)
    decide._post(decide.DECISIONS_URL, {"state": "x <a@b.com>"}, {})
    assert b"a@b.com" not in sent["data"] and b"[address]" in sent["data"]


def test_one_refused_unit_costs_only_itself():
    post = FilterPost(bad=["#13"])
    out, meta = decide.ask(texts_of(20), "m/x", post)
    assert set(out) == {f"#{i}" for i in range(1, 21)} - {"#13"} and meta["answered"] == 19
    assert list(meta["skipped"]) == ["#13"] and "403" in meta["skipped"]["#13"] and "error" not in meta
    assert post.calls <= 11                       # narrowing 20 units down to one takes about 2 * log2(20) requests


def test_an_auth_failure_is_not_split():
    post = FakePost(fail=RuntimeError("HTTP 401 Unauthorized: Missing Authentication header"))
    out, meta = decide.ask(texts_of(10), "m/x", post)
    assert out == {} and len(post.bodies) == 1 and meta["error"] and not meta["skipped"]


def test_the_extra_request_budget_counts_requests_sent_not_splits():
    """2026-11-15 review R137-01: the budget was spent once per split and each split sent two requests, so a fully
    refused 41-unit request made 81 calls against a documented 40 extra. It is now paid before each extra send."""
    post = FilterPost(bad=[f"#{i}" for i in range(1, 42)])
    out, meta = decide.ask(texts_of(41), "m/x", post)
    assert post.calls <= 1 + decide.MAX_EXTRA, post.calls
    assert meta["attempts"] == post.calls and meta["requests"] == 0, "attempts are visible; requests stay the answered ones"
    assert out == {} and meta["error"] and not meta["skipped"]


def test_the_budget_is_shared_across_chunks_and_answers_are_kept(monkeypatch):
    monkeypatch.setattr(decide, "CHUNK", 10)
    monkeypatch.setattr(decide, "MAX_EXTRA", 6)
    post = FilterPost(bad=["#3", "#13", "#23", "#33"])
    out, meta = decide.ask(texts_of(40), "m/x", post)
    assert post.calls <= 4 + 6 and meta["attempts"] == post.calls
    assert "#1" in out and "#3" not in out, "answers before the budget ran out are kept"
    assert "used up" in meta["error"] and "not asked" in meta["error"]


def test_a_request_wide_400_stops_at_once_and_blames_no_unit():
    """A 400 for the whole request (a model id the service doesn't know) used to be split down to every unit:
    10 units cost 19 requests and the run read as 10 per-unit refusals, with no error."""
    post = FakePost(fail=RuntimeError('HTTP 400 Bad Request: {"error":"invalid model id m/x"}'))
    out, meta = decide.ask(texts_of(10), "m/x", post)
    assert len(post.bodies) == 1 and meta["error"].startswith("RuntimeError: HTTP 400") and not meta["skipped"]


def test_every_unit_refused_on_its_own_is_a_request_wide_error():
    post = FilterPost(bad=[f"#{i}" for i in range(1, 5)])
    out, meta = decide.ask(texts_of(4), "m/x", post)
    assert out == {} and not meta["skipped"] and "request-wide" in meta["error"]


def test_a_lost_reply_after_a_paid_one_leaves_the_cost_incomplete():
    """2026-11-14 recheck, still open in #137: a success then a lost response reported cost_complete True."""
    calls = []

    def post(url, body, headers):
        calls.append(1)
        if len(calls) == 1:
            return {"answers": {k: {"type": "noul", "noul": 0.1} for k in body["questions"]}, "usage": {"cost": 0.001}}
        raise OSError("response lost")
    out, meta = decide.ask(texts_of(decide.CHUNK + 1), "m/x", post)
    assert meta["cost"] is None and meta["known_cost"] == pytest.approx(0.001) and meta["cost_complete"] is False
    assert len(out) == decide.CHUNK and meta["error"].startswith("OSError")


def test_a_pinned_version_is_not_an_address():
    assert decide.scrub("bump react@18.3.1, mail a.b@c-d.co.il") == "bump react@18.3.1, mail [address]"


def test_a_key_that_is_a_pasted_command_sends_nothing_and_is_not_echoed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "$env:OPENROUTER_API_KEY = (Get-Clipboard).Trim()")
    post = FakePost()
    out, meta = decide.ask(texts_of(3), "m/x", post)
    assert out == {} and post.bodies == [] and "whitespace" in meta["error"] and "Get-Clipboard" not in meta["error"]


def test_a_key_with_a_trailing_newline_is_trimmed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abc\n")
    seen = {}

    def post(url, body, headers):
        seen.update(headers)
        return {"answers": {}}

    decide.ask(texts_of(1), "m/x", post)
    assert seen["Authorization"] == "Bearer sk-or-v1-abc"


def test_the_collector_names_the_units_the_service_refused():
    units, warnings = [unit(1, "b: a"), unit(2, "b: b"), unit(3, "b: c")], []
    meta = evidence.decision_phase(units, "m/x", 0.5, warnings, FilterPost(bad=["#2"]))
    assert list(meta["skipped"]) == ["#2"] and meta["answered"] == 2
    assert units[1].model_p is None and units[0].model_p == 0.3 and units[2].model_p == 0.3
    assert len(warnings) == 1 and "#2" in warnings[0] and "refused" in warnings[0]
