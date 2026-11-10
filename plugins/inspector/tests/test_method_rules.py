"""Pin the method rules added 2026-11-10: one short phrase in the file that owns each rule."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
FILES = {
    "labels": ROOT / "skills" / "inspect" / "references" / "labels.md",
    "producers": ROOT / "skills" / "inspect" / "references" / "producers.md",
    "sweeper": ROOT / "agents" / "sweeper.md",
    "investigator": ROOT / "agents" / "investigator.md",
}
RULES = {
    "labels": [
        "parsed or run read-only",
        "never `text-pin` alone",
        "set `observed_in_production: yes`",
        "`1 of 8`",
    ],
    "producers": ["## 7. Where the job's logs live", "## 8. Deploy order and schema skew"],
    "sweeper": ["past `exp:`/expiry entries", "play the same role"],
    "investigator": ["degrade path lists that path's own failure modes"],
}


def _text(key: str) -> str:
    return FILES[key].read_text(encoding="utf-8")


def test_each_rule_is_in_its_owner() -> None:
    for key, phrases in RULES.items():
        for p in phrases:
            assert p in _text(key), (key, p)


def test_no_rule_is_duplicated_across_files() -> None:
    skill = (ROOT / "skills" / "inspect" / "SKILL.md").read_text(encoding="utf-8")
    for key, phrases in RULES.items():
        for p in phrases:
            for other in FILES:
                if other != key:
                    assert p not in _text(other), (p, other)
            assert p not in skill, (p, "SKILL.md")
            assert _text(key).count(p) == 1, (key, p)


def test_strict_json_rule_in_json_writing_agents() -> None:
    for name in ("case-reader", "sweeper", "investigator"):
        text = (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")
        assert "Strict JSON" in text and "written doubled" in text, name
