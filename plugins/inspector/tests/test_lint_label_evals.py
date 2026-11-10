"""The synthetic leads in evals/label-lint fire exactly the rules expected.json names."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import lint_leads as L  # noqa: E402

DIR = Path(__file__).parent.parent / "evals" / "label-lint"


def test_each_example_fires_exactly_its_rule() -> None:
    expected = json.loads((DIR / "expected.json").read_text(encoding="utf-8"))
    assert len(expected) == 9
    for name, rules in expected.items():
        fired = {r for lead in L.load(str(DIR / name)) for r, _, _ in L.lint(lead)}
        assert fired == set(rules), (name, fired)
