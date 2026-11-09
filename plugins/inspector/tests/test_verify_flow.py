"""The verify flow's files exist, are pointed to, and the agents have valid frontmatter."""
from __future__ import annotations

from pathlib import Path

PLUGIN = Path(__file__).parent.parent


def frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", path
    end = lines.index("---", 1)
    out = {}
    for ln in lines[1:end]:
        k, _, v = ln.partition(":")
        out[k.strip()] = v.strip()
    return out


def test_new_files_exist_and_reference_is_short() -> None:
    for f in ["agents/verifier.md", "agents/docs-checker.md",
              "skills/inspect/scripts/merge_verdicts.py", "skills/inspect/references/verify.md"]:
        assert (PLUGIN / f).is_file(), f
    assert len((PLUGIN / "skills/inspect/references/verify.md").read_text(encoding="utf-8").splitlines()) <= 45


def test_skill_md_points_to_verify() -> None:
    assert "references/verify.md" in (PLUGIN / "skills/inspect/SKILL.md").read_text(encoding="utf-8")


def test_agents_have_valid_frontmatter() -> None:
    for name, tools in [("verifier", "Read, Grep, Glob, Bash, Write"), ("docs-checker", "WebFetch, Read")]:
        fm = frontmatter(PLUGIN / "agents" / f"{name}.md")
        assert fm["name"] == name and fm["description"] and fm["tools"] == tools, name
