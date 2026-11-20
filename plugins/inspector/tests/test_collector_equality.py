"""Equality guard for the collector: its normalized output on a small synthetic repository must equal
a golden snapshot generated from the code BEFORE the 2026-11 performance work.

Any speed-up (batched git calls, caches, threads, pruning) has to leave these results byte-identical.
Regenerate deliberately, and only for an intended change of results:
    UPDATE_GOLDEN=1 python -m pytest plugins/inspector/tests/test_collector_equality.py -q

Run: python -m pytest plugins/inspector/tests/test_collector_equality.py -q
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402
import normalize  # noqa: E402
import synth  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "small_evidence.json"
HEX = re.compile(r"\b(?:[0-9a-f]{40}|[0-9a-f]{12}|[0-9a-f]{8})\b")

# name -> collector arguments (after --repo/--out). Scopes the optimizations must all preserve.
RUNS = {
    "default": ["--min-lines", "1"],
    "path": ["--min-lines", "1", "--path", "plugins/b"],
    "unit": ["--min-lines", "1", "--unit", "#5"],
    "since": ["--min-lines", "1", "--max", "6"],
}


# Same question as RUNS["default"], asked with other execution settings: the answer must not move.
SAME_AS_DEFAULT = {
    "serial": ["--min-lines", "1", "--workers", "1", "--no-cache"],
    "threads": ["--min-lines", "1", "--workers", "8", "--no-cache"],
}


def _tokenize(text: str, seen: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        return seen.setdefault(m.group(0)[:8], f"<SHA{len(seen)}>")
    return HEX.sub(sub, text)


def snapshot(repo: Path, out: Path, args: list[str]) -> dict:
    assert evidence.main(["--repo", str(repo), "--out", str(out), "--no-github", *args]) == 0   # offline: never gh
    seen: dict[str, str] = {}
    r = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    nj = normalize.normalize_json(r, [str(out)])
    md = normalize.normalize_md((out / "evidence.md").read_text(encoding="utf-8"),
                                [str(out), r["repo_path"], str(repo)])
    cases = {p.name: normalize.normalize_md(p.read_text(encoding="utf-8"), [str(out), r["repo_path"], str(repo)])
             for p in sorted((out / "cases").glob("*.md"))} if (out / "cases").exists() else {}
    return {"json": json.loads(_tokenize(json.dumps(nj, ensure_ascii=False), seen)),
            "md": _tokenize(md, seen),
            "cases": {k: _tokenize(v, seen) for k, v in cases.items()}}


@pytest.fixture(scope="module")
def small_repo(tmp_path_factory) -> Path:
    return synth.build_small(tmp_path_factory.mktemp("eq") / "repo")


@pytest.fixture(scope="module")
def results(small_repo: Path, tmp_path_factory) -> dict:
    return {name: snapshot(small_repo, tmp_path_factory.mktemp(f"out-{name}") / "o", args)
            for name, args in RUNS.items()}


def test_results_equal_the_golden_snapshot(results: dict) -> None:
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden regenerated")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for name in RUNS:
        assert results[name]["json"] == golden[name]["json"], f"{name}: evidence.json differs"
        assert results[name]["md"] == golden[name]["md"], f"{name}: evidence.md differs"
        assert results[name]["cases"] == golden[name]["cases"], f"{name}: case dossiers differ"


def test_the_snapshot_is_not_vacuous(results: dict) -> None:
    j = results["default"]["json"]
    assert j["fixes"] >= 4 and j["fix_of_fix"], "the synthetic history must contain fixes and a fix-of-fix"
    assert j["left_behind"] and any(u["version_bumps"] for u in j["timeline"])
    assert any(c.get("introduced_by") for u in j["timeline"] for c in u["commits"])


@pytest.mark.parametrize("name", sorted(SAME_AS_DEFAULT))
def test_workers_and_cache_settings_do_not_change_results(small_repo: Path, tmp_path: Path, name: str) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["default"]
    got = snapshot(small_repo, tmp_path / "o", SAME_AS_DEFAULT[name])
    assert got == golden


def test_a_warm_blame_cache_gives_the_same_results(small_repo: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    args = ["--min-lines", "1", "--cache-dir", str(cache)]
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["default"]
    assert snapshot(small_repo, tmp_path / "cold", args) == golden
    assert any(cache.rglob("*.json")), "the cold run fills the cache"
    assert snapshot(small_repo, tmp_path / "warm", args) == golden


def test_the_default_cache_is_the_only_write_inside_git(small_repo: Path, tmp_path: Path) -> None:
    before = {p for p in (small_repo / ".git").rglob("*") if p.is_file()}
    assert evidence.main(["--repo", str(small_repo), "--out", str(tmp_path / "o"), "--no-github", "--min-lines", "1"]) == 0
    new = {p.relative_to(small_repo / ".git").parts[:2] for p in (small_repo / ".git").rglob("*") if p.is_file()} - \
          {p.relative_to(small_repo / ".git").parts[:2] for p in before}
    assert new <= {("inspector", "cache")}, new


def test_default_excludes_are_overridden_by_path_and_component_root() -> None:
    names = lambda ex: {e.split("**/")[1].split("/")[0] for e in ex if e.startswith(":(exclude,glob)")}
    assert names(evidence.effective_excludes()) == set(evidence.DEFAULT_EXCLUDES)
    assert "vendor" not in names(evidence.effective_excludes(path="vendor/lib"))
    assert "dist" not in names(evidence.effective_excludes(path="packages/x/dist"))
    assert "build" not in names(evidence.effective_excludes(component_roots=["build"]))
    assert evidence.effective_excludes(defaults=False) == []
    assert evidence.effective_excludes(extra=["gen"], defaults=False) == [":(exclude)gen"]
