"""Blame line counts leave out the same trivial lines the copy detector leaves out (comments, bare return/pass/break)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402
from test_evidence import commit, new_repo  # noqa: E402

COMMENTS = "".join(f"# note {i}\n" for i in range(1, 6))


def _repo(tmp_path: Path) -> Path:
    r = new_repo(tmp_path / "repo")
    commit(r, {"README.md": "# demo\n"}, "initial")
    # unit A (a fix) writes one real line and five comment lines; unit B writes two real lines elsewhere
    commit(r, {"a.py": "x = compute(1)\n" + COMMENTS}, "fix: handle a missing value")
    commit(r, {"b.py": "y = load(2)\nz = save(3)\n"}, "Add b")
    # the later fix rewrites every line of both files
    commit(r, {"a.py": "x = compute(2)\n" + COMMENTS.replace("note", "remark"), "b.py": "y = load(3)\nz = save(4)\n"},
           "fix: crash in a and b")
    return r


def test_comment_only_lines_do_not_inflate_the_culprit_or_fix_of_fix(tmp_path: Path) -> None:
    r = evidence.investigate(str(_repo(tmp_path)), min_lines=3, github=False)
    last = r["timeline"][-1]
    assert last["title"].startswith("fix: crash")
    top = last["introduced_by"][0]
    assert top["lines"] == 2 and not top["is_fix"], last["introduced_by"]   # Add b (2 real lines), not fix A (1 real + 5 comments)
    assert not last["fix_of_fix"]                            # fix A wrote 1 non-trivial line, below min_lines=3


def test_count_origins_skips_what_the_copy_detector_skips() -> None:
    sha = "a" * 40
    out = f"{sha} 1 1 5\nauthor x\n\t# a comment\n\t// another\n\treturn\n\tpass\n\tbreak\n\tx = f(1)\n\t}}\n"
    assert evidence._count_origins(out) == [[sha, 1]]


def test_blame_cache_version_was_bumped() -> None:
    assert evidence.BLAME_CACHE_VERSION == "v4"
