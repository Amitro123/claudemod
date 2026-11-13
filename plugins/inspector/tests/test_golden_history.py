"""Golden test: the collector against this repository's own history, whose answers are known.

The labels come from the 2026-11-06 investigation (plugins/inspector/docs/2026-11-06-review.md),
where each one was checked by reading the diffs. Free and deterministic: no model.

- Fix verdicts: 16 units that fixed bugs, 20 that didn't (features, docs, a license, a rename).
- Culprits: fix commits whose broken lines blame can trace, and the unit that wrote them.

Needs the full history up to #72: skipped in a shallow clone or a checkout without it.
Run: python -m pytest plugins/inspector/tests -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

import evidence  # noqa: E402
from golden_labels import BUMP_ONLY_FIXES, FIXES, NOT_FIXES, PR72  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

# fix commit -> the unit that wrote the lines it changed (read from both diffs)
CULPRITS = {
    "eb790a7": "#48",  # re-plan and concurrent adds mixed in a merge: #48's mergeGoal
    "86fc34b": "#48",  # export `where` outside its code span: #48 quoted CLAUDE.md items only
    "d9970cc": "#51",  # exit 127 of a started check read as "not installed": #51
    "c917a09": "#48",  # every export quotes: #48 quoted one target
}
# commits of the bump-only units above: no longer worked, so no blame (idle SVG redraw -> #23; plan approval -> #55)
BUMP_ONLY_COMMITS = {"e5c6966", "748d209"}
NO_CULPRIT = {"a883bcd"}  # adds a redaction pattern, deletes nothing: blame has nothing to trace


def _has_history() -> bool:
    if not (ROOT / ".git").exists():
        return False
    shallow = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],
                             capture_output=True, text=True).stdout.strip()
    known = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{PR72}^{{commit}}"]).returncode == 0
    return shallow == "false" and known


pytestmark = [pytest.mark.skipif(not _has_history(), reason="needs the full claudemod history up to #72"),
              pytest.mark.slow]       # one collector run over ~100 units; deselect with -m "not slow"


@pytest.fixture(scope="module")
def ev(tmp_path_factory) -> dict:
    # one run shared by every test here; the blame cache goes to a temp folder, not into this checkout's .git
    return evidence.investigate(str(ROOT), ref=PR72, min_lines=3,
                                cache_dir=str(tmp_path_factory.mktemp("blame-cache")))


def test_fix_verdicts(ev: dict) -> None:
    by = {u["unit"]: u for u in ev["timeline"]}
    missed = [u for u in FIXES if not by[u]["is_fix"]]
    flagged = [u for u in NOT_FIXES if by[u]["is_fix"]]
    bump_only = [u for u in BUMP_ONLY_FIXES if by[u]["is_fix"]]
    assert not missed and not flagged, f"fixes missed: {missed}; non-fixes flagged: {flagged}"
    assert not bump_only, f"a patch bump alone made these fixes: {bump_only}"


def test_fix_share_stays_honest(ev: dict) -> None:
    # 0.1.0 called 51 of 76 units fixes. The real share, read by hand, is about a third.
    assert ev["fixes"] / ev["units"] < 0.45


def test_culprits(ev: dict) -> None:
    commits = {c["sha"][:7]: c for u in ev["timeline"] for c in u["commits"]}
    got = {s: [e["unit"] for e in commits[s].get("introduced_by", [])] for s in CULPRITS}
    wrong = {s: g for s, g in got.items() if CULPRITS[s] not in g}
    assert not wrong, f"culprit not traced: {wrong}"
    for s in NO_CULPRIT | BUMP_ONLY_COMMITS:
        assert not commits[s].get("introduced_by"), s
