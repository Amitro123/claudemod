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


def test_sweeper_writes_its_own_file() -> None:
    s = " ".join(_t("agents/sweeper.md").split())
    assert "Write" in s.split("---")[1].split("tools:")[1].splitlines()[0]
    assert "sweep-<k>.json" in s and "never the array itself" in s
    p = " ".join(_t("skills/inspect/references/parallel.md").split())
    assert "Sweep file: <tmp>/sweep-<k>.json" in p and "save each reply" not in p
