"""The collector reads GitHub through REST where GraphQL is refused, and works a unit named with --unit.

Found on a real run (2026-11-25, `/inspector:inspect since 39f97cc` in a Claude Code cloud session): GitHub GraphQL
answers HTTP 403 there, and both `gh api graphql` and `gh pr view` use it. Enrichment stopped, so a PR whose title
describes the new behaviour ("a malformed key is never sent or printed") but that closes a `bug` issue was judged
not a fix, and three of the day's five fixes got no case. SKILL.md's way back, "collect it in a run of its own
(--unit '#N')", gave no case either: the collector works only units it judges fixes.

The invariants: (1) where GraphQL is refused, labels and closing issues come from the REST API, and a closing
issue is what GitHub's own closing keywords in the PR body name; (2) a unit named with --unit is worked as a case.
The REFUSAL text and the REST answers below are copied from that session's real `gh` output (bodies cut).
gh is always a mock here; no test calls the real gh.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
import evidence  # noqa: E402
import synth  # noqa: E402

REFUSAL = ("gh failed (not logged in? try `gh auth login`): HTTP 403: GitHub GraphQL is not available from Claude "
           "Code sessions; use the REST API (gh api repos/{owner}/{repo}/...). To open a pull request, where this")
REST_PRS = {   # `gh api repos/Amitro123/claudemod/pulls/202`, the fields the collector reads
    202: {"number": 202, "title": "inspector: one reader of OPENROUTER_API_KEY; a malformed key is never sent or printed (#186)",
          "body": "Closes #186\n\n## The broken invariant\n\nPromise P20 says a secret never reaches a report.",
          "labels": [], "merged_at": "2026-11-25T16:40:47Z", "state": "closed"},
    201: {"number": 201, "title": "inspector: one BOM-tolerant reader for run-folder JSON, long Windows paths (#200)",
          "body": "Closes items 1, 2, 5 and 6 of #200. Items 3 and 4 are not in this PR.",
          "labels": [], "merged_at": "2026-11-25T14:58:00Z", "state": "closed"},
    4: {"number": 4, "title": "b: add more", "body": "fixes: #12 and Resolves o/r#13", "labels": [{"name": "enhancement"}],
        "merged_at": "2026-01-01T00:00:00Z", "state": "closed"},
}
REST_ISSUES = {   # `gh api repos/Amitro123/claudemod/issues/186`
    186: {"number": 186, "state": "closed", "labels": [{"name": "bug"}, {"name": "factory"}],
          "title": "inspector: premerge prints OPENROUTER_API_KEY in its error report when the key has a trailing newline (P20)"},
    12: {"number": 12, "state": "closed", "labels": [{"name": "bug"}], "title": "total is wrong"},
    13: {"number": 13, "state": "open", "labels": [], "title": "more is slow"},
}


class NoGraphQL:
    """gh as a Claude Code cloud session has it: everything GraphQL-backed is refused, `gh api repos/...` answers."""
    def __init__(self, refusal=REFUSAL):
        self.calls, self.refusal = [], refusal

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["api", "graphql"] or args[0] in ("pr", "issue"):
            raise evidence.GhUnavailable(self.refusal)
        assert args[0] == "api", args
        path = args[1].split("?")[0]
        if path.endswith("/pulls"):                  # the list of closed PRs, newest first
            return json.dumps([{**p, "merge_commit_sha": f"{p['number']:040d}", "head": {"ref": f"b{p['number']}"}}
                               for p in sorted(REST_PRS.values(), key=lambda p: p["merged_at"], reverse=True)]
                              + [{"number": 9, "title": "closed unmerged", "body": "", "merged_at": None}])
        if path.endswith("/files"):
            return json.dumps([{"filename": "plugins/inspector/x.py", "additions": 3, "deletions": 1}])
        kind, n = path.split("/")[-2], int(path.split("/")[-1])
        table = REST_PRS if kind == "pulls" else REST_ISSUES
        if kind == "pulls" and n not in table:       # as FakeGh does: a PR with nothing to say
            return json.dumps({"number": n, "title": "", "body": "", "labels": [], "merged_at": "2026-01-01T00:00:00Z"})
        if n not in table:
            raise evidence.GhUnavailable("gh failed: HTTP 404: Not Found")
        return json.dumps(table[n])


def test_a_pr_that_closes_a_bug_issue_is_read_through_rest() -> None:
    res = evidence.gh_enrich("Amitro123/claudemod", [202], NoGraphQL(), None)
    assert res.error is None, res.error
    gh = res.data[202]
    assert gh["closes"] == [{"number": 186, "title": REST_ISSUES[186]["title"][:evidence.GH_TEXT_CHARS],
                             "state": "CLOSED", "labels": ["bug", "factory"]}]   # the shape GraphQL gives (review of #209)
    assert evidence.gh_fix_signals(gh) == ["closes #186 (bug)"]
    assert res.bodies[202].startswith("Closes #186")


def test_rest_is_taken_once_graphql_is_refused_not_per_pr() -> None:
    gh = NoGraphQL()
    res = evidence.gh_enrich("Amitro123/claudemod", [201, 202], gh, None, batch=False)
    assert res.error is None, res.error
    assert {c[1] for c in gh.calls if c[0] == "api"} >= {"repos/Amitro123/claudemod/pulls/201",
                                                        "repos/Amitro123/claudemod/pulls/202"}, gh.calls
    assert sum(1 for c in gh.calls if c[0] == "pr") == 1, gh.calls   # the first refusal switches the run to REST


# (id, PR body, issue numbers GitHub links, why)
KEYWORDS = [
    ("closes", "Closes #186", [186], "the #202 body"),
    ("fixes-colon", "fixes: #12", [12], "a colon after the keyword is allowed"),
    ("resolved-lower", "this resolved #12.", [12], "any of close/fix/resolve and their -s/-d forms, any case"),
    ("cross-repo-same", "Resolves o/r#13", [13], "owner/repo#N naming this repository"),
    ("cross-repo-other", "Fixes other/repo#13", [], "another repository's issue is not this one's"),
    ("refs", "Refs #183", [], "#193's body: not a closing keyword, and GitHub did not close #183"),
    ("items-of", "Closes items 1, 2, 5 and 6 of #200.", [], "#201's body: the keyword is not followed by the issue"),
    ("bare", "see #186", [], "a mention is not a link"),
    ("glued", "fixes#12", [], "no space: GitHub does not link it"),
    ("two", "Fixes #12, closes #13", [12, 13], "each keyword links its own issue"),
    # review of #209: GitHub links no keyword written inside code
    ("fenced-code", "Notes\n```\nfixes #12\n```\nCloses #13", [13], "a commit message quoted in a fenced block"),
    ("inline-code", "the `fixes #12` form, and Closes #13", [13], "inline code"),
]


@pytest.mark.parametrize("body,want", [(b, w) for _, b, w, _ in KEYWORDS], ids=[k[0] for k in KEYWORDS])
def test_closing_keywords_as_github_reads_them(body, want) -> None:
    assert evidence.closing_issues(body, "o/r") == want


# Review of #209: gh's HTTP errors end with the request URL, which for `gh pr view` is the GraphQL endpoint, and its
# GraphQL errors start with `GraphQL:`. These texts follow that format (written here, not captured: in a session that
# refuses GraphQL every call gets the 403 first). Only the refusal switches the run to REST.
OTHER_GRAPHQL_FAILURES = [
    ("bad-token", "gh failed (not logged in? try `gh auth login`): HTTP 401: Bad credentials (https://api.github.com/graphql)"),
    ("rate-limit", "gh failed (not logged in? try `gh auth login`): GraphQL: API rate limit exceeded for user ID 1."),
    ("missing-pr", "gh failed (not logged in? try `gh auth login`): GraphQL: Could not resolve to a PullRequest with the number of 4."),
    ("server-error", "gh failed (not logged in? try `gh auth login`): HTTP 502: Bad Gateway (https://api.github.com/graphql)"),
]


@pytest.mark.parametrize("text", [t for _, t in OTHER_GRAPHQL_FAILURES], ids=[i for i, _ in OTHER_GRAPHQL_FAILURES])
def test_only_the_refusal_switches_to_rest(text) -> None:
    gh = NoGraphQL(refusal=text)
    res = evidence.gh_enrich("o/r", [4], gh, None, batch=False)
    assert res.error and not any(c[0] == "api" and c[1].startswith("repos/") for c in gh.calls), gh.calls
    assert evidence.graphql_refused(evidence.GhUnavailable(REFUSAL))


def test_an_answer_read_through_rest_is_not_cached() -> None:
    # Review of #209: a body parse can differ from GitHub's own closingIssuesReferences (an issue linked from the
    # sidebar), so it must not be served to a later run where GraphQL works.
    class Cache(dict):
        def __bool__(self):          # an empty store is still a store (gh_enrich tests `if cache`)
            return True

        def put(self, k, v):
            self[k] = v
    cache = Cache()
    res = evidence.gh_enrich("Amitro123/claudemod", [202], NoGraphQL(), cache, batch=False)
    assert res.data[202]["closes"] and cache == {}


def test_the_github_fallback_pages_until_it_has_n_merged_prs() -> None:
    # Review of #209: one page of closed PRs held fewer than `n` merged ones when many were closed unmerged.
    class Paged(NoGraphQL):
        def __call__(self, args):
            if args[0] == "api" and args[1].split("?")[0].endswith("/pulls"):
                self.calls.append(list(args))
                page = int(dict(kv.split("=") for kv in args[1].split("?")[1].split("&"))["page"])
                if page == 1:
                    return json.dumps([{"number": 900 + i, "title": "x", "body": "", "merged_at": None} for i in range(100)])
                if page == 2:
                    return json.dumps([{**REST_PRS[202], "merge_commit_sha": "a" * 40, "head": {"ref": "b"}}])
                return "[]"
            return super().__call__(args)
    out = evidence.github_units("Amitro123/claudemod", 1, set(), run=Paged())
    assert [u["unit"] for u in out] == ["#202"], out


def test_another_failure_is_not_taken_for_a_graphql_refusal() -> None:
    gh = NoGraphQL(refusal="gh failed (not logged in? try `gh auth login`): HTTP 401: Bad credentials")
    res = evidence.gh_enrich("o/r", [4], gh, None, batch=False)
    assert res.error and "401" in res.error and not any(c[0] == "api" and c[1].startswith("repos/") for c in gh.calls)


def test_the_run_judges_the_pr_a_fix_through_rest(tmp_path) -> None:
    r = synth.build_small(tmp_path / "repo")
    synth.run(r, "remote", "add", "origin", "https://github.com/o/r.git")
    res = evidence.investigate(str(r), "main", min_lines=1, github=True, gh_run=NoGraphQL(), workers=1, use_cache=False)
    t = {u["unit"]: u for u in res["timeline"]}
    assert t["#4"]["is_fix"] and t["#4"]["why"][0] == "closes #12 (bug)", t["#4"]["why"]   # "b: add more"
    assert not any("GitHub enrichment incomplete" in w for w in res["warnings"]), res["warnings"]


def test_a_unit_named_with_unit_is_worked_as_a_case(tmp_path) -> None:
    r = synth.build_small(tmp_path / "repo")
    res = evidence.investigate(str(r), "main", min_lines=1, unit="#4", github=False, workers=1, use_cache=False)
    u = res["timeline"][0]
    assert u["unit"] == "#4" and u["is_fix"], u["why"]                     # "b: add more": no fix word, no label
    assert any("--unit" in w for w in u["why"]), u["why"]
    assert evidence.triage(res) == ["#4"]


def test_the_github_fallback_lists_merged_prs_through_rest() -> None:
    # The collector's "GitHub fallback" (recent merged PRs, `--prs`) used `gh pr list` and `gh pr view`: GraphQL.
    out = evidence.github_units("Amitro123/claudemod", 2, set(), run=NoGraphQL())
    assert [u["unit"] for u in out] == ["#202", "#201"], out           # merged only, newest first, `n` of them
    assert out[0]["files"] == [{"path": "plugins/inspector/x.py", "ins": 3, "del": 1}]
    assert out[0]["branch"] == "b202" and out[0]["source"] == "github"


def test_a_dossier_reads_the_pr_body_through_rest(tmp_path) -> None:
    r = synth.build_small(tmp_path / "repo")
    synth.run(r, "remote", "add", "origin", "https://github.com/Amitro123/claudemod.git")
    assert evidence.pr_text(str(r), 202, run=NoGraphQL()).startswith("Closes #186")
