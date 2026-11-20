"""Every subprocess call that decodes text names its encoding.

Without `encoding=`, Python decodes a process's output in the locale's encoding: UTF-8 on Linux and macOS, cp1252 on
a default Windows. git prints commit messages, paths and diffs in UTF-8, so on Windows a Hebrew subject or file name
came back garbled. Found by the pytest-windows job (test_batched_git); this test holds the whole kind, in the
plugins' scripts and in the tests themselves.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOTS = [Path(__file__).resolve().parents[2] / p for p in ("inspector", "retro")]
FILES = sorted(f for r in ROOTS for f in r.rglob("*.py") if "__pycache__" not in f.parts)


def text_calls_without_encoding(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        decodes = any(isinstance(kw.get(k), ast.Constant) and kw[k].value is True for k in ("text", "universal_newlines"))
        if decodes and "encoding" not in kw:
            bad.append(node.lineno)
    return bad


def test_the_files_are_found():
    assert len(FILES) > 50 and any(f.name == "evidence.py" for f in FILES)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOTS[0].parent)))
def test_no_text_subprocess_call_without_an_encoding(path):
    assert text_calls_without_encoding(path) == [], f"{path.name}: text=True with no encoding= at lines {text_calls_without_encoding(path)}"
