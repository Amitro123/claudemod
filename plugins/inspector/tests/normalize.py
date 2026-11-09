"""Normalize an evidence run so two runs can be diffed: volatile fields (absolute paths, run folders,
the script's own location, path separators) are replaced by placeholders. Results are untouched.

    python normalize.py A.json B.json --out-a RUN_A_DIR --out-b RUN_B_DIR   # exit 0 if equal after normalizing
    python normalize.py A.md B.md --out-a RUN_A_DIR --out-b RUN_B_DIR
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
    # snapshot provenance (0.3.1): the plugin's own location, content fingerprint and version describe the
    # installed copy, not the results, so they are blanked. Schema, repository, and every collection option
    # stay compared.
    plugin = (out.get("snapshot") or {}).get("plugin")
    if isinstance(plugin, dict):
        plugin.update(path="<PLUGIN>", fingerprint="<FINGERPRINT>", version="<VERSION>")
    return out


def normalize_md(text: str, volatile: list[str]) -> str:
    text = _swap(text, volatile, "<VOLATILE>")
    text = re.sub(r"python3 '?[^\s']*evidence\.py'?", "python3 <SCRIPT>", text)
    # shell quoting of a path is platform dependent (a Windows path is quoted, a POSIX temp path is not)
    text = text.replace("'<VOLATILE>'", "<VOLATILE>")
    text = re.sub(r"^Inspector \S+ · fingerprint [0-9a-f]+$", "Inspector <VERSION> · fingerprint <FINGERPRINT>", text, flags=re.M)
    text = re.sub(r"^Plugin files: `.*`$", "Plugin files: `<PLUGIN>`", text, flags=re.M)
    text = re.sub(r"(<VOLATILE>)[\\/]cases[\\/]", r"\1/cases/", text)
    return text.replace("\\", "/")


def _main(argv: list[str]) -> int:
    """normalize.py A B [--out-a DIR] [--out-b DIR]: compare two evidence.json (or .md) files."""
    files = [x for x in argv if not x.startswith("--")]
    outs = {k: argv[i + 1] for i, k in enumerate(argv) if k in ("--out-a", "--out-b") and i + 1 < len(argv)}
    files = [x for x in files if x not in outs.values()]
    if len(files) != 2:
        print(__doc__)
        return 2
    if files[0].endswith(".json"):
        ra, rb = (json.loads(Path(f).read_text(encoding="utf-8")) for f in files)
        na = normalize_json(ra, [outs.get("--out-a", "")])
        nb = normalize_json(rb, [outs.get("--out-b", "")])
        bad = [k for k in na if na[k] != nb.get(k)]
        print("IDENTICAL after normalization" if not bad else "differs: " + ", ".join(bad))
        return 1 if bad else 0
    na = normalize_md(Path(files[0]).read_text(encoding="utf-8"), [outs.get("--out-a", "")])
    nb = normalize_md(Path(files[1]).read_text(encoding="utf-8"), [outs.get("--out-b", "")])
    print("IDENTICAL after normalization" if na == nb else "differs")
    return 0 if na == nb else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
