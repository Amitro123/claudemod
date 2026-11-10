"""The outside-in sweep: checklist, sweeper mode, three sweepers in the parallel recipe."""
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
HEADINGS = (
    "## 1. Trust boundaries",
    "## 2. Injection into session or agent context",
    "## 3. Secrets and personal data in logs, memory and commits",
    "## 4. Enforcement versus text",
    "## 5. Command construction",
    "## 6. Destructive writes",
    "## 7. Loss paths",
    "## 8. Packaging and install",
)


def _t(f: str) -> str:
    return " ".join((PLUGIN / f).read_text(encoding="utf-8").split())


def test_outside_in_checklist_has_eight_headings() -> None:
    raw = (PLUGIN / "skills/inspect/references/outside-in.md").read_text(encoding="utf-8")
    lines = raw.splitlines()
    for h in HEADINGS:
        assert h in lines, h
    assert sum(1 for x in lines if x.startswith("## ")) == 8
    assert "security_actor" in raw and "references/labels.md" in raw


def test_sweeper_documents_outside_in_mode() -> None:
    s = _t("agents/sweeper.md")
    assert "## Outside-in mode" in s and "OUTSIDE-IN" in s and "references/outside-in.md" in s
    assert "At most 25 tool calls" in s and "sweep-<k>.json" in s
    assert not (PLUGIN / "agents/sweeper-outside-in.md").exists()


def test_parallel_recipe_runs_three_sweepers() -> None:
    p = _t("skills/inspect/references/parallel.md")
    assert "three sweepers" in p and "OUTSIDE-IN" in p and "outside-in.md" in p
    assert len((PLUGIN / "skills/inspect/references/parallel.md").read_text(encoding="utf-8").splitlines()) <= 50


def test_outside_in_leads_are_kept_and_name_the_violated_rule() -> None:
    s = _t("agents/sweeper.md")
    assert "In normal mode a finding that breaks neither" in s
    assert "In OUTSIDE-IN mode such a lead is kept" in s
    assert "`breaks` names the rule, boundary or expectation violated" in s
    assert "in OUTSIDE-IN mode the rule, boundary or expectation that is violated" in s
