"""The parallel recipe: pointer, size, agents and budgets."""
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]


def _t(f: str) -> str:
    return (PLUGIN / f).read_text(encoding="utf-8")


def test_skill_md_points_to_parallel_recipe() -> None:
    assert "references/parallel.md" in _t("skills/inspect/SKILL.md")


def test_parallel_recipe_is_short_and_names_every_part() -> None:
    t = _t("skills/inspect/references/parallel.md")
    assert len(t.splitlines()) <= 50
    for word in ("collector", "brief-writer", "case-reader", "sweeper", "crosscheck", "verifier"):
        assert word in t, word


def test_sweeper_frontmatter() -> None:
    t = _t("agents/sweeper.md")
    head = t.split("---")[1]
    for key in ("name: sweeper", "description:", "tools: Read, Grep, Glob, Bash", "model: sonnet"):
        assert key in head, key


def test_case_reader_has_25_call_rule() -> None:
    t = " ".join(_t("agents/case-reader.md").split())
    assert "At most 25 tool calls" in t and "call 20" in t and "Never end without a card" in t
