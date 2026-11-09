"""Precision fixes: patch bump is no fix signal, removal units carry no culprits, copies-left-behind
ignore imports/comments/descriptions, and --path is repeatable. Tiny synthetic repositories."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
import evidence  # noqa: E402

BUMP = ["plugins/a/.claude-plugin/plugin.json: 0.2.0->0.2.1"]


def unit(title: str, commits: list[str], bumps=None) -> evidence.Unit:
    u = evidence.Unit("a" * 40, "pr", 7, title, "2026-01-01", "b" * 40, version_bumps=list(bumps or []))
    u.commits = [{"sha": f"{i:040x}", "subject": s, "parent": "b" * 40} for i, s in enumerate(commits)]
    u.files = [{"path": "plugins/a/x.js", "ins": 3, "del": 1}]
    return u


# ---- 1. a patch version bump is not a fix signal ------------------------------------------------

@pytest.mark.parametrize("title,commits", [
    ("a 0.2.1: release", ["a: tweak the toast"]),
    ("Bump version", ["bump a to 0.2.1"]),
    ("a: update docs and bump", ["update docs", "bump"]),
])
def test_patch_bump_alone_is_not_a_fix(title, commits):
    u = unit(title, commits, BUMP)
    evidence.judge(u)
    assert not u.is_fix and "patch version bump" not in u.why
    assert u.version_bumps == BUMP            # still recorded as a fact


def test_real_fix_evidence_still_counts_with_a_bump():
    u = unit("a 0.2.1: fix the first item", ["a: total skips the first item"], BUMP)
    evidence.judge(u)
    assert u.is_fix and u.why[0].startswith("title:")
    u = unit("a 0.2.1: release", ["fix: crash on empty list", "fix: wrong total", "bump a to 0.2.1"], BUMP)
    evidence.judge(u)
    assert u.is_fix and "commits say fix" in u.why[0]


