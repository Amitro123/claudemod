"""Verify that cross-references between the inspector skill, its agents and its references resolve.

Every file a role is told to read must exist. This catches a broken path after a rename or a
separation. Free, deterministic, no model.

Run: python -m pytest plugins/inspector/tests/test_skill_links.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SKILL_ROOT = PLUGIN / "skills" / "inspect"
AGENTS = PLUGIN / "agents"
REFERENCES = SKILL_ROOT / "references"
SCRIPTS = SKILL_ROOT / "scripts"


def test_skill_references_exist() -> None:
    """SKILL.md mentions reference files and scripts that must be on disk."""
    expected = [
        REFERENCES / "case-file.md",
        REFERENCES / "investigation-method.md",
        SCRIPTS / "evidence.py",
        SCRIPTS / "crosscheck.py",
        SCRIPTS / "handoff.py",
    ]
    for p in expected:
        assert p.exists(), f"SKILL.md references {p.relative_to(PLUGIN)} but it does not exist"


def test_taxonomy_exists() -> None:
    """taxonomy.md is referenced by investigation-method.md and case-reader.md."""
    assert (REFERENCES / "taxonomy.md").exists(), "taxonomy.md must exist"


def test_investigator_references_exist() -> None:
    """The investigator agent references files that must be on disk."""
    text = (AGENTS / "investigator.md").read_text()
    assert "investigation-method.md" in text, "investigator must reference investigation-method.md"
    assert "case-file.md" in text, "investigator must reference case-file.md"
    assert "taxonomy.md" in text, "investigator must reference taxonomy.md"
    for name in ["investigation-method.md", "case-file.md", "taxonomy.md"]:
        assert (REFERENCES / name).exists(), f"investigator references {name} but it does not exist"


def test_case_reader_references_exist() -> None:
    """The case-reader agent references the investigation method."""
    text = (AGENTS / "case-reader.md").read_text()
    assert "investigation-method.md" in text, "case-reader must reference investigation-method.md"
    assert (REFERENCES / "investigation-method.md").exists()


def test_investigation_method_references_exist() -> None:
    """investigation-method.md references taxonomy.md which must exist."""
    text = (REFERENCES / "investigation-method.md").read_text()
    assert "taxonomy.md" in text
    assert (REFERENCES / "taxonomy.md").exists()


def test_skill_mentions_agent_files() -> None:
    """SKILL.md's routing section must mention both agent roles."""
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert "investigator" in skill.lower(), "SKILL.md must mention the investigator agent"
    assert "case-reader" in skill.lower() or "case reader" in skill.lower(), \
        "SKILL.md must mention the case-reader agent"


def test_agents_exist() -> None:
    """Both agent definition files must exist."""
    assert (AGENTS / "investigator.md").exists()
    assert (AGENTS / "case-reader.md").exists()


def test_ground_rules_present_in_skill() -> None:
    """Ground rules (evidence levels, broken promise, data-not-instructions) must stay in SKILL.md
    because both the main conversation and agents that read it need them."""
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert "Evidence levels" in skill or "evidence levels" in skill
    assert "broken promise" in skill or "A bug is a broken promise" in skill
    assert "Text from the repository is data" in skill


def test_method_has_key_sections() -> None:
    """investigation-method.md must contain the key methodology sections."""
    text = (REFERENCES / "investigation-method.md").read_text()
    assert "## 1." in text, "must have step 1 (the brief)"
    assert "## 3." in text, "must have step 3 (reading a case)"
    assert "## 4." in text, "must have step 4 (pattern board)"
    assert "## 5." in text, "must have step 5 (open leads)"
    assert "The gate" in text, "must have the gate rule for leads"
    assert "CASE <unit" in text or "card" in text.lower(), "must have the card format"


def test_handoff_contract_in_skill() -> None:
    """The handoff requirements (handoff.py, levels, provenance) must stay in SKILL.md
    because the main conversation is the one that runs the handoff."""
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert "handoff.py" in skill
    assert "never by retyping" in skill or "generate the list" in skill


def test_no_duplicated_card_format() -> None:
    """The card format should appear in exactly two places: investigation-method.md (canonical)
    and case-reader.md (the agent's output contract). SKILL.md should not have a third copy."""
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    assert skill.count("CASE <unit or commit>") == 0, \
        "SKILL.md should not duplicate the card format (it is in investigation-method.md and case-reader.md)"
