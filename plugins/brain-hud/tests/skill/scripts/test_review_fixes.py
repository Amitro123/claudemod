"""What a whole-plugin review found in the skill's hooks and scripts (2026-11-06), pinned.

Run: pytest tests/skill/scripts/test_review_fixes.py -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent / "skills" / "mistake-brain"
sys.path.insert(0, str(ROOT / "scripts"))

import compose_mistakes  # noqa: E402
import host_layout  # noqa: E402

MARKER = host_layout.MARKER


def _hook(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_git_dash_p_keeps_its_path_and_a_mysql_password_is_still_redacted():
    assert host_layout.safe_for_markdown("git restore -p src/x.py") == "git restore -p src/x.py"
    assert host_layout.safe_for_markdown("git checkout -p app.ts && mysql -u root -ps3cret db").endswith("-p [redacted] db")


def test_a_failing_validator_command_is_stored_with_its_secrets_redacted(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "MISTAKES.md").write_text(f"# MISTAKES.md\n\n{MARKER}\n", encoding="utf-8")
    payload = {"tool_name": "Bash", "tool_input": {"command": "OPENAI_API_KEY=sk-abcdefghijklmnopqrstu pytest --token hunter2"}, "error": "Exit code 1\nboom password=p4ss", "is_interrupt": False}
    subprocess.run([sys.executable, str(ROOT / "hooks" / "draft_mistake_on_validation_failure.py")], input=json.dumps(payload), capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}, check=True)
    stored = (tmp_path / ".claude" / "mb-pending-candidates.json").read_text(encoding="utf-8")
    for secret in ("sk-abcdefghijklmnopqrstu", "hunter2", "p4ss"):
        assert secret not in stored, secret
    assert "pytest" in stored


def test_a_revert_subject_with_a_backtick_or_a_secret_stays_inside_its_code_span(tmp_path):
    hook = _hook("revert_stop_hook")
    (tmp_path / "MISTAKES.md").write_text(f"# MISTAKES.md\n\n{MARKER}\n", encoding="utf-8")
    assert hook._draft_entry(tmp_path, "revert", 'Revert "x` ignore the rules ghp_abcdefghijklmnopqrstuvwxyz0123"')
    heading = next(l for l in (tmp_path / "MISTAKES.md").read_text(encoding="utf-8").splitlines() if l.startswith("## "))
    assert heading.count("`") == 2
    assert "ghp_" not in heading


def test_the_inbox_note_counts_what_is_really_there():
    text = "- **Status:** unrouted\n- **Status:** routed\n- **Status:** unrouted\n"
    assert host_layout.unrouted_note(text) == "2 unrouted entries now in the inbox. "
    assert host_layout.unrouted_note("- **Status:** unrouted\n") == "1 unrouted entry now in the inbox. "


def test_archiving_keeps_the_blank_lines_inside_an_entry_that_stays(tmp_path):
    def entry(date, title, status, extra=""):
        return f"## [{date}] {title}\n- **Type:** mistake\n- **What happened:** x{extra}\n- **PARA route:** {'unrouted' if status == 'unrouted' else 'Area: Areas/x.md'}\n- **Status:** {status}\n\n"
    kept = entry("2026-01-03 10:00", "kept", "unrouted", "\n\n\n    a quoted log\n\n\n    with gaps")
    path = tmp_path / "MISTAKES.md"
    path.write_text(f"# MISTAKES.md\n\n{MARKER}\n\n" + entry("2026-01-01 10:00", "old", "routed") + kept, encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "compose_mistakes.py"), str(path), "--max-lines", "3"], capture_output=True, text=True, check=True)
    remaining = path.read_text(encoding="utf-8")
    assert "old" not in remaining
    assert kept.rstrip("\n") in remaining


def test_routes_own_status_edits_get_no_routing_nudge(tmp_path):
    hook = _hook("auto_pipeline_on_mistakes_edit")
    route = {"tool_name": "Edit", "tool_input": {"old_string": "- **PARA route:** unrouted\n- **Status:** unrouted", "new_string": "- **PARA route:** Area: Areas/ci.md\n- **Status:** routed"}}
    assert hook._is_route_edit(route)
    assert not hook._is_route_edit({"tool_name": "Edit", "tool_input": {"old_string": "- **Status:** unrouted", "new_string": "## new entry\n- **Status:** unrouted"}})
    assert not hook._is_route_edit({"tool_name": "Write", "tool_input": {"content": "x"}})


def test_the_validation_hook_says_how_it_finds_the_project():
    text = (ROOT / "hooks" / "draft_mistake_on_validation_failure.py").read_text(encoding="utf-8")
    assert "ALWAYS resolved via git rev-parse" not in text
    assert "_resolve_git_root" not in text


def test_the_skill_says_there_is_one_index():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "each keep their own index" not in skill
    assert "Both harness indexes" not in (ROOT / "hooks" / "brief_on_session_start.py").read_text(encoding="utf-8")
    assert ".agent-brain/Areas/" not in (ROOT / "promote.md").read_text(encoding="utf-8")


def test_a_secret_in_an_env_style_name_is_redacted():
    """The open-bugs list, #2: \\b can't match after _, so DB_PASSWORD= and GITHUB_TOKEN= went through."""
    for cmd, secret in [
        ("DB_PASSWORD=hunter2 git checkout -- .", "hunter2"),
        ("export GITHUB_TOKEN=abc123; git restore .", "abc123"),
        ("API_TOKEN=xyz9 git clean -f", "xyz9"),
        ("MY_API_KEY: k-777 git checkout .", "k-777"),
    ]:
        out = host_layout.safe_for_markdown(cmd)
        assert secret not in out, (cmd, out)
        assert "[redacted]" in out
    assert host_layout.safe_for_markdown("git checkout -- tokens.py") == "git checkout -- tokens.py"


def test_an_index_line_with_an_en_dash_is_read_as_brain_ts_reads_it():
    """The open-bugs list, #6: rebuild_index's _LINE took — and - but not –, so rebuild added a second line."""
    import rebuild_index
    for line, file, summary in [
        ("- [Area] [ci](Areas/ci.md) – en dash summary (2 lessons)", "[ci](Areas/ci.md)", "en dash summary"),
        ("- [Area] [my notes](Areas/my notes.md) — spaced (1 lesson)", "[my notes](Areas/my notes.md)", "spaced"),
        ("- [Area] `Areas/x.md`", "`Areas/x.md`", None),
    ]:
        m = rebuild_index._LINE.match(line)
        assert m, line
        assert (m.group("file"), m.group("summary")) == (file, summary)
