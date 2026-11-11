"""--unit with a sha prefix that two units share is an error naming the candidates, not a silent first match."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "inspect" / "scripts"))

import evidence  # noqa: E402
from test_evidence import new_repo, run  # noqa: E402

IDENT = "T <t@example.com> 1700000000 +0000"


@pytest.fixture(scope="module")
def clash(tmp_path_factory) -> tuple[Path, str, list[str]]:
    """A repository whose last commit shares its first 4 hex digits with an earlier one (found by varying the
    message of that last commit; hashing the commit object here is cheap). Returns (repo, shared prefix, both shas)."""
    r = new_repo(tmp_path_factory.mktemp("clash") / "repo")
    stream = []
    for i in range(1, 61):
        body, msg = f"change {i}\n", f"Add file {i}"
        stream.append(f"commit refs/heads/main\nmark :{i}\ncommitter {IDENT}\ndata {len(msg)}\n{msg}\n")
        stream.append(f"from :{i - 1}\n" if i > 1 else "")
        stream.append(f"M 644 inline f{i}.txt\ndata {len(body)}\n{body}\n")
    subprocess.run(["git", "-C", str(r), "fast-import", "--quiet"], input="".join(stream).encode(), check=True)
    head = run(r, "rev-parse", "main").strip()
    tree = run(r, "rev-parse", "main^{tree}").strip()
    earlier = run(r, "rev-list", "--first-parent", "main").split()
    prefixes = {s[:4]: s for s in earlier}
    for salt in range(2_000_000):
        text = f"tree {tree}\nparent {head}\nauthor {IDENT}\ncommitter {IDENT}\n\nAdd file 61 #{salt}\n"
        raw = text.encode()
        sha = hashlib.sha1(b"commit %d\0" % len(raw) + raw).hexdigest()
        if sha[:4] in prefixes:
            made = subprocess.run(["git", "-C", str(r), "hash-object", "-t", "commit", "-w", "--stdin"], input=raw,
                                  check=True, capture_output=True).stdout.decode().strip()
            assert made == sha
            run(r, "update-ref", "refs/heads/main", sha)
            run(r, "reset", "-q", "--hard", "main")
            return r, sha[:4], [prefixes[sha[:4]], sha]
    raise AssertionError("no prefix clash found")


def test_ambiguous_prefix_is_an_error_naming_the_candidates(clash, capsys) -> None:
    r, prefix, both = clash
    assert evidence.main(["--repo", str(r), "--unit", prefix, "--no-github", "--history", "100",
                          "--json", str(r / "o.json")]) == 2
    err = capsys.readouterr().err
    assert "ambiguous" in err and all(s[:8] in err for s in both)
    assert not (r / "o.json").exists()
    with pytest.raises(evidence.AmbiguousUnit):
        evidence.investigate(str(r), unit=prefix, github=False, history=100)


def test_full_sha_and_a_longer_prefix_still_resolve(clash) -> None:
    r, _, both = clash
    for sha in (both[0], both[1][:12]):
        out = evidence.investigate(str(r), unit=sha, github=False, history=100)
        want = both[0] if sha == both[0] else both[1]
        assert [want.startswith(u["sha"]) for u in out["timeline"]] == [True]
