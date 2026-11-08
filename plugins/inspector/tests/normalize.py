"""Normalize an evidence run so two runs can be diffed: volatile fields (absolute paths, run folders,
the script's own location, path separators) are replaced by placeholders. Results are untouched.

    python normalize.py A.json B.json            # exit 0 if equal after normalizing, else print the first differences
    python normalize.py A.md B.md --repo X --repo Y   # (md) --repo is given once per file, in order
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _swap(text: str, volatile: list[str], token: str) -> str:
    for v in sorted({x for x in volatile if x}, key=len, reverse=True):
        for form in (v, v.replace("\\", "/"), v.replace("/", "\\")):
            text = text.replace(form, token)
    return text


def normalize_json(r: dict, extra: list[str] | None = None) -> dict:
    """The evidence dict with machine-specific values replaced. `extra`: more strings to blank
    (e.g. the run folder)."""
    text = json.dumps(r, ensure_ascii=False, sort_keys=False)
    vol = [r.get("repo_path", ""), r.get("repo", "")] + list(extra or [])
    # json escapes backslashes: swap the escaped forms too
    esc = [json.dumps(v)[1:-1] for v in vol if v]
    text = _swap(text, esc, "<REPO>")
    text = _swap(text, vol, "<REPO>")
    out = json.loads(text)
    out["repo_path"] = "<REPO>"
    out["repo"] = "<REPO>"
    return out


def normalize_md(text: str, volatile: list[str]) -> str:
    text = _swap(text, volatile, "<VOLATILE>")
    text = re.sub(r"python3 \S+evidence\.py", "python3 <SCRIPT>", text)
    text = re.sub(r"(<VOLATILE>)[\\/]cases[\\/]", r"\1/cases/", text)
    return text.replace("\\", "/")


def _main(argv: list[str]) -> int:
    files = [a for a in argv if not a.startswith("--") and a not in ()]
    if len(files) != 2:
        print(__doc__)
        return 2
    a, b = (Path(f).read_text(encoding="utf-8") for f in files)
    if files[0].endswith(".json"):
        na, nb = normalize_json(json.loads(a)), normalize_json(json.loads(b))
        if na == nb:
            print("IDENTICAL after normalization")
            return 0
        for k in na:
            if na[k] != nb.get(k):
                print("differs:", k)
        return 1
    na, nb = a.replace("\\", "/"), b.replace("\\", "/")
    return 0 if na == nb else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
