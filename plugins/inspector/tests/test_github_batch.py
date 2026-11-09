"""Batched GitHub enrichment: one `gh api graphql` call per up to 25 PRs gives the same result as one
`gh pr view` per PR; any failure or missing field falls back to the per-PR path. gh is always a mock.

Run: python -m pytest plugins/inspector/tests/test_github_batch.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402

MERGED = "2026-01-01T00:00:00Z"


def _pr(n: int) -> dict:
    d = {"title": f"t{n}", "body": f"body {n} " + "x" * 400, "mergedAt": MERGED, "reviewDecision": "",
         "labels": [{"name": "Bug"}] if n % 2 else [], "closingIssuesReferences": []}
    if n % 3 == 0:
        d["closingIssuesReferences"] = [{"number": 100 + n, "title": f"issue\n{n}", "state": "CLOSED",
                                         "labels": [{"name": "bug"}, {"name": "ui"}]}]
    return d


class Gh:
    """Answers `pr view` and `issue view` from the PR table, and `api graphql` in GraphQL shape."""

    def __init__(self, prs, graphql="ok"):
        self.prs, self.mode, self.calls = prs, graphql, []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["api", "graphql"]:
            if self.mode == "fail":
                raise evidence.GhUnavailable("graphql down")
            if self.mode == "junk":
                return "[]"
            q = next(a for a in args if a.startswith("query="))
            repo = {}
            for n in map(int, re.findall(r"pr(\d+): pullRequest", q)):
                p = self.prs.get(n)
                if p is None:
                    repo[f"pr{n}"] = None
                    continue
                refs = [{**r, "labels": {"totalCount": len(r["labels"]), "nodes": r["labels"]}}
                        for r in p["closingIssuesReferences"]]
                node = {"title": p["title"], "body": p["body"], "mergedAt": p["mergedAt"],
                        "labels": {"totalCount": len(p["labels"]), "nodes": p["labels"]},
                        "closingIssuesReferences": {"totalCount": len(refs), "nodes": refs}}
                if self.mode == "truncated" and n == 3:
                    node["labels"]["totalCount"] = 99
                if self.mode == "missing" and n == 4:
                    del node["mergedAt"]
                repo[f"pr{n}"] = node
            return json.dumps({"data": {"repository": repo}})
        assert args[:2] == ["pr", "view"]
        return json.dumps(self.prs[int(args[2])])


PRS = {n: _pr(n) for n in range(1, 8)}


def _same(a, b):
    assert json.dumps([a.data, a.bodies], sort_keys=True) == json.dumps([b.data, b.bodies], sort_keys=True)


def test_batch_equals_per_pr_and_is_one_call():
    batched, per_pr = Gh(PRS), Gh(PRS)
    a = evidence.gh_enrich("o/r", list(PRS), batched, None, workers=4)
    b = evidence.gh_enrich("o/r", list(PRS), per_pr, None, workers=4, batch=False)
    _same(a, b)
    assert a.error is None and a.calls == 1 == len(batched.calls) and b.calls == len(PRS)
    args = batched.calls[0]
    assert args[:2] == ["api", "graphql"] and "owner=o" in args and "name=r" in args
    assert 3 in a.data and a.data[3]["closes"][0]["labels"] == ["bug", "ui"]


def test_chunks_of_at_most_25():
    prs = {n: _pr(n) for n in range(1, 61)}
    gh = Gh(prs)
    res = evidence.gh_enrich("o/r", list(prs), gh, None, workers=3)
    assert res.calls == 3 and len(res.bodies) == 60
    assert all(len(re.findall(r"pullRequest", next(a for a in c if a.startswith("query=")))) <= 25 for c in gh.calls)


@pytest.mark.parametrize("mode", ["fail", "junk", "truncated", "missing"])
def test_fallback_to_per_pr_gives_the_same_result(mode):
    gh = Gh(PRS, graphql=mode)
    res = evidence.gh_enrich("o/r", list(PRS), gh, None, workers=2)
    _same(res, evidence.gh_enrich("o/r", list(PRS), Gh(PRS), None, workers=2, batch=False))
    per_pr = [c for c in gh.calls if c[0] == "pr"]
    assert len(per_pr) == {"fail": 7, "junk": 7, "truncated": 1, "missing": 1}[mode]
    assert res.error is None


def test_cached_prs_are_not_asked_again(tmp_path):
    evidence.gh_enrich("o/r", list(PRS), Gh(PRS), evidence.BlameCache(str(tmp_path)), workers=2)
    gh = Gh(PRS)
    res = evidence.gh_enrich("o/r", list(PRS), gh, evidence.BlameCache(str(tmp_path)), workers=2)
    assert gh.calls == [] and res.cached == len(PRS)


def test_bad_slug_makes_no_call():
    gh = Gh(PRS)
    for bad in ("o/r; rm -rf", "o", "o/r/x", "", "o/r name"):
        res = evidence.gh_enrich(bad, [1], gh, None)
        assert res.error and res.data == {}
    assert gh.calls == []


def test_no_gh_at_all_stops_after_the_first_per_pr_call():
    def down(args):
        raise evidence.GhUnavailable("gh is not installed")
    res = evidence.gh_enrich("o/r", [1, 2, 3], down, None, workers=1)
    assert res.data == {} and "not installed" in res.error and res.calls == 2   # one graphql, one pr view
