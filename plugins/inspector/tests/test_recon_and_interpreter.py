"""Two things a review of 0.8.1 on Windows asked for (2026-11-18): `--recon`, a scoped look at a seam before changing it
that does not start the full investigation, and a `python` that is not the Microsoft Store stub in the commands the
collector and the plan print. No network, no agents."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

import evidence  # noqa: E402
import plan as plan_mod  # noqa: E402
import synth  # noqa: E402
from test_plan import make_run, SHA, PLAN  # noqa: E402
import subprocess  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = (PLUGIN / "skills" / "inspect" / "SKILL.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def big(tmp_path_factory) -> Path:
    return synth.build_big(tmp_path_factory.mktemp("recon") / "repo", 20)       # about 14 fix units


def collect(repo: Path, out: Path, *flags: str, capsys) -> tuple[str, dict]:
    assert evidence.main(["--repo", str(repo), "--out", str(out), "--min-lines", "1", "--no-github", *flags]) == 0
    text = capsys.readouterr().out
    return text, json.loads((out / "evidence.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- recon
def test_a_recon_run_prints_no_plan_writes_no_plan_and_ends_with_saved(big, tmp_path, capsys) -> None:
    out, ev = collect(big, tmp_path / "o", "--recon", capsys=capsys)
    assert "RUN PLAN: " not in out and "RUN PLAN (inline" not in out and not (tmp_path / "o" / "plan").exists()
    assert "RECON: no case file, no agents, no RUN PLAN." in out and "run again without --recon" in out
    assert "Cases to work, in order" in out and list((tmp_path / "o" / "cases").glob("*.md"))
    assert out.rstrip().splitlines()[-1].startswith("Saved: ")


def test_the_recon_budget_is_5_unless_the_budget_is_given(big, tmp_path, capsys) -> None:
    _, plain = collect(big, tmp_path / "a", capsys=capsys)
    _, recon = collect(big, tmp_path / "b", "--recon", capsys=capsys)
    _, two = collect(big, tmp_path / "c", "--recon", "--budget", "2", capsys=capsys)
    _, nine = collect(big, tmp_path / "d", "--recon", "--budget", "9", capsys=capsys)
    assert len(plain["cases"]) > 5 and len(recon["cases"]) == 5 and len(two["cases"]) == 2 and len(nine["cases"]) == 9


def test_a_run_without_recon_still_prints_its_plan(big, tmp_path, capsys) -> None:
    out, _ = collect(big, tmp_path / "o", capsys=capsys)
    assert "RUN PLAN: " in out and "RECON" not in out and (tmp_path / "o" / "plan" / "plan.md").is_file()


def test_recon_on_a_path_nothing_touches_says_so(big, tmp_path, capsys) -> None:
    out, ev = collect(big, tmp_path / "o", "--recon", "--path", "no/such/folder", capsys=capsys)
    assert ev["cases"] == [] and "nothing to read first" in out and out.rstrip().splitlines()[-1].startswith("Saved: ")


def test_skill_md_names_recon_and_premerge_and_when_to_use_reaches_a_seam() -> None:
    head = SKILL.split("---", 2)[1]
    assert "about to change a multi-component or high-churn seam" in head
    assert "`--recon --path <path>`" in SKILL and "scripts/premerge.py" in SKILL
    assert "on Windows write `python` for `python3`" in SKILL


# ---------------------------------------------------------------- the interpreter
def test_python_cmd_is_python3_on_posix_python_on_windows_and_can_be_named(monkeypatch) -> None:
    monkeypatch.delenv("INSPECTOR_PYTHON", raising=False)
    assert plan_mod.python_cmd(windows=False) == "python3" and plan_mod.python_cmd(windows=True) == "python"
    monkeypatch.setenv("INSPECTOR_PYTHON", "py -3")
    assert plan_mod.python_cmd(windows=False) == "py -3" and plan_mod.python_cmd(windows=True) == "py -3"
    monkeypatch.setenv("INSPECTOR_PYTHON", "  ")
    assert plan_mod.python_cmd(windows=False) == "python3"


@pytest.mark.parametrize("value", ["python; echo x", "python && id", "$(id)", "`id`", "python | tee f", "py (3)", "python > f", 'python "unclosed',
                                   "python\nid"])
def test_an_interpreter_that_holds_shell_syntax_or_broken_quotes_is_ignored(monkeypatch, value) -> None:
    monkeypatch.setenv("INSPECTOR_PYTHON", value)
    assert plan_mod.python_cmd(windows=False) == "python3" and plan_mod.python_cmd(windows=True) == "python"


@pytest.mark.parametrize("value", ["py -3", '"C:/Program Files/Python312/python.exe"', "C:/Python312/python.exe", "python3.12"])
def test_plain_interpreters_and_quoted_paths_with_spaces_are_kept(monkeypatch, value) -> None:
    monkeypatch.setenv("INSPECTOR_PYTHON", value)
    assert plan_mod.python_cmd(windows=False) == value


def test_the_plans_commands_use_the_interpreter(tmp_path, monkeypatch) -> None:
    run = make_run(tmp_path, 7)
    env = {**__import__("os").environ, "INSPECTOR_PYTHON": "pyx"}
    assert subprocess.run([sys.executable, str(PLAN), "--run", str(run)], env=env, capture_output=True).returncode == 0
    md = (run / "plan" / "plan.md").read_text(encoding="utf-8")
    cmds = [ln for ln in md.splitlines() if ".py" in ln and "scripts/" in ln and ln[:3].strip().rstrip(".").isdigit()]
    assert cmds and all(ln.split(". ", 1)[1].startswith('pyx "') for ln in cmds) and "python3" not in md


def test_the_collectors_dossier_commands_use_the_interpreter(big, tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("INSPECTOR_PYTHON", "pyx")
    out, _ = collect(big, tmp_path / "o", capsys=capsys)
    assert "(or `pyx " in out and "(or `python3 " not in out


def test_a_multiword_interpreter_is_split_not_quoted(big, tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("INSPECTOR_PYTHON", "py -3")
    out, _ = collect(big, tmp_path / "o", capsys=capsys)
    assert "(or `py -3 " in out and "'py -3'" not in out
