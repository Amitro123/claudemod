"""distill routes each lesson: the recommendations file and its lint."""
from __future__ import annotations

from pathlib import Path

from test_retro import FAKE_TOKEN  # noqa: F401  (also puts the scripts on the path)
import lint_skill as L  # noqa: E402

GOOD = """# Recommendations

## R1: tests never ran before the PR
- Destination: check
- Observed: the builder opened the PR with a red suite (evidence: digest steps 14-15, `npm test` exit 1)
- Measured: 1 failed call, 0 test runs before the push
- Existing: package.json has `test`; .github/workflows/ci.yml runs only lint
- Change: add `npm test` to the CI job -> .github/workflows/ci.yml
- Why: a red suite then blocks the merge whatever the agent does (hypothesis)
- Verify: a branch with a failing test shows a red CI run

## R2: one odd timeout
- Destination: no-change
- Observed: the registry timed out once (evidence: call 31)
- Measured: 1 timeout in 1 run
- Existing: nothing retries it
- Change: none
- Why: one run, a cause of that day
- Verify: another run that times out the same way would make it a lesson
"""


def lint(tmp_path: Path, text: str):
    f = tmp_path / "recommendations.md"
    f.write_text(text, encoding="utf-8")
    return L.lint_recommendations(f)


def test_a_complete_routing_file_passes(tmp_path):
    assert lint(tmp_path, GOOD) == ([], [])
    assert L.main(["--recommendations", str(tmp_path / "recommendations.md")]) == 0


def test_every_field_and_a_known_destination_are_required(tmp_path):
    errors, _ = lint(tmp_path, GOOD.replace("- Verify: a branch with a failing test shows a red CI run\n", "").replace("Destination: no-change", "Destination: prompt"))
    assert "R1: no Verify" in errors
    assert any("R2: destination 'prompt' is not one of" in e for e in errors)


def test_evidence_a_target_and_none_for_no_change(tmp_path):
    text = (GOOD.replace("(evidence: digest steps 14-15, `npm test` exit 1)", "it seemed so")
                .replace("-> .github/workflows/ci.yml", "in CI")
                .replace("- Change: none", "- Change: add a retry -> npm config"))
    errors, _ = lint(tmp_path, text)
    assert "R1: Observed names no evidence (evidence: a step, a call, a file:line)" in errors
    assert "R1: Change names no target (`<what> -> <file or component>`)" in errors
    assert "R2: no-change has `Change: none`" in errors


def test_an_improvement_claim_needs_a_comparison(tmp_path):
    _, warnings = lint(tmp_path, GOOD.replace("1 failed call, 0 test runs before the push", "40% fewer calls"))
    assert warnings == ["R1: Measured claims a change with nothing to compare it with"]
    _, warnings = lint(tmp_path, GOOD.replace("1 failed call, 0 test runs before the push", "12 calls, fewer than 30 in run-log row 3"))
    assert warnings == []


def test_private_data_and_no_blocks_are_errors(tmp_path):
    errors, _ = lint(tmp_path, GOOD.replace("call 31", "call 31 by someone@corp.io"))
    assert any("email" in e for e in errors)
    assert lint(tmp_path, "# nothing here\n")[0] == ["recommendations.md: no `## R1: ...` block"]


def test_a_skill_folder_given_as_dot_is_named_by_its_real_folder(tmp_path, monkeypatch):
    d = tmp_path / "my-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: my-skill\ndescription: does a thing\n---\n\n1. step\n", encoding="utf-8")
    monkeypatch.chdir(d)
    assert not any("differs from the folder" in e for e in L.lint(Path("."))[0])


def test_distill_routes_before_it_drafts_and_names_the_template():
    root = Path(__file__).resolve().parents[1] / "skills" / "distill"
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert text.index("**Route each lesson**") < text.index("**Draft** the skill only for the lessons routed to *skill*")
    for d in L.DESTINATIONS:
        assert f"**{d}**" in text
    assert (root / "references" / "recommendations.md").is_file()
    assert L.lint(root) == ([], [])
