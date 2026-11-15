"""The collector asks git for several commits at once. Each batched answer must equal the one-commit
answer it replaced, and the number of git calls on a known history is held as a budget."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
import evidence  # noqa: E402
import synth  # noqa: E402

pytestmark = pytest.mark.slow


def body(i: int, v: int) -> str:
    return "".join(f"def f{i}_{j}(x):\n    return x + {v}\n\n" for j in range(30))


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    r = synth.build_small(tmp_path_factory.mktemp("batch") / "repo")
    synth.commit(r, {f"src/m{i}.py": body(i, 1) for i in range(9)} | {"vendor/lib.js": "a = 1\n"}, "Add modules")
    synth.merge_pr(r, 20, "big", [({f"src/m{i}.py": body(i, 2) for i in range(9)}, "fix: the first half of the 9 issues"),
                                  ({f"src/m{i}.py": body(i, 3) for i in range(9)} | {"vendor/lib.js": "a = 2\n"},
                                   "fix: the second half")], "fix: the 9 issues")
    return r


def pairs(repo: Path) -> list[tuple[str, str]]:
    out = synth.run(repo, "log", "--no-merges", "--format=%H %P")
    return [tuple(line.split()) for line in out.splitlines() if len(line.split()) == 2]


@pytest.mark.parametrize("excludes", [[], [":(exclude)vendor", ":(exclude)plugins/b"]])
def test_batched_diffs_equal_one_diff_per_commit(repo: Path, excludes) -> None:
    ps = pairs(repo)
    assert len(ps) > 10
    got = evidence.commit_diffs(str(repo), ps, excludes)
    for sha, parent in ps:
        assert got[sha] == evidence.commit_diff(str(repo), parent, sha, excludes), sha
    assert any("rename from" in d for d in got.values())          # the rename fix is in the set
    if excludes:
        assert "" in got.values()                                  # a commit with nothing outside the excludes


def test_a_refused_batch_falls_back_to_one_diff_per_commit(repo: Path, monkeypatch) -> None:
    ps = pairs(repo)[:4]
    want = {sha: evidence.commit_diff(str(repo), parent, sha) for sha, parent in ps}

    def refuse(*a, **k):
        raise RuntimeError("git log: refused")
    monkeypatch.setattr(evidence, "log_patches", refuse)
    assert evidence.commit_diffs(str(repo), ps) == want


def test_subjects_in_one_call_and_an_unknown_sha_drops_only_itself(repo: Path) -> None:
    shas = [s for s, _ in pairs(repo)][:5]
    want = {s: synth.run(repo, "log", "-1", "--format=%s", s).strip() for s in shas}
    evidence.Timing.reset(True)
    assert evidence.subjects(str(repo), shas + shas[:2]) == want
    assert sum(evidence.Timing.calls.values()) == 1
    assert evidence.subjects(str(repo), shas + ["0" * 40]) == want
    evidence.Timing.reset(False)


def test_dossier_is_the_same_with_and_without_the_batched_reads(repo: Path, monkeypatch) -> None:
    ev = evidence.investigate(str(repo), use_cache=False)
    u = next(x for x in ev["timeline"] if x["pr"] == 20)
    assert len([c for c in u["commits"] if c.get("is_fix")]) == 2
    assert any(k[0] == u["commits"][0]["sha"][:12] for k in evidence._BLAME_MEMO)
    fast = evidence.dossier(str(repo), u, ev["unit_shas"])
    assert "culprits:" in fast and "### Files in this fix" in fast

    def refuse(*a, **k):
        raise RuntimeError("refused")
    evidence._BLAME_MEMO.clear()                                   # as a saved run read later by --show
    monkeypatch.setattr(evidence, "log_patches", refuse)
    assert evidence.dossier(str(repo), u, ev["unit_shas"]) == fast


def test_git_call_budget_on_the_synthetic_history(repo: Path) -> None:
    """Counted, not timed: seconds differ by 100x between machines, the number of processes does not.
    58 calls when this was written (102 before the batched reads). Raise the budget only with a reason in the changelog."""
    evidence.Timing.reset(True)
    ev = evidence.investigate(str(repo), use_cache=False, workers=1)
    for label in evidence.triage(ev):
        evidence.dossier(str(repo), next(x for x in ev["timeline"] if x["unit"] == label), ev["unit_shas"])
    calls = sum(evidence.Timing.calls.values())
    evidence.Timing.reset(False)
    assert calls <= 65, f"{calls} git calls ({evidence.Timing.calls})"
