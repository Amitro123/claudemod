"""Design changes: terms a unit that is not a fix removed from docs while other files still use them.

The case that missed it: a refactor moved a skill from a 4-tier table to 3 levels, a template kept saying "4-tier",
and "copies left behind" (lines deleted by FIX units only) had nothing to say. Synthetic repositories only.

Run: python -m pytest plugins/inspector/tests/test_design_changes.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402
from synth import commit, merge_pr, new_repo  # noqa: E402

OLD = "# Router\nA 4-tier system.\nUse Tier 4 for lookups.\n"
NEW = "# Router\nThree levels.\nUse the light level for lookups.\n"
TEMPLATE = "# Global\nOur 4-tier system.\nRoute cheap work to Tier 4.\n"


def refactor(r: Path, template: str | None = TEMPLATE, extra: dict | None = None) -> None:
    commit(r, {"README.md": "# demo\n", "skills/router/SKILL.md": OLD,
               **({"templates/global.CLAUDE.md": template} if template else {}), **(extra or {})}, "Add router")
    merge_pr(r, 1, "levels", [({"skills/router/SKILL.md": NEW}, "Move the router to three levels")],
             "Refactor the router to three levels")


def design(r: Path) -> list[dict]:
    return evidence.investigate(str(r)).get("design_changes", [])


def test_a_refactor_that_removed_4_tier_while_a_template_keeps_it_is_reported(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    refactor(r)
    ev = evidence.investigate(str(r))
    assert ev["fixes"] == 0 and ev["left_behind"] == []          # the old section has nothing to say
    got = {e["term"]: e for e in ev["design_changes"]}
    e = got["4-tier"]
    assert e["unit"] == "#1" and e["removed"] == 1 and e["files_using"] == 1
    assert e["at"] == ["templates/global.CLAUDE.md:2"] and e["removed_from"] == ["skills/router/SKILL.md"]
    assert e["why"] == "removed 1 time by that unit, still used in 1 file"
    assert got["tier 4"]["at"] == ["templates/global.CLAUDE.md:3"]


def test_the_section_is_in_the_markdown_and_in_the_json(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    refactor(r)
    md, js = tmp_path / "e.md", tmp_path / "e.json"
    assert evidence.main(["--repo", str(r), "--md", str(md), "--json", str(js), "--no-github"]) == 0
    text = md.read_text(encoding="utf-8")
    assert "## Design changes: terms a unit removed that other files still use" in text
    assert "- #1 `4-tier`: removed 1 time by that unit, still used in 1 file; at templates/global.CLAUDE.md:2" in text
    assert any(x["term"] == "4-tier" for x in json.loads(js.read_text(encoding="utf-8"))["design_changes"])


def test_no_entry_and_no_section_when_every_use_was_removed(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"README.md": "# demo\n", "skills/router/SKILL.md": OLD, "templates/global.CLAUDE.md": TEMPLATE}, "Add router")
    merge_pr(r, 1, "levels", [({"skills/router/SKILL.md": NEW, "templates/global.CLAUDE.md": "# Global\nThree levels.\n"},
                               "Move everything to three levels")], "Refactor to three levels")
    assert "design_changes" not in evidence.investigate(str(r))
    md = tmp_path / "e.md"
    assert evidence.main(["--repo", str(r), "--md", str(md), "--json", str(tmp_path / "e.json"), "--no-github"]) == 0
    assert "Design changes" not in md.read_text(encoding="utf-8")


def test_a_changelog_or_history_file_is_not_a_still_user(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    refactor(r, template=None, extra={"CHANGELOG.md": "## 1.0\n- A 4-tier system, Tier 4 for lookups.\n",
                                      "docs/decisions/001.md": "We chose a 4-tier system.\n",
                                      "docs/tuning-log.md": "4-tier tried.\n"})
    assert design(r) == []


def test_a_term_still_in_a_file_the_unit_changed_is_not_reported(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"README.md": "# demo\n", "skills/router/SKILL.md": OLD, "templates/global.CLAUDE.md": TEMPLATE}, "Add router")
    merge_pr(r, 1, "levels", [({"skills/router/SKILL.md": NEW + "Formerly a 4-tier system, Tier 4.\n"}, "Reword the router")],
             "Reword the router")
    assert design(r) == []


def test_a_fix_unit_is_left_to_copies_left_behind(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"README.md": "# demo\n", "skills/router/SKILL.md": OLD, "templates/global.CLAUDE.md": TEMPLATE}, "Add router")
    merge_pr(r, 1, "fixlevels", [({"skills/router/SKILL.md": NEW}, "fix: the router doc says 4-tier no more")],
             "fix: the router doc says 4-tier no more")
    ev = evidence.investigate(str(r))
    assert ev["fixes"] == 1 and "design_changes" not in ev


def test_a_numbered_term_needs_one_removal_a_word_or_hyphenated_word_two_files(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    commit(r, {"README.md": "# demo\n", "skills/a/SKILL.md": "# A\norchestrator once.\nsingle-owner too.\nPhase 9 ends.\n",
               "skills/b/SKILL.md": "# B\norchestrator again.\n",
               "templates/t.md": "orchestrator, single-owner and Phase 9 live here.\n",
               "templates/u.md": "an orchestrator note.\n"}, "Add skills")
    merge_pr(r, 1, "rename", [({"skills/a/SKILL.md": "# A\nnothing.\n", "skills/b/SKILL.md": "# B\nnothing.\n"},
                               "Rename the concepts")], "Rename the concepts")
    got = {e["term"]: e for e in design(r)}
    assert set(got) == {"orchestrator", "phase 9"}      # single-owner left one file only
    assert got["orchestrator"]["removed"] == 2
    assert got["orchestrator"]["removed_from"] == ["skills/a/SKILL.md", "skills/b/SKILL.md"]


def test_the_section_is_capped_at_15_ranked_by_removed_count_then_rarity(tmp_path: Path) -> None:
    r = new_repo(tmp_path / "r")
    old = "\n".join(f"use legacy-mode-{i:02d} here" for i in range(20)) + "\n" + "legacy-mode-07 again\n" * 2
    commit(r, {"README.md": "# demo\n", "skills/a/SKILL.md": old,
               "templates/t.md": "\n".join(f"legacy-mode-{i:02d}" for i in range(20)) + "\n",
               "templates/u.md": "legacy-mode-00\n"}, "Add skill")
    merge_pr(r, 1, "drop", [({"skills/a/SKILL.md": "# A\nnothing\n"}, "Drop the legacy modes")], "Drop the legacy modes")
    ev = evidence.investigate(str(r))
    got = ev["design_changes"]
    assert len(got) == 15 and ev["design_changes_omitted"] == 5
    assert got[0]["term"] == "legacy-mode-07" and got[0]["removed"] == 3        # most removed first
    assert got[1]["term"] == "legacy-mode-01"                                 # then fewest files using (00 is in 2), then name
    assert [e["files_using"] for e in got[1:]] == sorted(e["files_using"] for e in got[1:])
    md = tmp_path / "e.md"
    assert evidence.main(["--repo", str(r), "--md", str(md), "--json", str(tmp_path / "e.json"), "--no-github"]) == 0
    assert "and 5 more" in md.read_text(encoding="utf-8")


def test_terms_are_words_hyphenated_and_numbered_without_stop_words() -> None:
    got = evidence.design_terms("A 4-tier system, see https://x.io/a-b-c for Tier 4 and the 3 levels (2026-11-06).")
    assert got[:2] == ["4-tier", "tier 4"] and "system" in got and "levels" in got
    assert "the 3" not in got and "2026-11-06" not in got and "see" not in got and "for" not in got
