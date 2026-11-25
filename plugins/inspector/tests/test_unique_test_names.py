"""No two Python test files under plugins/ share a file name (retro R2, 2026-11-25).

The factory's detected check `python -m pytest -q plugins` failed at collection in all 7 reviews of that day:
`plugins/retro/tests/test_review_fixes.py` and `plugins/brain-hud/tests/skill/scripts/test_review_fixes.py`. pytest
imports test files without `__init__.py` by their base name, so the second one clashes with the first. CI runs each
plugin's folder separately and never hit it; a whole-repository run did, every time.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[2]


def test_no_two_test_files_share_a_name():
    seen: dict[str, list[str]] = defaultdict(list)
    for p in PLUGINS.rglob("test_*.py"):
        if "node_modules" not in p.parts and "__pycache__" not in p.parts:
            seen[p.name].append(p.relative_to(PLUGINS).as_posix())
    assert {n: ps for n, ps in seen.items() if len(ps) > 1} == {}
