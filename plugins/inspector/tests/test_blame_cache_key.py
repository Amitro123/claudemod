"""The blame cache key changes with every input and with BLAME_CACHE_VERSION. Pure logic, no repository."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
import evidence  # noqa: E402

BASE = ("a" * 40, "src/x.py", [(1, 3), (8, 9)], "ign1")


def key(*args):
    return evidence._blame_key(*(args or BASE))


def test_same_inputs_same_key():
    assert key() == key("a" * 40, "src/x.py", [(1, 3), (8, 9)], "ign1")


def test_version_changes_the_key(monkeypatch):
    before = key()
    monkeypatch.setattr(evidence, "BLAME_CACHE_VERSION", evidence.BLAME_CACHE_VERSION + "-next")
    assert key() != before


def test_version_is_v2_or_later():
    assert evidence.BLAME_CACHE_VERSION != "v1"


def test_each_other_input_changes_the_key():
    parent, old, ranges, ign = BASE
    keys = {key(), key("b" * 40, old, ranges, ign), key(parent, "src/y.py", ranges, ign),
            key(parent, old, [(1, 3)], ign), key(parent, old, [(1, 3), (8, 10)], ign), key(parent, old, ranges, "ign2")}
    assert len(keys) == 6
