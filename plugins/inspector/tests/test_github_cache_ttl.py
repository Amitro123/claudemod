"""gh cache freshness: TTL, missing fetchedAt, --refresh-github, failed refresh. Fake gh runner, injectable clock.

Run: python -m pytest plugins/inspector/tests/test_github_cache_ttl.py -q
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402
from test_github_batch import Gh, MERGED  # noqa: E402

T0 = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


def _pr(labels, body, issue_labels):
    return {"title": "t", "body": body, "mergedAt": MERGED, "reviewDecision": "",
            "labels": [{"name": x} for x in labels],
            "closingIssuesReferences": [{"number": 12, "title": "i", "state": "CLOSED",
                                         "labels": [{"name": x} for x in issue_labels]}]}


def _run(prs, cache, gh, t, **kw):
    return evidence.gh_enrich("o/r", sorted(prs), gh, cache, now=lambda: t, **kw)


@pytest.fixture(params=[True, False], ids=["batch", "per-pr"])
def batch(request):
    return request.param


def test_fresh_entry_makes_no_call(tmp_path, batch):
    cache = evidence.BlameCache(str(tmp_path))
    gh = Gh({1: _pr(["bug"], "old", [])})
    _run(gh.prs, cache, gh, T0, batch=batch)
    n = len(gh.calls)
    res = _run(gh.prs, cache, gh, T0 + timedelta(days=evidence.GH_CACHE_TTL_DAYS) - timedelta(seconds=1), batch=batch)
    assert len(gh.calls) == n and res.cached == 1 and res.calls == 0


def test_expired_entry_is_read_again_and_shows_the_new_data(tmp_path, batch):
    cache = evidence.BlameCache(str(tmp_path))
    gh = Gh({1: _pr(["enhancement"], "old", ["bug"])})
    first = _run(gh.prs, cache, gh, T0, batch=batch)
    assert first.data[1]["closes"][0]["labels"] == ["bug"]
    gh.prs = {1: _pr(["bug"], "corrected", [])}
    n = len(gh.calls)
    res = _run(gh.prs, cache, gh, T0 + timedelta(days=evidence.GH_CACHE_TTL_DAYS), batch=batch)
    assert len(gh.calls) > n and res.cached == 0
    assert res.data[1]["labels"] == ["bug"] and res.data[1]["closes"][0]["labels"] == []
    assert res.bodies[1] == "corrected"
    assert evidence.gh_fix_signals(res.data[1]) == ["label: bug"]


def test_changed_labels_drop_the_fix_signal_after_expiry(tmp_path, batch):
    cache = evidence.BlameCache(str(tmp_path))
    gh = Gh({1: _pr(["bug"], "b", [])})
    assert evidence.gh_fix_signals(_run(gh.prs, cache, gh, T0, batch=batch).data[1])
    gh.prs = {1: _pr([], "b", [])}
    res = _run(gh.prs, cache, gh, T0 + timedelta(days=30), batch=batch)
    assert not evidence.gh_fix_signals(res.data.get(1, {}))


def test_entry_without_fetched_at_is_a_miss(tmp_path, batch):
    cache = evidence.BlameCache(str(tmp_path))
    gh = Gh({1: _pr(["bug"], "new", [])})
    cache.put(evidence._gh_cache_key("o/r", 1), {"gh": {"labels": ["stale"]}, "body": "stale"})
    res = _run(gh.prs, cache, gh, T0, batch=batch)
    assert res.cached == 0 and res.data[1]["labels"] == ["bug"] and res.bodies[1] == "new"
    assert "fetchedAt" in cache.get(evidence._gh_cache_key("o/r", 1))


def test_refresh_skips_the_read_and_writes(tmp_path, batch):
    cache = evidence.BlameCache(str(tmp_path))
    gh = Gh({1: _pr(["bug"], "old", [])})
    _run(gh.prs, cache, gh, T0, batch=batch)
    gh.prs = {1: _pr(["fix"], "newer", [])}
    t1 = T0 + timedelta(hours=1)
    res = _run(gh.prs, cache, gh, t1, batch=batch, refresh=True)
    assert res.cached == 0 and res.data[1]["labels"] == ["fix"]
    stored = cache.get(evidence._gh_cache_key("o/r", 1))
    assert stored["gh"]["labels"] == ["fix"] and stored["fetchedAt"] == "2026-01-10T13:00:00Z"
    gh.calls.clear()
    assert _run(gh.prs, cache, gh, t1, batch=batch).cached == 1 and not gh.calls


@pytest.mark.parametrize("mode", ["fail", "down"])
def test_failed_refresh_keeps_the_previous_entry(tmp_path, batch, mode):
    cache = evidence.BlameCache(str(tmp_path))
    gh = Gh({1: _pr(["bug"], "old", [])})
    _run(gh.prs, cache, gh, T0, batch=batch)
    key = evidence._gh_cache_key("o/r", 1)
    before = copy.deepcopy(cache.get(key))

    def broken(args):
        raise evidence.GhUnavailable("offline")
    res = _run(gh.prs, cache, broken, T0 + timedelta(hours=1), batch=batch, refresh=True)
    assert res.error and 1 not in res.data
    assert cache.get(key) == before


def test_failed_fetch_of_an_expired_entry_caches_nothing_new(tmp_path):
    cache = evidence.BlameCache(str(tmp_path))
    def broken(args):
        raise evidence.GhUnavailable("offline")
    res = _run({1: None}, cache, broken, T0)
    assert res.error and cache.get(evidence._gh_cache_key("o/r", 1)) is None


def test_garbage_or_future_timestamp_is_a_miss():
    ok = {"gh": {}, "fetchedAt": "2026-01-10T12:00:00Z"}
    assert evidence._gh_fresh(ok, T0)
    assert not evidence._gh_fresh({**ok, "fetchedAt": "yesterday"}, T0)
    assert not evidence._gh_fresh({**ok, "fetchedAt": None}, T0)
    assert not evidence._gh_fresh(ok, T0 - timedelta(days=1))


def test_help_documents_the_flag():
    import subprocess
    out = subprocess.run([sys.executable, str(Path(evidence.__file__)), "--help"], capture_output=True, text=True).stdout
    assert "--refresh-github" in out and "--no-cache" in out
