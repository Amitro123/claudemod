"""Find sensitive material without printing it: where it is, what kind, and whether it looks real.

    python scan.py --repo . --ref origin/main                 # files at a ref (what is published)
    python scan.py --repo . --range origin/main..my-branch    # lines added by those commits
    python scan.py --repo . --worktree [--include-ignored]    # tracked + untracked files on disk (+ git-ignored ones)
    python scan.py --paths DIR [DIR ...]                      # any folder, git or not
    options: --secret-env NAME (a value to look for, read from that environment variable, e.g. the tenant id;
             repeatable) --allow-domain example.com --json --out FILE --max-findings 400

Kinds: email (reported by domain), token (GitHub, GitLab, Slack, AWS, OpenAI-style keys, JWTs), bearer,
private-key, azure-devops-pat (a 52-character token on a line that says pat/token/password), guid-near-tenant
(a GUID on a line that says tenant, entra, directory or tid), secret-env:<NAME> (the value of that variable),
raw-log (an Azure DevOps log marker, a Python traceback, a PowerShell error record, or 10+ timestamped lines).

Each finding: kind, path, line, where it lives (ref, commit, tracked, untracked, ignored), class
(placeholder / test-fixture / code-reference / likely-real) and a detail that never holds the value (a
domain, a length, a prefix kind). Values never reach stdout, a file or the command line: pass a value to look
for by naming the variable that holds it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
TOKENS = [
    ("github", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("gitlab", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api-key", re.compile(r"\bsk-(?:ant-|or-|proj-)?[A-Za-z0-9_-]{24,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]
BEARER = re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{16,})")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
ADO_PAT = re.compile(r"(?<![A-Za-z0-9])[a-z2-7]{52}(?![A-Za-z0-9])")
ADO_PAT_LINE = re.compile(r"\b(pat|token|password|secret|personal access)\b", re.I)
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
TENANT_LINE = re.compile(r"\b(tenant|entra|directory|tid)\b", re.I)
LOG_MARKERS = re.compile(r"##\[(?:error|warning|section|command|group)\]|Traceback \(most recent call last\)|"
                         r"\+ CategoryInfo\s*:|FullyQualifiedErrorId\s*:")
TS_LINE = re.compile(r"^\s*\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
PLACEHOLDER = re.compile(r"fake|example|dummy|xxxx|redact|placeholder|synthetic|sample|changeme|test|0000000|1234567|<[^>]+>", re.I)
CODE_EXT = {".py", ".ts", ".js", ".tsx", ".jsx", ".ps1", ".psm1", ".cs", ".go", ".rs", ".java", ".rb", ".sh"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".exe", ".dll", ".so",
            ".pyc", ".woff", ".woff2", ".ttf", ".mp4", ".mov", ".lock"}
SAFE_DOMAINS = ("example.com", "example.org", "example.net", "invalid", "localhost", "test", "users.noreply.github.com")
FIXTURE_DIR = re.compile(r"(^|/)(tests?|fixtures?|__fixtures__|testdata|spec)(/|$)", re.I)


def run(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def classify(path: str, line: str, value: str) -> str:
    if PLACEHOLDER.search(value) or re.fullmatch(r"[a-z]+(?:[-_][a-z]+){2,}", value):
        return "placeholder"
    if FIXTURE_DIR.search(path.replace("\\", "/")):
        return "test-fixture"
    return "likely-real"


def scan_text(path: str, where: str, text: str, secrets: dict[str, str], allow: tuple[str, ...], out: list, line_no=None):
    ext = Path(path).suffix.lower()
    ts_run = 0
    lines = text.splitlines()
    log_reported = False
    for i, ln in enumerate(lines, 1):
        n = line_no[i - 1] if line_no else i
        for m in EMAIL.finditer(ln):
            dom = m.group(1).lower()
            if dom.endswith(allow):
                continue
            out.append({"kind": "email", "path": path, "line": n, "where": where, "class": classify(path, ln, m.group(0)),
                        "detail": f"domain={dom}"})
        for name, rx in TOKENS:
            for m in rx.finditer(ln):
                v = m.group(0)
                out.append({"kind": "token", "path": path, "line": n, "where": where, "class": classify(path, ln, v),
                            "detail": f"type={name} length={len(v)}"})
        for m in BEARER.finditer(ln):
            v = m.group(1)
            if any(rx.search(v) for _, rx in TOKENS):
                continue
            out.append({"kind": "bearer", "path": path, "line": n, "where": where, "class": classify(path, ln, v),
                        "detail": f"length={len(v)} jwt_shape={v.startswith('eyJ')}"})
        if PRIVATE_KEY.search(ln):
            out.append({"kind": "private-key", "path": path, "line": n, "where": where, "class": classify(path, ln, ln), "detail": "PEM header"})
        if ADO_PAT_LINE.search(ln):
            for m in ADO_PAT.finditer(ln):
                out.append({"kind": "azure-devops-pat", "path": path, "line": n, "where": where,
                            "class": classify(path, ln, m.group(0)), "detail": "52 chars, base32 alphabet, on a line naming a token"})
        if TENANT_LINE.search(ln):
            for m in GUID.finditer(ln):
                if any(m.group(0).lower() == v for v in secrets.values()):
                    continue
                out.append({"kind": "guid-near-tenant", "path": path, "line": n, "where": where,
                            "class": classify(path, ln, m.group(0)), "detail": "a GUID on a line naming tenant/entra/directory/tid"})
        low = ln.lower()
        for name, v in secrets.items():
            if v and v in low:
                out.append({"kind": f"secret-env:{name}", "path": path, "line": n, "where": where, "class": "likely-real",
                            "detail": f"the value of ${name}"})
        mk = LOG_MARKERS.search(ln)
        if mk and not log_reported:
            code_ref = ext in CODE_EXT and re.search(r"[\"'`]" + re.escape(mk.group(0)[:8]), ln)
            out.append({"kind": "raw-log", "path": path, "line": n, "where": where,
                        "class": "code-reference" if code_ref else ("test-fixture" if FIXTURE_DIR.search(path) else "likely-real"),
                        "detail": f"marker={mk.group(0)[:30]}"})
            log_reported = not code_ref
        ts_run = ts_run + 1 if TS_LINE.match(ln) else 0
        if ts_run == 10 and not log_reported:
            out.append({"kind": "raw-log", "path": path, "line": n - 9, "where": where,
                        "class": "test-fixture" if FIXTURE_DIR.search(path) else "likely-real", "detail": "10+ consecutive timestamped lines"})
            log_reported = True


def readable(path: str, size: int) -> bool:
    return Path(path).suffix.lower() not in SKIP_EXT and size <= 2_000_000


def scan_ref(repo: Path, ref: str, secrets, allow, out):
    listing = run(repo, "ls-tree", "-r", "-l", ref)
    files = []
    for ln in listing.splitlines():
        meta, _, path = ln.partition("\t")
        parts = meta.split()
        if len(parts) >= 4 and parts[1] == "blob" and parts[3].isdigit() and readable(path, int(parts[3])):
            files.append((parts[2], path))
    p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for sha, path in files:
        p.stdin.write((sha + "\n").encode())
        p.stdin.flush()
        header = p.stdout.readline().split()
        size = int(header[2])
        data = p.stdout.read(size)
        p.stdout.read(1)
        if b"\0" in data[:8000]:
            continue
        scan_text(path, f"ref:{ref}", data.decode("utf-8", errors="replace"), secrets, allow, out)
    p.stdin.close()
    p.wait()


_ESC = {"a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def unquote_path(s: str) -> str:
    """A path as git prints it in a diff header: plain (with a tab after it when it holds a space), or
    C-quoted with octal bytes for anything outside printable ASCII (a Hebrew name, a tab, a quote)."""
    if not s.startswith('"'):
        return s.rstrip("\t")
    out, i, body = bytearray(), 1, s.rstrip("\t")
    while i < len(body) and body[i] != '"':
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567":
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out += _ESC.get(nxt, nxt).encode()
            i += 2
            continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def _merge_mode(repo: Path) -> str:
    """remerge shows only what a merge itself changed against git's own merge of its parents (git 2.36+);
    an older git gets the first-parent diff, which repeats the side branch's lines."""
    p = subprocess.run(["git", "-C", str(repo), "log", "-1", "--diff-merges=remerge", "--format=%H"], capture_output=True, text=True)
    return "remerge" if p.returncode == 0 else "first-parent"


# The diff's shape is the scanner's, not the user's: a repository's diff.noprefix, mnemonicPrefix, an external
# diff tool or a textconv filter would change the "+++ b/<path>" lines the parser reads, and nothing would match;
# log.showRoot=false would hide the first commit's diff (--root shows it); a `-diff` or `binary` attribute in
# .gitattributes would print "Binary files differ" instead of the lines (--text prints them). A file that really
# is binary (a NUL byte in what it adds) is then skipped by _scan_log, as scan_files skips it in a tree.
DIFF_SHAPE = ["--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "--root", "--text"]


# Files the scan never reads, left out by git itself: with --text it would otherwise print every image and archive
# in the range in full.
SKIP_PATHSPEC = ["--", ".", *[f":(exclude,glob,icase)**/*{e}" for e in sorted(SKIP_EXT)]]


def scan_range(repo: Path, rng: str, secrets, allow, out):
    # Two passes: every commit, merges of two parents by what the merge itself changed (remerge); then merges of
    # three or more parents (an octopus), which remerge shows nothing for, as a dense combined diff, keeping only
    # the lines that are in none of the parents.
    _scan_log(run(repo, "-c", "core.quotePath=true", "log", "-p", *DIFF_SHAPE, f"--diff-merges={_merge_mode(repo)}",
                  "--format=commit %H", "--unified=0", rng, *SKIP_PATHSPEC), secrets, allow, out)
    _scan_log(run(repo, "-c", "core.quotePath=true", "log", "-p", *DIFF_SHAPE, "--min-parents=3",
                  "--diff-merges=dense-combined", "--format=commit %H", "--unified=0", rng, *SKIP_PATHSPEC), secrets, allow, out, combined=True)


def _scan_log(text: str, secrets, allow, out, combined: bool = False):
    sha, path, buf, nums, n = None, None, [], [], 0
    in_header = False  # between "diff --git" and the first "@@": only there is "+++ " a file name, not an added "++ " line
    cols = 1  # a combined diff has one marker column per parent ("@@@" for two, "@@@@" for three)

    def flush():
        # A NUL byte in what the commit added: a real binary, read as text only because of --text.
        if path and buf and not any("\0" in line for line in buf):
            scan_text(path, f"commit:{sha[:12]}", "\n".join(buf), secrets, allow, out, line_no=nums)

    for ln in text.splitlines():
        if ln.startswith("commit ") and len(ln) == 47:
            flush()
            sha, path, buf, nums, in_header = ln[7:], None, [], [], False
        elif ln.startswith("diff --git ") or ln.startswith("diff --cc ") or ln.startswith("diff --combined "):
            flush()
            path, buf, nums, in_header = None, [], [], True
        elif in_header and ln.startswith("+++ "):
            flush()
            target = unquote_path(ln[4:])
            path, buf, nums = (target[2:] if target.startswith("b/") else None), [], []
        elif ln.startswith("@@"):
            in_header = False
            cols = max(1, len(ln) - len(ln.lstrip("@")) - 1)
            m = re.search(r"\+(\d+)", ln)
            n = int(m.group(1)) if m else 0
        elif not in_header and path and readable(path, 0) and len(ln) >= cols:
            marks = ln[:cols]
            if "-" in marks:
                continue  # a line only a parent had: not in the result
            if marks == "+" * cols or (not combined and marks == "+"):
                buf.append(ln[cols:])
                nums.append(n)
            n += 1
    flush()


def scan_files(root: Path, rel: list[tuple[str, str]], secrets, allow, out):
    for path, where in rel:
        f = root / path
        try:
            if not f.is_file() or not readable(path, f.stat().st_size):
                continue
            data = f.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8000]:
            continue
        scan_text(path, where, data.decode("utf-8", errors="replace"), secrets, allow, out)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ref")
    g.add_argument("--range")
    g.add_argument("--worktree", action="store_true")
    g.add_argument("--paths", nargs="+")
    ap.add_argument("--include-ignored", action="store_true")
    ap.add_argument("--secret-env", action="append", default=[])
    ap.add_argument("--allow-domain", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--max-findings", type=int, default=400)
    a = ap.parse_args(argv)
    secrets = {}
    for name in a.secret_env:
        v = os.environ.get(name, "").strip().lower()
        if not v:
            print(f"warning: ${name} is empty; not searched", file=sys.stderr)
        elif len(v) < 8:
            print(f"warning: ${name} is shorter than 8 characters; not searched (too many false matches)", file=sys.stderr)
        else:
            secrets[name] = v
    allow = SAFE_DOMAINS + tuple(d.lower() for d in a.allow_domain)
    repo = Path(a.repo)
    out: list[dict] = []
    if a.ref:
        scan_ref(repo, a.ref, secrets, allow, out)
        scope = f"files at {a.ref}"
    elif a.range:
        scan_range(repo, a.range, secrets, allow, out)
        scope = f"lines added in {a.range}"
    elif a.worktree:
        root = Path(run(repo, "rev-parse", "--show-toplevel").strip())
        rel = [(p, "tracked") for p in run(root, "ls-files", "-z").split("\0") if p]
        rel += [(p, "untracked") for p in run(root, "ls-files", "-z", "-o", "--exclude-standard").split("\0") if p]
        if a.include_ignored:
            rel += [(p, "ignored") for p in run(root, "ls-files", "-z", "-o", "-i", "--exclude-standard").split("\0") if p]
        scan_files(root, rel, secrets, allow, out)
        scope = "working tree" + (" with ignored files" if a.include_ignored else "")
    else:
        rel = []
        for base in a.paths:
            b = Path(base)
            rel += [(str(f), "path") for f in (b.rglob("*") if b.is_dir() else [b]) if ".git" not in f.parts]
        scan_files(Path("."), rel, secrets, allow, out)
        scope = "paths " + " ".join(a.paths)
    counts = Counter((f["kind"], f["class"]) for f in out)
    domains = Counter(f["detail"] for f in out if f["kind"] == "email")
    report = {"scope": scope, "findings": len(out), "by_kind": {f"{k} ({c})": n for (k, c), n in sorted(counts.items())},
              "email_domains": dict(domains.most_common(30)), "items": out[: a.max_findings],
              "omitted": max(0, len(out) - a.max_findings)}
    if a.json:
        text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        lines = [f"scan: {scope}: {len(out)} findings"]
        lines += [f"  {k}: {n}" for k, n in report["by_kind"].items()]
        if domains:
            lines.append("  email domains: " + ", ".join(f"{d.split('=', 1)[1]} {n}" for d, n in domains.most_common(15)))
        for f in out[: a.max_findings]:
            lines.append(f"{f['kind']}\t{f['class']}\t{f['where']}\t{f['path']}:{f['line']}\t{f['detail']}")
        if report["omitted"]:
            lines.append(f"... {report['omitted']} more (--max-findings)")
        text = "\n".join(lines)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(f"Saved: {a.out} ({len(out)} findings)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
