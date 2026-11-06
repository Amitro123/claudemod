#!/usr/bin/env python3
"""Collect the evidence for a bug investigation from a repository's git history.

Walks the first-parent history of a branch. Each first-parent commit is one *unit*: a merged PR
(a merge commit, or a squash commit ending in "(#N)") or a direct commit. For every unit it records
what changed, how strongly it looks like a bug fix, and, for a fix, which earlier units wrote the
lines the fix deleted or changed (SZZ: `git blame` on the fix's parent). A fix whose blamed lines
come from another fix is a fix-of-fix: the first fix broke something, or didn't finish the job.

Stdlib only, offline, read-only. The fix score is a heuristic for Claude to confirm by reading the
diff, not a verdict.

    python evidence.py [--repo .] [--ref HEAD] [--since REF|YYYY-MM-DD] [--max 200]
                       [--json out.json] [--md out.md]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

FIX_WORDS = [
    (r"\bfix(es|ed|ing)?\b", 2), (r"\bbug(s|fix)?\b", 2), (r"\bregress(ion|ed)?\b", 3),
    (r"\brevert(s|ed)?\b", 3), (r"\bhotfix\b", 3), (r"\bbroke(n)?\b", 2), (r"\bcrash(es|ed)?\b", 2),
    (r"\bno longer\b", 1), (r"\binstead of\b", 1), (r"\bwrong\b", 1), (r"\bstale\b", 1),
    (r"\brace\b", 1), (r"\bleak(s|ed)?\b", 1), (r"\bNaN\b", 1), (r"\bnever\b", 1),
    (r"\bfound\b", 1), (r"\breview\b", 1), (r"\bmissing\b", 1), (r"\bdoesn't|don't|didn't\b", 1),
    (r"תיקון|תוקן|באג|תקלה|נשבר|שבור", 2),
]
FEATURE_WORDS = [r"\badd(s|ed)?\b", r"\bnew\b", r"\bintroduc(e|es|ed)\b", r"\bfeature\b"]
VERSION_RE = re.compile(r'^([+-])\s*"version"\s*:\s*"(\d+)\.(\d+)\.(\d+)"', re.M)
PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)")
PR_SQUASH_RE = re.compile(r"\(#(\d+)\)\s*$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)

NOT_CODE = {"(root)", "assets", "demo", "docs", ".github", ".claude-plugin"}

# Lines here say what changed, not what broke: blaming them only finds the last release.
NOT_BLAMED = re.compile(
    r"(\.md$|\.lock$|package-lock\.json$|(^|/)plugin\.json$|marketplace\.json$|"
    r"\.(png|gif|jpg|jpeg|svg|ico|webp)$|(^|/)evals/results/)"
)


def git(repo: str, *args: str, ok_codes=(0,)) -> str:
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode not in ok_codes:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def component(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("plugins", "packages", "apps", "services", "libs"):
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if len(parts) > 1 else "(root)"


@dataclass
class Unit:
    sha: str
    kind: str                     # pr | commit
    pr: int | None
    title: str
    date: str
    base: str | None              # first parent ('' for the root commit)
    commits: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    fix_score: int = 0
    signals: list[str] = field(default_factory=list)
    version_bumps: list[str] = field(default_factory=list)
    introduced_by: list[dict] = field(default_factory=list)
    fix_of_fix: bool = False

    @property
    def is_fix(self) -> bool:
        return self.fix_score >= 2

    def label(self) -> str:
        return f"#{self.pr}" if self.pr else self.sha[:8]


def score_text(text: str) -> tuple[int, list[str]]:
    score, hits = 0, []
    for pat, w in FIX_WORDS:
        m = re.search(pat, text, re.I)
        if m:
            score += w
            hits.append(m.group(0).lower())
    if score and any(re.search(p, text.split("\n")[0], re.I) for p in FEATURE_WORDS):
        score -= 1
    return score, hits


def first_parent_units(repo: str, ref: str, since: str | None, limit: int) -> list[Unit]:
    rng = [ref]
    if since:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
            rng = [f"--since={since}", ref]
        else:
            rng = [f"{since}..{ref}"]
    out = git(repo, "log", "--first-parent", f"--max-count={limit}",
              "--format=%H%x1f%P%x1f%cs%x1f%s%x1f%b%x1e", *rng)
    units = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, parents, date, subject, body = (rec.split("\x1f") + [""] * 5)[:5]
        parents = parents.split()
        m = PR_MERGE_RE.match(subject)
        if len(parents) >= 2:
            title = next((ln for ln in body.splitlines() if ln.strip()), subject)
            units.append(Unit(sha, "pr", int(m.group(1)) if m else None, title.strip(), date,
                              parents[0]))
            units[-1].commits = inner_commits(repo, parents[0], parents[1])
        else:
            sq = PR_SQUASH_RE.search(subject)
            u = Unit(sha, "pr" if sq else "commit", int(sq.group(1)) if sq else None, subject,
                     date, parents[0] if parents else "")
            u.commits = [{"sha": sha, "subject": subject, "body": body.strip()}]
            units.append(u)
    units.reverse()  # oldest first, so a commit belongs to the first unit that merged it
    return units


def inner_commits(repo: str, base: str, head: str) -> list[dict]:
    out = git(repo, "log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..{head}")
    res = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            sha, subject, body = (rec.split("\x1f") + ["", ""])[:3]
            res.append({"sha": sha, "subject": subject, "body": body.strip()})
    res.reverse()
    return res


def fill_changes(repo: str, u: Unit) -> None:
    base = u.base or git(repo, "hash-object", "-t", "tree", "/dev/null").strip()
    for line in git(repo, "diff", "--numstat", "-M", base, u.sha).splitlines():
        a, d, path = line.split("\t", 2)
        if " => " in path:
            path = re.sub(r"\{[^}]* => ([^}]*)\}", r"\1", path).split(" => ")[-1]
        ins, dele = (int(a) if a != "-" else 0), (int(d) if d != "-" else 0)
        u.files.append({"path": path, "ins": ins, "del": dele})
        u.insertions += ins
        u.deletions += dele
    u.components = sorted({component(f["path"]) for f in u.files})
    for m in VERSION_RE.finditer(git(repo, "diff", "-U0", base, u.sha, "--", "*.json")):
        u.version_bumps.append(f"{m.group(1)}{m.group(2)}.{m.group(3)}.{m.group(4)}")


def score_unit(u: Unit) -> None:
    text = "\n".join([u.title] + [c["subject"] + "\n" + c["body"] for c in u.commits])
    u.fix_score, u.signals = score_text(text)
    old = sorted(v[1:] for v in u.version_bumps if v[0] == "-")
    new = sorted(v[1:] for v in u.version_bumps if v[0] == "+")
    for o, n in zip(old, new):
        o3, n3 = o.split("."), n.split(".")
        if o3[:2] == n3[:2] and o3[2] != n3[2]:
            u.fix_score += 2
            u.signals.append(f"patch bump {o}->{n}")
            break


def blame_origins(repo: str, commit: str, max_lines: int) -> Counter:
    """Commits that last wrote the lines `commit` deleted or changed."""
    origins: Counter = Counter()
    try:
        parent = git(repo, "rev-parse", f"{commit}^").strip()
    except RuntimeError:
        return origins  # root commit
    names = git(repo, "diff", "--name-only", "--diff-filter=MD", parent, commit).splitlines()
    budget = max_lines
    for path in names:
        if NOT_BLAMED.search(path) or budget <= 0:
            continue
        diff = git(repo, "diff", "-U0", "--no-color", parent, commit, "--", path)
        for m in HUNK_RE.finditer(diff):
            start, count = int(m.group(1)), int(m.group(2) or "1")
            if count == 0 or budget <= 0:
                continue
            count = min(count, budget)
            budget -= count
            try:
                out = git(repo, "blame", "-w", "--porcelain", "-L", f"{start},+{count}",
                          parent, "--", path)
            except RuntimeError:
                continue
            sha, content = None, None
            for ln in out.splitlines():
                if re.match(r"^[0-9a-f]{40} ", ln):
                    sha = ln.split()[0]
                elif ln.startswith("\t"):
                    content = ln[1:].strip()
                    if sha and content and content not in ("}", "{", ")", "];", "});"):
                        origins[(sha, path)] += 1
    return origins


def code_components(u: Unit) -> list[str]:
    return sorted({component(f["path"]) for f in u.files
                   if not NOT_BLAMED.search(f["path"]) and component(f["path"]) not in NOT_CODE})


def investigate(repo: str, ref: str, since: str | None, limit: int, max_blame: int,
                min_lines: int = 3) -> dict:
    shallow = git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"
    units = first_parent_units(repo, ref, since, limit)
    owner: dict[str, Unit] = {}
    for u in units:
        owner.setdefault(u.sha, u)
        for c in u.commits:
            owner.setdefault(c["sha"], u)
    for u in units:
        fill_changes(repo, u)
        score_unit(u)
    for u in units:
        if not u.is_fix:
            continue
        per_unit: dict[str, dict] = {}
        for c in u.commits:
            for (sha, path), n in blame_origins(repo, c["sha"], max_blame).items():
                src = owner.get(sha)
                key = src.label() if src else f"{sha[:8]} (before the window)"
                if src is u:
                    continue  # rewrote its own lines
                e = per_unit.setdefault(key, {"unit": key, "sha": sha[:12], "lines": 0,
                                              "files": set(), "is_fix": bool(src and src.is_fix),
                                              "title": src.title if src else ""})
                e["lines"] += n
                e["files"].add(path)
        u.introduced_by = sorted(
            ({**e, "files": sorted(e["files"])} for e in per_unit.values()),
            key=lambda e: -e["lines"])
        u.fix_of_fix = any(e["is_fix"] and e["lines"] >= min_lines for e in u.introduced_by)

    fixes = [u for u in units if u.is_fix]
    hot = Counter(f["path"] for u in fixes for f in u.files if not NOT_BLAMED.search(f["path"]))
    blamed = Counter()
    for u in fixes:
        for e in u.introduced_by:
            blamed[e["unit"]] += e["lines"]
    by_comp = Counter(c for u in fixes for c in code_components(u))
    return {
        "repo": repo, "ref": ref, "since": since, "shallow": shallow,
        "units": len(units), "fixes": len(fixes),
        "fix_of_fix": [u.label() for u in fixes if u.fix_of_fix],
        "cross_component_fixes": [u.label() for u in fixes if len(code_components(u)) >= 2],
        "hotspot_files": hot.most_common(15),
        "fix_components": by_comp.most_common(),
        "most_blamed_units": blamed.most_common(10),
        "timeline": [unit_json(u) for u in units],
    }


def unit_json(u: Unit) -> dict:
    return {
        "unit": u.label(), "sha": u.sha[:12], "kind": u.kind, "pr": u.pr, "date": u.date,
        "title": u.title, "is_fix": u.is_fix, "fix_score": u.fix_score, "signals": u.signals,
        "components": u.components, "insertions": u.insertions, "deletions": u.deletions,
        "files": u.files, "version_bumps": u.version_bumps,
        "commits": [{"sha": c["sha"][:12], "subject": c["subject"]} for c in u.commits],
        "introduced_by": u.introduced_by, "fix_of_fix": u.fix_of_fix,
    }


def markdown(r: dict) -> str:
    L = [f"# Evidence: {r['repo']} ({r['ref']}{', since ' + r['since'] if r['since'] else ''})", ""]
    if r["shallow"]:
        L += ["> **Shallow clone**: blame stops at the clone's boundary. Run "
              "`git fetch --unshallow` and collect again before trusting `introduced_by`.", ""]
    L += [f"- Units (PRs and direct commits): {r['units']}; likely fixes: {r['fixes']}",
          f"- Fix-of-fix (a fix changed lines another fix wrote): {', '.join(r['fix_of_fix']) or 'none'}",
          f"- Fixes spanning 2+ components: {', '.join(r['cross_component_fixes']) or 'none'}", ""]
    L += ["## Hotspots (files changed by fixes)", ""]
    L += [f"- `{p}`: {n}" for p, n in r["hotspot_files"]] or ["- none"]
    L += ["", "## Components the fixes landed in", ""]
    L += [f"- {c}: {n}" for c, n in r["fix_components"]] or ["- none"]
    L += ["", "## Units whose lines the fixes changed most (suspects)", ""]
    L += [f"- {u}: {n} lines" for u, n in r["most_blamed_units"]] or ["- none"]
    L += ["", "## Timeline (oldest first)", "",
          "| unit | date | fix? | score | components | +/- | introduced by (lines) |",
          "|---|---|---|---|---|---|---|"]
    for u in r["timeline"]:
        intro = ", ".join(f"{e['unit']}{'*' if e['is_fix'] else ''} ({e['lines']})"
                          for e in u["introduced_by"][:4])
        title = u["title"].replace("|", "/")[:70]
        L.append(f"| {u['unit']} {title} | {u['date']} | {'fix' if u['is_fix'] else ''}"
                 f"{' ↺' if u['fix_of_fix'] else ''} | {u['fix_score']} | "
                 f"{', '.join(u['components'])[:40]} | +{u['insertions']}/-{u['deletions']} | {intro} |")
    L += ["", "`*` the blamed unit is itself a fix. `↺` fix-of-fix. Scores are keyword and "
          "version-bump heuristics: read the diff before you call anything a bug."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--since", help="a ref (tag, sha) or a date YYYY-MM-DD")
    ap.add_argument("--max", type=int, default=200, help="most first-parent units to read")
    ap.add_argument("--max-blame-lines", type=int, default=400, help="per fix commit")
    ap.add_argument("--min-lines", type=int, default=3,
                    help="blamed lines from an earlier fix that make a fix-of-fix")
    ap.add_argument("--json", help="write the full evidence here")
    ap.add_argument("--md", help="write the summary here (default: stdout)")
    a = ap.parse_args(argv)
    try:
        r = investigate(a.repo, a.ref, a.since, a.max, a.max_blame_lines, a.min_lines)
    except RuntimeError as e:
        print(f"evidence.py: {e}", file=sys.stderr)
        return 1
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
    md = markdown(r)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
