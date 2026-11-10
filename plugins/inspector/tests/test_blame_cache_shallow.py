"""The persistent blame cache is bypassed on a shallow repository and survives (hits) on a full one.
Real git in tmp_path only. Run: python -m pytest plugins/inspector/tests/test_blame_cache_shallow.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
import evidence  # noqa: E402

pytestmark = pytest.mark.slow


def g(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def origin(tmp_path):
    o = tmp_path / "origin"
    o.mkdir()
    g(o, "init", "-q", "-b", "main")
    shas = []
    for f, txt, m in (("a.py", "value = bad_function()\n", "A"), ("b.txt", "x\n", "B"), ("a.py", "value = good_function()\n", "fix: wrong value")):
        (o / f).write_text(txt)
        g(o, "add", ".")
        g(o, "commit", "-q", "-m", m)
        shas.append(g(o, "rev-parse", "HEAD"))
    return o, shas


def _who(r):
    """Titles of the units the fix is blamed on (A = the real culprit, B = the shallow boundary's wrong answer)."""
    return sorted({i["title"] for u in r["timeline"] if u["is_fix"] for i in u.get("introduced_by", [])})


def _clone(tmp_path, o, *extra):
    cl = tmp_path / "clone"
    g(tmp_path, "clone", "-q", *extra, "file://" + str(o).replace("\\", "/"), str(cl))
    return cl


def test_shallow_expansion_gives_the_right_attribution(origin, tmp_path):
    cl = _clone(tmp_path, origin[0], "--depth", "2")
    folder = str(tmp_path / "cache")
    first = evidence.investigate(str(cl), "main", min_lines=1, cache_dir=folder)
    assert first["shallow"] and _who(first) == ["B"]
    assert not list(Path(folder).rglob("*.json")), "a shallow repository must not write the blame cache"
    g(cl, "fetch", "-q", "--unshallow")
    cached = evidence.investigate(str(cl), "main", min_lines=1, cache_dir=folder)
    plain = evidence.investigate(str(cl), "main", min_lines=1, use_cache=False)
    assert not cached["shallow"] and _who(plain) == ["A"] and _who(cached) == ["A"]


def test_deepening_never_serves_a_stale_entry(origin, tmp_path):
    cl = _clone(tmp_path, origin[0], "--depth", "2")
    folder = str(tmp_path / "cache")
    evidence.investigate(str(cl), "main", min_lines=1, cache_dir=folder)
    g(cl, "fetch", "-q", "--deepen", "1")
    again = evidence.investigate(str(cl), "main", min_lines=1, cache_dir=folder)
    plain = evidence.investigate(str(cl), "main", min_lines=1, use_cache=False)
    assert _who(again) == _who(plain)


def test_full_history_still_hits_the_cache(origin, tmp_path):
    o, (A, B, C) = origin
    cl = _clone(tmp_path, o)
    folder = str(tmp_path / "cache")
    r1 = evidence.investigate(str(cl), "main", min_lines=1, cache_dir=folder)
    assert list(Path(folder).rglob("*.json"))
    seen = {}
    real = evidence.BlameCache.get
    def spy(self, key):
        v = real(self, key)
        seen["hits"] = self.hits
        return v
    evidence.BlameCache.get = spy
    try:
        r2 = evidence.investigate(str(cl), "main", min_lines=1, cache_dir=folder)
    finally:
        evidence.BlameCache.get = real
    assert seen.get("hits", 0) >= 1
    assert _who(r1) == _who(r2) == ["A"]


def test_blame_cache_version_was_bumped():
    assert evidence.BLAME_CACHE_VERSION not in ("v1", "v2")
