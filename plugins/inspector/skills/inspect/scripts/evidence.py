#!/usr/bin/env python3
"""Collect the evidence for a bug investigation from a repository's git history.

Walks the first-parent history of a branch. Each first-parent commit is one *unit*: a merged PR
(a merge commit, or a squash commit whose subject names the PR) or a direct commit. For every unit
it records what changed and whether it looks like a bug fix; for each fix *commit* inside a fix
unit, which earlier units last wrote the lines it deleted or changed (SZZ: `git blame` on the
commit's parent, following renames). A fix whose blamed lines come from another fix is a
fix-of-fix: the first fix broke something, or didn't finish the job.

Two windows: the *work* window (what --since, --max, --unit and --path select) is what the
investigation works; the *attribution* window (--history units back from --ref) is what blame
results are mapped to, so a fix in the work window still sees that its culprit was a fix.

Stdlib only, offline, read-only. The fix verdict is a heuristic for Claude to confirm by reading
the diff, not a verdict.

    python evidence.py [--repo .] [--ref HEAD] [--since REF|YYYY-MM-DD] [--max 200]
                       [--unit '#N'|SHA] [--path PREFIX [--path PREFIX2 ...]] [--json out.json] [--md out.md]
    python evidence.py --show '#N' --json out.json      # one unit from a saved run

Speed (see plugins/inspector/docs/perf-2026-11.md): --workers N, --cache-dir DIR / --no-cache (blame cache,
default <git dir>/inspector/cache), --exclude PATH / --no-default-excludes, --timing (per-phase time and git calls).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # also under `python -I`, which drops the script folder
import snapshot  # noqa: E402

# Strong: the words people use for a fix. Weak: words fixes use, and so do features; they only
# count beside a strong one. Scored on subjects and titles, never on bodies (a feature PR's body
# lists its "fix lint" and "address review" commits).
STRONG = [
    r"^fix(\(.+\))?!?:", r"\bfix(es|ed|ing)?\b",
    r"\bbug(s|fix)?\b(?!\s+(marker|tracker|report(er|s)?|detective|label|template|icon|bounty))",
    r"\bregress(ion|ed)?\b", r"\breview (fixes|findings)\b",
    r"\brevert(s|ed)?\b", r"\bhotfix\b", r"\bbroke(n)?\b", r"\bcrash(es|ed)?\b",
    r"תיקון|תוקן|באג|תקלה|נשבר|שבור",
]
WEAK = [r"\bno longer\b", r"\bwhat .{0,40}\bfound\b", r"\bwrong\b", r"\bstale\b", r"\brace\b", r"\bleak(s|ed)?\b", r"\bNaN\b",
        r"\bmissing\b", r"\b(doesn't|don't|didn't|isn't|wasn't|can't)\b", r"\binstead of\b"]
# A feature says so first: "Add X", "feat: X", "factory 0.6.0: support Y" (after a "name 1.2.3:" prefix).
FEATURE_START = re.compile(r"^(feat(\(.+\))?!?:|(add|adds|introduce|introduces|support|supports|implement|new)\b)", re.I)
PREFIX = re.compile(r"^([\w.@/-]+( \d+\.\d+(\.\d+|\.x)?)?(, [\w.@/-]+( \d+\.\d+(\.\d+|\.x)?)?)*):\s+")


def starts_as_feature(subject: str) -> bool:
    return bool(FEATURE_START.match(PREFIX.sub("", subject.strip(), count=1)))
# Housekeeping commits inside a feature PR: not a fix of anything that shipped.
CHORE = re.compile(r"\bfix(es|ed)?\s+(the\s+)?(lint|typo|tests?|ci|build|types?|format(ting)?|review)\b"
                   r"|\baddress(ed)?\s+review\b|\breview (comments|feedback)\b", re.I)

BUMP = re.compile(r"^(bump|release|prepare release|chore\(release\))\b|\bbump (the )?versions?\b", re.I)

JSON_VERSION = re.compile(r'^([+-])(\s{0,4})"version"\s*:\s*"(\d+)\.(\d+)\.(\d+)"')
TOML_VERSION = re.compile(r'^([+-])()version\s*=\s*"(\d+)\.(\d+)\.(\d+)"')
PR_PATTERNS = [
    re.compile(r"^Merge pull request #(\d+)"),          # GitHub merge
    re.compile(r"\(#(\d+)\)\s*$"),                      # GitHub squash
    re.compile(r"See merge request [\w./-]*!(\d+)"),    # GitLab (in the body)
    re.compile(r"\(pull request #(\d+)\)"),             # Bitbucket
]
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)

MONOREPO_ROOTS = {"plugins", "packages", "apps", "services", "libs", "crates", "modules",
                  "components", "src", "lib", "pkg", "internal", "cmd"}
NOT_CODE = {"(root)", "assets", "demo", "docs", ".github", ".claude-plugin"}

# Markdown that an agent reads as instructions is code: it is blamed like code.
INSTRUCTIONS = re.compile(r"(^|/)(SKILL|CLAUDE|AGENTS|GEMINI)\.md$|(^|/)(skills|agents|commands|prompts|rules)/.+\.md$",
                          re.I)
# Lines here say what changed, not what broke: blaming them only finds the last release.
NOT_BLAMED = re.compile(
    r"(\.md$|\.mdx$|\.rst$|\.txt$|\.lock$|package-lock\.json$|pnpm-lock\.yaml$|yarn\.lock$|"
    r"(^|/)plugin\.json$|marketplace\.json$|\.(png|gif|jpg|jpeg|svg|ico|webp|pdf)$|(^|/)evals/results/)",
    re.I)
# A unit whose code deletions dominate its additions (a skill or module removed) is a removal, not a
# repair: the authors of deleted files are not culprits, so it gets verdict "removal" and no blame.
# Deleted code lines must be at least REMOVAL_RATIO times the added ones and at least REMOVAL_MIN_DELETED.
REMOVAL_RATIO = 4.0
REMOVAL_MIN_DELETED = 20
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(\.|_)(test|spec)\.[a-z]+$|(^|/)test_[^/]+$", re.I)


def in_scope(file_path: str, paths) -> bool:
    """`file_path` is one of the --path prefixes or below one (no prefixes: everything)."""
    prefixes = [p.rstrip("/") for p in snapshot.path_list(paths)]
    return not prefixes or any(file_path == p or file_path.startswith(p + "/") for p in prefixes)


def blamed(path: str) -> bool:
    return bool(INSTRUCTIONS.search(path)) or not NOT_BLAMED.search(path)


class Timing:
    """Off by default (--timing or INSPECTOR_TIMING=1): wall time and git subprocess calls per phase.
    Never part of evidence.json; printed to stderr."""
    enabled = False
    phase_now = "other"
    seconds: dict[str, float] = {}
    calls: dict[str, int] = {}
    extra: dict[str, str] = {}
    _lock = threading.Lock()

    @classmethod
    def reset(cls, enabled: bool) -> None:
        cls.enabled, cls.phase_now, cls.seconds, cls.calls, cls.extra = enabled, "other", {}, {}, {}

    @classmethod
    def count(cls) -> None:
        if cls.enabled:
            with cls._lock:
                cls.calls[cls.phase_now] = cls.calls.get(cls.phase_now, 0) + 1

    @classmethod
    def report(cls) -> str:
        names = list(dict.fromkeys([*cls.seconds, *cls.calls]))
        rows = [f"{n:<12} {cls.seconds.get(n, 0.0):8.2f}s {cls.calls.get(n, 0):6d} git calls" for n in names]
        rows.append(f"{'total':<12} {sum(cls.seconds.values()):8.2f}s {sum(cls.calls.values()):6d} git calls")
        rows += [f"{k}: {v}" for k, v in cls.extra.items()]
        return "\n".join(rows)


class phase:
    """Context manager: git calls and time inside it are booked to `name`."""
    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.prev, Timing.phase_now, self.t0 = Timing.phase_now, self.name, time.perf_counter()

    def __exit__(self, *exc):
        if Timing.enabled:
            Timing.seconds[self.name] = Timing.seconds.get(self.name, 0.0) + time.perf_counter() - self.t0
        Timing.phase_now = self.prev


def git(repo: str, *args: str, ok_codes=(0,)) -> str:
    Timing.count()
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode not in ok_codes:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def component(path: str, roots: set[str]) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] in roots:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if len(parts) > 1 else "(root)"


@dataclass
class Unit:
    sha: str
    kind: str                     # pr | commit
    pr: int | None
    title: str
    date: str
    base: str                     # first parent ('' for a root or shallow-boundary commit)
    boundary: bool = False        # the oldest commit of a shallow clone: its diff is meaningless
    commits: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    is_fix: bool = False
    why: list[str] = field(default_factory=list)
    version_bumps: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    introduced_by: list[dict] = field(default_factory=list)
    fix_of_fix: bool = False
    verdict: str = ""             # "removal" (see REMOVAL_RATIO) or "" (no verdict beyond is_fix)
    gh: dict = field(default_factory=dict)    # {labels, closes} from GitHub (gh_enrich); empty when not read

    def label(self) -> str:
        return f"#{self.pr}" if self.pr else self.sha[:8]


def words(text: str, pats: list[str]) -> list[str]:
    out = []
    for p in pats:
        m = re.search(p, text, re.I | re.M)
        if m:
            out.append(m.group(0).strip().lower())
    return out


def subject_verdict(subject: str) -> tuple[bool, list[str]]:
    """A commit subject or PR title: a fix when it says so strongly and isn't housekeeping."""
    if CHORE.search(subject):
        return False, ["housekeeping"]
    strong, weak = words(subject, STRONG), words(subject, WEAK)
    if not strong:
        return False, weak
    if starts_as_feature(subject) and not weak and len(strong) == 1:
        return False, strong + ["starts as a feature"]     # "Add X, fix Y's wording"
    return True, strong + weak


def pmap(fn, items, workers: int):
    """fn over items, in order; on a thread pool when workers > 1. Git calls are independent
    subprocesses, so threads overlap their start-up cost (the dominant cost on Windows)."""
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(fn, items))


@dataclass
class RepoInfo:
    shallow: bool
    toplevel: str
    git_dir: str
    shallow_file: str


def repo_info(repo: str) -> RepoInfo:
    """One rev-parse for what used to be four calls."""
    out = git(repo, "rev-parse", "--is-shallow-repository", "--show-toplevel", "--absolute-git-dir",
              "--git-path", "shallow").splitlines()
    sf = out[3].strip()
    return RepoInfo(out[0].strip() == "true", out[1].strip(), out[2].strip(),
                    sf if os.path.isabs(sf) else os.path.join(repo, sf))


def _range(ref: str, since: str | None) -> list[str]:
    if since and re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        return [f"--since={since}", ref]
    return [f"{since}..{ref}"] if since else [ref]


def work_window(repo: str, ref: str, limit: int, since: str | None) -> list[str]:
    """The shas of the work window: a bare log (the units themselves come from the attribution walk)."""
    return git(repo, "log", "--first-parent", f"--max-count={limit}", "--format=%H", *_range(ref, since)).split()


def first_parent(repo: str, ref: str, limit: int, since: str | None, shallow: set[str] | None = None,
                 workers: int = 1) -> list[Unit]:
    out = git(repo, "log", "--first-parent", f"--max-count={limit}",
              "--format=%H%x1f%P%x1f%cs%x1f%s%x1f%b%x1e", *_range(ref, since))
    if shallow is None:
        shallow = set(read_shallow(repo))
    units, tasks = [], []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, parents, date, subject, body = (rec.split("\x1f") + [""] * 5)[:5]
        parents = parents.split()
        pr = next((int(m.group(1)) for p in PR_PATTERNS for m in [p.search(subject) or p.search(body)] if m), None)
        if len(parents) >= 2:
            title = next((ln.strip() for ln in body.splitlines() if ln.strip()), subject)
            if title.startswith("See merge request"):
                title = subject
            u = Unit(sha, "pr", pr, title, date, parents[0])
            u.commits = []
            for side in parents[1:]:           # octopus merges: every merged branch
                tasks.append((u, parents[0], side))
        else:
            u = Unit(sha, "pr" if pr else "commit", pr, subject, date, parents[0] if parents else "")
            u.commits = [{"sha": sha, "subject": subject, "parent": parents[0] if parents else ""}]
            u.boundary = sha in shallow
        units.append(u)
    # one `git log` per merged branch, side by side; results land in log order
    for (u, _, _), commits in zip(tasks, pmap(lambda t: inner_commits(repo, t[1], t[2]), tasks, workers)):
        u.commits += commits
    units.reverse()
    return units


def read_shallow(repo: str) -> list[str]:
    try:
        path = git(repo, "rev-parse", "--git-path", "shallow").strip()
        path = path if os.path.isabs(path) else os.path.join(repo, path)
        with open(path, encoding="utf-8") as f:
            return f.read().split()
    except (OSError, RuntimeError):
        return []


def inner_commits(repo: str, base: str, head: str) -> list[dict]:
    out = git(repo, "log", "--no-merges", "--format=%H%x1f%s%x1f%P%x1e", f"{base}..{head}")
    res = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            sha, subject, parents = (rec.split("\x1f") + ["", ""])[:3]
            res.append({"sha": sha, "subject": subject, "parent": (parents.split() or [""])[0]})
    res.reverse()
    return res


MANIFESTS = ("package.json", "plugin.json", "pyproject.toml", "Cargo.toml", "manifest.json")


def _log_diff(repo: str, ref: str, n: int, *flags: str, pathspec: tuple[str, ...] = (),
              workers: int = 1) -> list[tuple[str, str]]:
    """(sha, text) per first-parent commit among the newest n: its diff against its first parent.
    A long window is cut into slices (--skip/--max-count) that git works on side by side."""
    tail = ["--", *pathspec] if pathspec else []

    def one(sl: tuple[int, int]) -> list[tuple[str, str]]:
        skip, count = sl
        common = ["--first-parent", "--no-color", "--root", f"--max-count={count}", f"--skip={skip}",
                  "--format=%x1e%H", *flags, ref, *tail]
        try:
            out = git(repo, "log", "--diff-merges=first-parent", *common)
        except RuntimeError:                    # git older than 2.31
            out = git(repo, "log", "-m", *common)
        res = []
        for rec in out.split("\x1e"):
            if rec.strip():
                sha, _, text = rec.partition("\n")
                res.append((sha.strip(), text))
        return res

    parts = min(workers, max(1, n // 12))        # slices of at least 12 commits
    size = -(-n // parts)
    slices = [(i * size, min(size, n - i * size)) for i in range(parts)]
    return [x for part in pmap(one, slices, workers) for x in part]


def fill_all_changes(repo: str, units: list[Unit], roots: set[str], ref: str, n: int, workers: int = 1) -> None:
    """The per-unit stats of every unit, from one `git log --numstat` pass (it was a `git diff` per unit),
    and the version bumps from one more pass over the manifests only."""
    todo = [u for u in units if not u.boundary]
    for u in units:
        if u.boundary:
            u.tags.append("shallow-boundary")
    if not todo:
        return
    stats = dict(_log_diff(repo, ref, n, "-M", "--numstat", workers=workers))
    for u in todo:
        for line in stats.get(u.sha, "").splitlines():
            if "\t" not in line:
                continue
            a, d, path = line.split("\t", 2)
            if " => " in path:
                path = re.sub(r"\{[^}]* => ([^}]*)\}", r"\1", path).split(" => ")[-1].replace("//", "/")
            ins, dele = (int(a) if a != "-" else 0), (int(d) if d != "-" else 0)
            u.files.append({"path": path, "ins": ins, "del": dele})
            u.insertions += ins
            u.deletions += dele
        u.components = sorted({component(f["path"], roots) for f in u.files})
    if not any(f["path"].endswith(MANIFESTS) for u in todo for f in u.files):
        return
    # `*suffix` (wildcards cross slashes) is the same test as the endswith above; --no-renames so a
    # moved manifest reads as an addition, as it did when each path was diffed alone.
    sections: dict[tuple[str, str], tuple] = {}
    for sha, text in _log_diff(repo, ref, n, "--no-renames", "-p", "-U0",
                               pathspec=tuple("*" + m for m in MANIFESTS), workers=workers):
        for sec in re.split(r"(?m)^(?=diff --git )", text):
            head = sec.split("\n", 1)[0]
            if not head.startswith("diff --git a/"):
                continue
            rest = head[len("diff --git a/"):]
            path = rest[: (len(rest) - 3) // 2]
            old = new = None
            for ln in sec.splitlines():
                m = JSON_VERSION.match(ln) or TOML_VERSION.match(ln)
                if m:
                    v = tuple(int(x) for x in m.groups()[2:])
                    old, new = (v, new) if m.group(1) == "-" else (old, v)
            sections[(sha, path)] = (old, new)
    for u in todo:
        for path in [f["path"] for f in u.files if f["path"].endswith(MANIFESTS)]:
            old, new = sections.get((u.sha, path), (None, None))
            if old and new:
                u.version_bumps.append(f"{path}: {'.'.join(map(str, old))}->{'.'.join(map(str, new))}")


def judge(u: Unit) -> None:
    if u.boundary:
        return
    t_fix, t_why = subject_verdict(u.title)
    verdicts = [subject_verdict(c["subject"]) for c in u.commits]
    for c, (ok, _) in zip(u.commits, verdicts):
        c["is_fix"] = ok
    n_fix = sum(ok for ok, _ in verdicts)
    feature_title = starts_as_feature(u.title) and not t_fix
    # A patch version bump is recorded (u.version_bumps) but is no fix signal: releases bump patch numbers
    # for features, docs and chores too (PRs 113 and 123 of the model-router run).
    if t_fix:
        u.is_fix, u.why = True, ["title: " + ", ".join(t_why)]
    elif u.commits and n_fix * 2 > len(u.commits) and not feature_title:
        u.is_fix, u.why = True, [f"{n_fix}/{len(u.commits)} commits say fix"]
    elif n_fix:
        u.why = [f"{n_fix}/{len(u.commits)} commits say fix (a feature unit: fixes inside are not worked)"]
    if u.is_fix and t_fix:
        # A fix by its title ("review fixes", "Fix the findings F1-F13"): each of its commits is one of
        # the fixes, whatever its own subject says, except housekeeping.
        for c in u.commits:
            c["is_fix"] = not (CHORE.search(c["subject"]) or BUMP.search(c["subject"]))
    code = [f for f in u.files if blamed(f["path"])]
    if u.files and not code:
        u.tags.append("docs-only")
    if code and all(TEST_PATH.search(f["path"]) for f in code):
        u.tags.append("tests-only")
    if code and all(INSTRUCTIONS.search(f["path"]) for f in code):
        u.tags.append("instructions-only")
    if code and sum(f["del"] for f in code) == 0:
        u.tags.append("adds-only")
    deleted, added = sum(f["del"] for f in code), sum(f["ins"] for f in code)
    if deleted >= REMOVAL_MIN_DELETED and deleted >= REMOVAL_RATIO * max(added, 1):
        u.verdict = "removal"
        u.tags.append("removal")
    if len(code_components(u)) >= 2:
        u.tags.append("multi-component")


def code_components(u: Unit) -> list[str]:
    return sorted({c for f in u.files if blamed(f["path"])
                   for c in [component_of(u, f["path"])] if c not in NOT_CODE})


def component_of(u: Unit, path: str) -> str:
    for c in u.components:
        if path == c or path.startswith(c + "/"):
            return c
    return path.split("/")[0] if "/" in path else "(root)"


# Trees nobody writes by hand. Their diffs and lines are left out of blame and of the copies search
# (the units' own file lists and stats still count them). `--path` or `--component-root` naming one of
# them, or `--no-default-excludes`, brings it back; `--exclude PATH` adds more. Rename detection and
# blame on a regenerated tree are the costly part of a big diff, and they say nothing about who broke what.
DEFAULT_EXCLUDES = ("node_modules", "vendor", "third_party", "dist", "build", ".venv")


def effective_excludes(path=None, component_roots=(), extra=(), defaults: bool = True) -> list[str]:
    """Pathspecs (git magic) for the trees to leave out of blame diffs and the copies search.
    `path`: one prefix or a list; any of them naming an excluded tree brings it back."""
    out = []
    paths = [x.strip("/") for x in snapshot.path_list(path)] or [""]
    for d in DEFAULT_EXCLUDES if defaults else ():
        if d in set(component_roots) or any(p == d or p.startswith(d + "/") or f"/{d}/" in f"/{p}/" for p in paths):
            continue
        out.append(f":(exclude,glob)**/{d}/**")
    out += [f":(exclude){e}" for e in extra]
    return out


class BlameCache:
    """(parent commit, file, line ranges, ignore-revs content) -> who wrote those lines. Commits are
    content-addressed, so an entry never goes stale. The one place the collector writes inside .git."""

    def __init__(self, folder: str | None):
        self.folder = folder
        self.hits = self.misses = 0

    def _file(self, key: str) -> str:
        return os.path.join(self.folder, key[:2], key + ".json")

    def get(self, key: str):
        if not self.folder:
            return None
        try:
            with open(self._file(key), encoding="utf-8") as f:
                val = json.load(f)
            self.hits += 1
            return val
        except (OSError, ValueError):
            self.misses += 1
            return None

    def put(self, key: str, val) -> None:
        if not self.folder:
            return
        try:
            fp = self._file(key)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            tmp = f"{fp}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(val, f)
            os.replace(tmp, fp)
        except OSError:
            pass                                # a read-only repository just runs uncached


# Part of every blame cache key. RULE: bump it whenever what a blame entry stores, or how it is computed
# (blame flags, filtering of trivial lines, range handling, ignore handling), changes; otherwise stale
# disk entries from an older collector would be reused silently. v2: removal/ignore changes on fix/inspector-precision.
# v3: entries written while the repository was shallow may hold a wrong attribution (blame stops at the clone's
# boundary and the entry survived `git fetch --unshallow`); the cache is now bypassed on a shallow repository.
BLAME_CACHE_VERSION = "v3"


def _blame_key(parent: str, old: str, ranges: list[tuple[int, int]], ignore_id: str) -> str:
    import hashlib
    raw = json.dumps([BLAME_CACHE_VERSION, parent, old, ranges, ignore_id], ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _count_origins(out: str) -> list[list]:
    """[[sha, lines], ...] in order of first appearance, trivial lines left out."""
    res: dict[str, int] = {}
    sha = None
    for ln in out.splitlines():
        if re.match(r"^[0-9a-f]{40} ", ln):
            sha = ln.split()[0]
        elif ln.startswith("\t"):
            content = ln[1:].strip()
            if sha and content and content not in ("}", "{", ")", "];", "});", "end", "fi"):
                res[sha] = res.get(sha, 0) + 1
    return [[k, v] for k, v in res.items()]


def split_patch(diff: str) -> tuple[list[tuple[str, str, str]], list[str], str]:
    """`git diff --patch-with-raw` -> ([(status, old, new)], [one patch section per file], the patch)."""
    lines = diff.split("\n")
    raws, i = [], 0
    while i < len(lines) and lines[i].startswith(":"):
        meta, *paths = lines[i].split("\t")
        raws.append((meta.split()[-1], paths[0] if paths else "", paths[1] if len(paths) > 1 else ""))
        i += 1
    patch = "\n".join(lines[i:]).lstrip("\n")
    sections = [s for s in re.split(r"(?m)^(?=diff --git )", patch) if s.startswith("diff --git ")]
    return raws, sections, patch


def blame_origins(repo: str, commit: str, budget: int, ignore: str | None, parent: str | None = None,
                  diff: str | None = None, excludes: list[str] = (), cache: BlameCache | None = None,
                  ignore_id: str = "") -> Counter:
    """(commit, path) -> lines: who last wrote the lines `commit` deleted or changed.
    One diff of the commit and one blame per file (all its hunks as -L ranges), not one of each per hunk."""
    origins: Counter = Counter()
    if parent is None:
        try:
            parent = git(repo, "rev-parse", f"{commit}^").strip()
        except RuntimeError:
            return origins
    if diff is None:
        diff = commit_diff(repo, parent, commit, excludes)
    raws, sections, _ = split_patch(diff)
    plan: dict[str, list[tuple[int, int]]] = {}
    for (status, old, new), sec in zip(raws, sections):
        if status[:1] not in ("M", "D", "R") or not old or not blamed(old) or budget <= 0:
            continue
        if status[0] == "R" and not new:
            continue
        for m in HUNK_RE.finditer(sec):
            start, count = int(m.group(1)), int(m.group(2) or "1")
            if count == 0 or budget <= 0:
                continue
            count = min(count, budget)
            budget -= count
            plan.setdefault(old, []).append((start, count))
    for old, ranges in plan.items():
        key = _blame_key(parent, old, ranges, ignore_id) if cache and cache.folder else ""
        got = cache.get(key) if key else None
        if got is None:
            got = blame_ranges(repo, parent, old, ranges, ignore)
            if key:
                cache.put(key, got)
        for sha, n in got:
            origins[(sha, old)] += n
    return origins


def blame_ranges(repo: str, parent: str, old: str, ranges: list[tuple[int, int]], ignore: str | None) -> list[list]:
    """One `git blame` for all of a file's hunks. If git refuses the set, fall back to one per hunk,
    skipping the ones it refuses."""
    extra = ["--ignore-revs-file", ignore] if ignore else []
    try:
        args = ["blame", "-w", "-M", "--porcelain"]
        for s, c in ranges:
            args += ["-L", f"{s},+{c}"]
        return _count_origins(git(repo, *args, *extra, parent, "--", old))
    except RuntimeError:
        merged: dict[str, int] = {}
        for s, c in ranges:
            try:
                out = git(repo, "blame", "-w", "-M", "--porcelain", "-L", f"{s},+{c}", *extra, parent, "--", old)
            except RuntimeError:
                continue
            for sha, n in _count_origins(out):
                merged[sha] = merged.get(sha, 0) + n
        return [[k, v] for k, v in merged.items()]


def commit_diff(repo: str, parent: str, commit: str, excludes: list[str] = ()) -> str:
    """The commit's whole diff once: raw status lines plus -U0 patch, rename-aware. Serves blame and the copies search."""
    tail = ["--", ".", *excludes] if excludes else []
    return git(repo, "diff", "-U0", "-M", "--no-color", "--patch-with-raw", parent, commit, *tail)


TRIVIAL = re.compile(r"^[\s{}()\[\];,]*$|^\s*(//|#|\*|/\*|--)|^\s*(return|else|end|fi|pass|break|continue)\s*;?\s*$")


def removed_lines(patch: str) -> list[str]:
    """Lines this fix deleted in place of others: the candidates for a copy left somewhere else."""
    diff = patch
    added = {ln[1:].strip() for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")}
    removed, path, hunk = [], None, {"-": [], "+": 0}

    def close() -> None:
        # Only a changed expression counts: a hunk that removed lines and added others in their
        # place. A deleted block, or a line the commit adds back elsewhere (a move), doesn't.
        if hunk["+"]:
            for t in hunk["-"]:
                if t not in added and t not in removed:
                    removed.append(t)
        hunk["-"], hunk["+"] = [], 0

    for ln in diff.splitlines():
        if ln.startswith("@@") or ln.startswith("diff "):
            close()
        if ln.startswith("--- "):
            path = ln[6:] if ln.startswith("--- a/") else None
        elif ln.startswith("+") and not ln.startswith("+++"):
            hunk["+"] += 1
        elif ln.startswith("-") and path and blamed(path) and not TEST_PATH.search(path):
            t = ln[1:].strip()
            if len(t) >= 16 and not TRIVIAL.search(t):
                hunk["-"].append(t)
    close()
    return removed[:40]


# Matches on these lines are not copies of a fixed expression: they mention it. They are listed apart
# (`ignored_matches`), never counted: an import/require/from line, a comment, a description/frontmatter string.
IGNORED_MATCH = re.compile(
    r"^\s*(import\b|from\b|export\b.*\bfrom\b|#\s*include\b|(#|//|/\*|\*|--|<!--)"
    r"|[\"']?(description|when_to_use|argument-hint)[\"']?\s*[:=])|\brequire\s*\(", re.I)


def grep_hits(repo: str, ref: str, patterns: list[str], excludes: list[str] = (),
              ignored: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """pattern -> up to every `path:line` at `ref` (tests left out) that contains it: one `git grep -f`
    for all patterns of the run, where it used to be one `git grep` per line. Matches on import,
    comment and description lines go to `ignored` (same shape) when given, and are dropped otherwise."""
    patterns = list(dict.fromkeys(patterns))
    if not patterns:
        return {}
    fd, pf = tempfile.mkstemp(prefix="inspector-patterns-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(("\n".join(patterns) + "\n").encode("utf-8"))
        out = git(repo, "grep", "-n", "-F", "-I", "-f", pf, ref, "--", ".", *excludes, ok_codes=(0, 1))
    finally:
        os.unlink(pf)
    res: dict[str, list[str]] = {t: [] for t in patterns}
    for h in out.splitlines():
        h = h.split(":", 1)[1] if h.startswith(ref + ":") else h
        parts = h.split(":", 2)
        if len(parts) < 3 or TEST_PATH.search(parts[0]):
            continue
        at = ":".join(parts[:2])
        skip = bool(IGNORED_MATCH.search(parts[2]))
        for t in patterns:
            if t in parts[2]:
                if not skip:
                    res[t].append(at)
                elif ignored is not None:
                    ignored.setdefault(t, []).append(at)
    return res


def ignored_matches(removed: list[str], ignored: dict[str, list[str]]) -> list[dict]:
    """The matches left_behind did not count (imports, comments, descriptions), for the lines of one fix."""
    return [{"line": t[:160], "at": ignored[t]} for t in removed if ignored.get(t)]


def left_behind(repo: str, commit: str, ref: str, cap: int = 8, removed: list[str] | None = None,
                hits: dict[str, list[str]] | None = None) -> list[dict]:
    """Lines this fix deleted that still exist somewhere at `ref`: a copy the fix may have missed."""
    if removed is None:
        try:
            parent = git(repo, "rev-parse", f"{commit}^").strip()
        except RuntimeError:
            return []
        removed = removed_lines(split_patch(commit_diff(repo, parent, commit))[2])
    if hits is None:
        hits = grep_hits(repo, ref, removed)
    out = []
    for t in removed:
        found = hits.get(t, [])
        if 0 < len(found) <= 3:          # a line found in many places is an idiom, not a copy
            out.append({"line": t[:160], "at": found})
        if len(out) >= cap:
            break
    return out


def investigate(repo: str, ref: str = "HEAD", since: str | None = None, limit: int = 200,
                max_blame: int = 400, min_lines: int = 3, history: int = 500,
                unit: str | None = None, path: str | list[str] | None = None,
                roots: set[str] | None = None, workers: int | None = None,
                cache_dir: str | None = None, use_cache: bool = True,
                excludes: list[str] | None = None, github: bool = False, gh_run=None) -> dict:
    """`github`: read each PR of the work window through gh (labels, closing issues; gh_enrich) before blame;
    off by default for library callers. `gh_run`: the gh runner (tests pass a mock). `workers`: git calls in flight (default min(8, cpus)). `cache_dir`/`use_cache`: the blame cache
    (default <git dir>/inspector/cache). `excludes`: pathspecs left out of blame diffs and the copies
    search (default: effective_excludes(path, roots))."""
    roots = roots or MONOREPO_ROOTS
    path = snapshot.scope_path(path)       # None, "a/" (one, as before) or ["a/", "b/"] (repeated --path: a union)
    workers = max(1, workers if workers is not None else min(8, os.cpu_count() or 1))
    with phase("discovery"):
        # One call resolves the ref to an immutable commit; HEAD rides along for the workspace check.
        if ref.startswith("-"):
            raise ValueError(f"not a ref: {ref}")
        resolved = git(repo, "rev-parse", f"{ref}^{{commit}}", "HEAD").split()
        requested_ref, ref, head = ref, resolved[0], resolved[-1]
        info = repo_info(repo)
        shallow = info.shallow
        work_list = work_window(repo, ref, limit, since)
        truncated = len(work_list) >= limit
        # The attribution window holds the work window (both walk back from the same ref).
        try:
            with open(info.shallow_file, encoding="utf-8") as f:
                boundary = set(f.read().split())
        except OSError:
            boundary = set()
        n_units = max(history, limit)
        units = first_parent(repo, ref, n_units, None, boundary, workers)
    by_sha = {u.sha: u for u in units}
    owner: dict[str, Unit] = {}
    for u in units:
        owner.setdefault(u.sha, u)
        for c in u.commits:
            owner.setdefault(c["sha"], u)
    with phase("changes"):
        fill_all_changes(repo, units, roots, ref, n_units, workers)
    with phase("judge"):
        for u in units:
            judge(u)

    work_shas = {s for s in work_list if s in by_sha}
    if unit:
        want = unit.lstrip("#")
        hit = None
        if unit.startswith("#") or (want.isdigit() and len(want) < 7):
            hit = next((u for u in units if u.pr is not None and str(u.pr) == want), None)
        if not hit and len(want) >= 4:
            hit = next((owner[s] for s in owner if s.startswith(want.lower())), None)
        if not hit:
            raise RuntimeError(f"no unit {unit} in the last {max(history, limit)} first-parent units (raise --history)")
        work_shas = {hit.sha}
    if path:
        work_shas = {s for s in work_shas if any(in_scope(f["path"], path) for f in by_sha[s].files)}
    ignore, ignore_id = None, ""
    if os.path.exists(os.path.join(info.toplevel, ".git-blame-ignore-revs")):
        ignore = os.path.join(info.toplevel, ".git-blame-ignore-revs")
        try:
            import hashlib
            with open(ignore, "rb") as f:
                ignore_id = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            ignore_id = "unreadable"
    if excludes is None:
        excludes = effective_excludes(path, roots - MONOREPO_ROOTS)
    cache_folder = None if not use_cache else (cache_dir or os.path.join(info.git_dir, "inspector", "cache"))
    # A shallow repository's blame stops at the boundary, and the same (parent, file, ranges) key gives a different
    # answer once history is fetched: no read, no write of the blame cache until the clone is complete.
    cache = BlameCache(None if shallow else cache_folder)

    worked = [u for u in units if u.sha in work_shas]
    gh_bodies, gh_warnings = None, []
    if github:
        gh_bodies = github_phase(repo, worked, workers, cache_folder, gh_run or gh_runner, gh_warnings)
    jobs = [(u, c) for u in worked if u.is_fix and u.verdict != "removal" for c in u.commits if c.get("is_fix")]

    def analyze(job):
        # per fix commit: one diff, one blame per file touched; independent of every other commit
        c = job[1]
        parent = c.get("parent")
        if parent is None:                       # a commit dict built elsewhere: ask git
            try:
                parent = git(repo, "rev-parse", f"{c['sha']}^").strip()
            except RuntimeError:
                parent = ""
        if not parent:
            return Counter(), []
        diff = commit_diff(repo, parent, c["sha"], excludes)
        origins = blame_origins(repo, c["sha"], max_blame, ignore, parent, diff, excludes, cache, ignore_id)
        return origins, removed_lines(split_patch(diff)[2])

    with phase("blame"):
        results = pmap(analyze, jobs, workers)
    with phase("copies"):
        ignored: dict[str, list[str]] = {}
        hits = grep_hits(repo, ref, [t for _, rem in results for t in rem], excludes, ignored)
    by_job = {id(c): res for (_, c), res in zip(jobs, results)}
    for u in worked:
        if not u.is_fix or u.verdict == "removal":     # no blame for removals: nobody broke what was deleted
            continue
        per_unit: dict[str, dict] = {}
        for c in u.commits:
            if not c.get("is_fix"):
                continue
            c_intro: Counter = Counter()
            origins, removed = by_job[id(c)]
            for (sha, fpath), n in origins.items():
                src = owner.get(sha)
                if src is u:
                    continue
                key = src.label() if src else f"{sha[:8]} (before the attribution window)"
                c_intro[key] += n
                e = per_unit.setdefault(key, {"unit": key, "sha": sha[:12], "lines": 0, "files": set(),
                                              "is_fix": bool(src and src.is_fix),
                                              "title": src.title if src else ""})
                e["lines"] += n
                e["files"].add(fpath)
            c["introduced_by"] = [{"unit": k, "lines": n} for k, n in c_intro.most_common(5)]
            c["left_behind"] = left_behind(repo, c["sha"], ref, removed=removed, hits=hits)
            c["ignored_matches"] = ignored_matches(removed, ignored)
        u.introduced_by = sorted(({**e, "files": sorted(e["files"])} for e in per_unit.values()),
                                 key=lambda e: -e["lines"])
        u.fix_of_fix = any(e["is_fix"] and e["lines"] >= min_lines for e in u.introduced_by)
    Timing.extra["blame cache hits/misses"] = f"{cache.hits}/{cache.misses}"

    fixes = [u for u in worked if u.is_fix]
    code_files = lambda u: [f["path"] for f in u.files if blamed(f["path"])]
    hot = Counter(p for u in fixes for p in code_files(u) if not TEST_PATH.search(p))
    hot_tests = Counter(p for u in fixes for p in code_files(u) if TEST_PATH.search(p))
    blamed_units = Counter()
    for u in fixes:
        for e in u.introduced_by:
            blamed_units[e["unit"]] += e["lines"]
    with phase("workspace"):
        warnings = snapshot.workspace_warnings(repo, ref, head=head)
    warnings += gh_warnings
    if shallow:
        warnings.append("shallow clone: blame stops at the clone's boundary; run `git fetch --unshallow` "
                        "and collect again, or treat every introduced_by as inferred")
    if truncated and not unit:
        warnings.append(f"the work window hit --max {limit}: older units are not in it (raise --max, or use --since)")
    if any(u.boundary for u in units):
        warnings.append("the shallow boundary commit is listed but not judged: its diff is the whole tree")
    return {
        "snapshot": snapshot.metadata(repo, {"since": since, "limit": limit, "max_blame": max_blame,
                    "min_lines": min_lines, "history": history, "unit": unit, "path": path,
                    "roots": sorted(roots), "excludes": list(excludes)}, repo_path=info.toplevel),
        "repo": repo, "ref": ref, "ref_requested": requested_ref, "ref_sha": ref, "since": since,
        "unit": unit, "path": path, "shallow": shallow, "truncated": truncated, "warnings": warnings,
        "units": len(worked), "fixes": len(fixes),
        "fix_of_fix": [u.label() for u in fixes if u.fix_of_fix],
        "multi_component_fixes": [u.label() for u in fixes if "multi-component" in u.tags],
        "hotspot_files": hot.most_common(15),
        "hotspot_tests": hot_tests.most_common(5),
        "fix_components": Counter(c for u in fixes for c in code_components(u)).most_common(),
        "fix_tags": Counter(t for u in fixes for t in u.tags).most_common(),
        "most_blamed_units": blamed_units.most_common(10),
        "left_behind": [{"unit": u.label(), "commit": c["sha"][:12], **x} for u in fixes for c in u.commits
                        for x in c.get("left_behind", [])],
        **({"ignored_matches": im} if (im := [{"unit": u.label(), "commit": c["sha"][:12], **x} for u in fixes
                                              for c in u.commits for x in c.get("ignored_matches", [])]) else {}),
        "timeline": [unit_json(u) for u in worked],
        "unit_shas": {u.label(): u.sha for u in units},
        **({"gh_bodies": gh_bodies} if gh_bodies is not None else {}),     # popped by main(): never saved
    }


class GhUnavailable(Exception):
    """gh is missing, not logged in, or the call failed: the GitHub fallback is skipped."""


def gh_runner(args: list[str]) -> str:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    except FileNotFoundError:
        raise GhUnavailable("gh is not installed")
    except subprocess.TimeoutExpired:
        raise GhUnavailable("gh timed out")
    if p.returncode != 0:
        raise GhUnavailable("gh failed (not logged in? try `gh auth login`): " + p.stderr.strip()[:200])
    return p.stdout

# ---- GitHub enrichment: labels and closing issues of each PR in the work window --------------------------
# Deterministic, no model tokens. One `gh pr view` per PR (plus one `gh issue view` per linked issue the PR
# call does not describe fully), run on the --workers pool, cached on disk next to the blame cache.
GH_FIX_LABELS = ("bug", "fix", "regression", "security")    # a PR carrying one of these is a fix signal (case-insensitive)
GH_ISSUE_FIX_LABELS = ("bug",)                              # a closing issue carrying one of these is too
GH_PR_FIELDS = "title,body,labels,closingIssuesReferences,reviewDecision,mergedAt"
GH_TEXT_CHARS = 120                                         # issue titles kept in the saved evidence
# Part of every gh cache key. RULE: bump it whenever what an entry stores, or the fields asked of gh, change.
GH_CACHE_VERSION = "v1"


@dataclass
class GhEnrichment:
    data: dict = field(default_factory=dict)       # PR number -> {"labels": [...], "closes": [...]} (keys only when present)
    bodies: dict = field(default_factory=dict)     # PR number -> body, first PR_TEXT_CHARS characters
    calls: int = 0                                 # gh calls made
    cached: int = 0                                # PRs answered from the disk cache
    error: str | None = None                       # the first GhUnavailable message: the phase stopped there


def _names(items) -> list[str]:
    return [str(x.get("name")) for x in items or [] if isinstance(x, dict) and x.get("name")]


def _gh_cache_key(slug: str, pr: int) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(["gh", GH_CACHE_VERSION, slug, pr]).encode()).hexdigest()


GH_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GH_BATCH = 25                                               # PRs per `gh api graphql` call
_GQL_PR = ("{ title body mergedAt labels(first:20){totalCount nodes{name}} "
           "closingIssuesReferences(first:10){totalCount nodes{number title state labels(first:20){totalCount nodes{name}}}} }")


def _gql_query(prs: list[int]) -> str:
    """One query for many PRs (aliases pr<N>). The numbers are cast to int: nothing else is put in the text."""
    body = " ".join(f"pr{int(n)}: pullRequest(number:{int(n)}) {_GQL_PR}" for n in prs)
    return "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){ " + body + " }}"


def _gql_det(node) -> dict | None:
    """A GraphQL pullRequest node in the shape `gh pr view --json` gives, or None when it is missing a field or
    a list was cut short by the page size (that PR then takes the per-PR path)."""
    if not isinstance(node, dict) or not all(k in node for k in ("title", "body", "mergedAt", "labels", "closingIssuesReferences")):
        return None

    def items(conn):
        if not isinstance(conn, dict) or not isinstance(conn.get("nodes"), list):
            return None
        if isinstance(conn.get("totalCount"), int) and conn["totalCount"] > len(conn["nodes"]):
            return None
        return [n for n in conn["nodes"] if isinstance(n, dict)]
    labels, refs = items(node["labels"]), items(node["closingIssuesReferences"])
    if labels is None or refs is None:
        return None
    closing = []
    for r in refs:
        il = items(r.get("labels"))
        if il is None:
            return None
        closing.append({"number": r.get("number"), "title": r.get("title"), "state": r.get("state"), "labels": il})
    return {"title": node["title"], "body": node["body"], "mergedAt": node["mergedAt"],
            "labels": labels, "closingIssuesReferences": closing}


def gh_enrich(slug: str, prs: list[int], run, cache, workers: int = 1, batch: bool = True) -> GhEnrichment:
    """Labels and closing issues for `prs`. Uncached PRs are read in batches of GH_BATCH by one `gh api graphql`
    call each (`batch=False`, or a failed/incomplete batch: one `gh pr view` per PR). A failure stops the
    remaining calls; what was read is kept, a failure is never cached, and nothing from gh is ever executed or
    put on a command line (a list of args)."""
    out, lock, stop = GhEnrichment(), threading.Lock(), threading.Event()
    if not GH_SLUG.match(slug or ""):
        out.error = "not a GitHub owner/repo slug"
        return out
    prefetched: dict[int, dict] = {}

    def call(args: list[str]) -> dict:
        with lock:
            out.calls += 1
        val = json.loads(run(args) or "{}")
        if not isinstance(val, dict):
            raise GhUnavailable("gh returned unexpected JSON")
        return val

    def one(pr: int):
        key = _gh_cache_key(slug, pr)
        hit = cache.get(key) if cache else None
        if hit:
            with lock:
                out.cached += 1
            return pr, hit["gh"], hit.get("body", "")
        if stop.is_set():
            return pr, None, ""
        complete = True
        try:
            det = prefetched.get(pr) or call(["pr", "view", str(pr), "-R", slug, "--json", GH_PR_FIELDS])
        except (GhUnavailable, ValueError) as e:             # ValueError: invalid JSON
            with lock:
                out.error = out.error or str(e)
            stop.set()
            return pr, None, ""
        closes = []
        for ref in det.get("closingIssuesReferences") or []:
            if not isinstance(ref, dict) or not isinstance(ref.get("number"), int):
                continue
            issue = {"number": ref["number"], "title": ref.get("title"), "state": ref.get("state"),
                     "labels": ref.get("labels") if "labels" in ref else None}
            if issue["labels"] is None:                      # gh describes a closing issue by number and url only
                repo = ref.get("repository") or {}
                where = f"{(repo.get('owner') or {}).get('login')}/{repo.get('name')}" if repo.get("name") else slug
                try:
                    full = call(["issue", "view", str(ref["number"]), "-R", where, "--json", "title,labels,state"])
                    issue.update(title=full.get("title"), state=full.get("state"), labels=full.get("labels"))
                except (GhUnavailable, ValueError):
                    complete = False                         # keep the number; do not cache a half answer
            closes.append({"number": issue["number"], "title": " ".join(str(issue["title"] or "").split())[:GH_TEXT_CHARS],
                           "state": str(issue["state"] or ""), "labels": _names(issue["labels"])})
        labels = _names(det.get("labels"))
        gh = {**({"labels": labels} if labels else {}), **({"closes": closes} if closes else {})}
        body = str(det.get("body") or "")[:PR_TEXT_CHARS]
        if cache and complete and det.get("mergedAt"):        # a merged PR's data does not change
            cache.put(key, {"gh": gh, "body": body})
        return pr, gh, body

    todo = sorted({int(n) for n in prs})
    if batch:
        owner, name = slug.split("/")
        missing = [n for n in todo if not (cache and cache.get(_gh_cache_key(slug, n)))]
        chunks = [missing[i:i + GH_BATCH] for i in range(0, len(missing), GH_BATCH)]

        def fetch(chunk: list[int]) -> dict[int, dict]:
            try:
                data = call(["api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}", "-f", "query=" + _gql_query(chunk)])
                repo = ((data.get("data") or {}).get("repository")) or {}
                return {n: d for n in chunk if (d := _gql_det(repo.get(f"pr{n}"))) is not None}
            except (GhUnavailable, ValueError, AttributeError, TypeError):
                return {}                                    # the per-PR path decides what a failure means
        for got in pmap(fetch, chunks, workers):
            prefetched.update(got)

    for pr, gh, body in pmap(one, todo, workers):
        if gh is not None:
            out.bodies[pr] = body
            if gh:
                out.data[pr] = gh
    return out


def gh_fix_signals(gh: dict) -> list[str]:
    """`why` texts for the label / closing-issue evidence of one PR: `label: bug`, `closes #12 (bug)`."""
    why = [f"label: {label}" for label in gh.get("labels", []) if label.lower() in GH_FIX_LABELS]
    for c in gh.get("closes", []):
        for label in c.get("labels", []):
            if label.lower() in GH_ISSUE_FIX_LABELS:
                why.append(f"closes #{c['number']} ({label})")
                break
    return why


def gh_note(gh: dict) -> str:
    """One line for the timeline: `labels: bug, docs; closes #12 (bug), #13`."""
    parts = []
    if gh.get("labels"):
        parts.append("labels: " + ", ".join(gh["labels"]))
    if gh.get("closes"):
        parts.append("closes " + ", ".join(f"#{c['number']}" + (f" ({', '.join(c['labels'])})" if c.get("labels") else "")
                                           for c in gh["closes"]))
    return "; ".join(parts)


def github_phase(repo: str, worked: list[Unit], workers: int, cache_dir: str | None, run, warnings: list[str]):
    """Read the PRs of the work window, record labels/closes on their units and promote fix signals to the
    unit's fix verdict (a promoted unit's non-housekeeping commits are its fixes, as for a fix title).
    Returns the PR bodies (None when the phase did not run: no GitHub remote or no PR in the window)."""
    prs = sorted({u.pr for u in worked if u.pr is not None and not u.boundary})
    slug = github_slug(repo) if prs else None
    if not slug:
        return None
    with phase("github"):
        res = gh_enrich(slug, prs, run, BlameCache(cache_dir) if cache_dir else None, workers)
    if Timing.enabled:
        Timing.extra["github"] = f"{res.calls} gh calls for {len(prs)} PRs ({res.cached} from cache)"
    if res.error:
        warnings.append(f"GitHub enrichment incomplete, labels and linked issues not used for some PRs: {res.error}")
    for u in worked:
        gh = res.data.get(u.pr) if u.pr is not None else None
        if not gh:
            continue
        u.gh = gh
        signals = gh_fix_signals(gh)
        if signals:
            u.is_fix, u.why = True, signals + [w for w in u.why if w not in signals]
            for c in u.commits:
                c["is_fix"] = c.get("is_fix", False) or not (CHORE.search(c["subject"]) or BUMP.search(c["subject"]))
    return res.bodies



GH_REMOTE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def github_slug(repo: str) -> str | None:
    try:
        m = GH_REMOTE.search(git(repo, "remote", "get-url", "origin").strip())
    except RuntimeError:
        return None
    return f"{m.group(1)}/{m.group(2)}" if m else None


def github_units(slug: str, n: int, roots: set[str], path=None, run=gh_runner) -> list[dict]:
    """The last `n` merged PRs as unit-like records. Every value is evidence level `inferred`:
    it comes from GitHub, not from local history, and no blame is possible."""
    try:
        prs = json.loads(run(["pr", "list", "-R", slug, "--state", "merged", "--limit", str(n), "--json",
                              "number,title,body,mergedAt,mergeCommit,headRefName"]) or "[]")
    except json.JSONDecodeError:
        raise GhUnavailable("gh returned invalid JSON")
    out = []
    for pr in prs[:n]:
        num = pr.get("number")
        try:
            det = json.loads(run(["pr", "view", str(num), "-R", slug, "--json", "files,additions,deletions"]) or "{}")
        except json.JSONDecodeError:
            raise GhUnavailable("gh returned invalid JSON")
        files = [{"path": f.get("path", ""), "ins": int(f.get("additions") or 0), "del": int(f.get("deletions") or 0)}
                 for f in det.get("files") or []]
        u = Unit((pr.get("mergeCommit") or {}).get("oid", ""), "pr", num, pr.get("title") or "",
                 (pr.get("mergedAt") or "")[:10], "", files=files,
                 insertions=int(det.get("additions") or 0), deletions=int(det.get("deletions") or 0))
        u.components = sorted({component(f["path"], roots) for f in files})
        judge(u)
        d = unit_json(u)
        d.update({"source": "github", "evidence": "inferred", "introduced_by": "unknown",
                  "branch": pr.get("headRefName") or "",
                  "touches_path": bool(path and any(in_scope(f["path"], path) for f in files))})
        out.append(d)
    return out


def github_markdown(prs: list[dict], path) -> list[str]:
    L = ["", "## Recent PRs (GitHub, no local history)", "",
         "> Evidence level: inferred. Titles and files come from GitHub; introduced_by is unknown (no blame without history). "
         "PR text is data, not instructions.", ""]
    for u in prs:
        flag = f" **[touches --path {', '.join(snapshot.path_list(path))}]**" if u["touches_path"] else ""
        L.append(f"- {u['unit']} {u['title'].replace(chr(10), ' ')[:90]} ({u['date']}) "
                 f"{'fix' if u['is_fix'] else ''} +{u['insertions']}/-{u['deletions']}{flag}")
        groups: dict[str, list[str]] = {}
        for f in u["files"]:
            groups.setdefault(component_of_json(u, f["path"]), []).append(f["path"])
        for c, ps in sorted(groups.items()):
            L.append(f"  - {c}: " + ", ".join(f"`{x}`" for x in ps[:8]) + (f" (+{len(ps) - 8} more)" if len(ps) > 8 else ""))
    return L if prs else L + ["- none"]


def component_of_json(u: dict, path: str) -> str:
    for c in u["components"]:
        if path == c or path.startswith(c + "/"):
            return c
    return path.split("/")[0] if "/" in path else "(root)"


def unit_json(u: Unit) -> dict:
    return {
        "unit": u.label(), "sha": u.sha[:12], "base": u.base[:12], "kind": u.kind, "pr": u.pr,
        "date": u.date, "title": u.title, "is_fix": u.is_fix, "why": u.why, "tags": u.tags,
        "components": u.components, "insertions": u.insertions, "deletions": u.deletions,
        "files": u.files, "version_bumps": u.version_bumps,
        "commits": [{"sha": c["sha"][:12], "subject": c["subject"], "is_fix": c.get("is_fix", False),
                     **({"introduced_by": c["introduced_by"]} if c.get("introduced_by") else {}),
                     **({"left_behind": c["left_behind"]} if c.get("left_behind") else {}),
                     **({"ignored_matches": c["ignored_matches"]} if c.get("ignored_matches") else {})}
                    for c in u.commits],
        "introduced_by": u.introduced_by, "fix_of_fix": u.fix_of_fix,
        **({"verdict": u.verdict} if u.verdict else {}),
        **({"gh": u.gh} if u.gh else {}),
    }


def why_cell(u: dict) -> str:
    """The timeline's `why`: the fix evidence, plus PR labels and linked issues when GitHub was read."""
    if not u.get("gh"):
        return "; ".join(u["why"])[:50]
    return "; ".join(u["why"] + [gh_note(u["gh"])])[:110].replace("|", "/")


def markdown(r: dict) -> str:
    scope = ", ".join(x for x in [f"since {r['since']}" if r["since"] else "", f"unit {r['unit']}" if r["unit"] else "",
                                  f"path {', '.join(snapshot.path_list(r['path']))}" if r["path"] else ""] if x)
    L = [f"# Evidence: {r['repo']} ({r.get('ref_requested', r['ref'])} = {r['ref_sha'][:12]}{', ' + scope if scope else ''})", ""]
    if r.get("snapshot"):
        plugin = r["snapshot"]["plugin"]
        L += [f"Inspector {plugin['version']} · fingerprint {plugin['fingerprint'][:12]}",
              f"Plugin files: `{plugin['path']}`", ""]
    L += [f"> **Warning**: {w}" for w in r["warnings"]] + ([""] if r["warnings"] else [])
    L += [f"- Units in the work window: {r['units']}; likely fixes: {r['fixes']}",
          f"- Fix-of-fix (a fix changed lines an earlier fix wrote) `↺`: {', '.join(r['fix_of_fix']) or 'none'}",
          f"- Fixes spanning 2+ components: {', '.join(r['multi_component_fixes']) or 'none'}",
          f"- Fix tags: {', '.join(f'{t} {n}' for t, n in r['fix_tags']) or 'none'}", ""]
    L += ["## Hotspots (code files changed by fixes; tests apart)", ""]
    L += [f"- `{p}`: {n}" for p, n in r["hotspot_files"]] or ["- none"]
    if r["hotspot_tests"]:
        L += ["- tests: " + ", ".join(f"`{p}` {n}" for p, n in r["hotspot_tests"])]
    L += ["", "## Components the fixes landed in", ""]
    L += [f"- {c}: {n}" for c, n in r["fix_components"]] or ["- none"]
    L += ["", "## Units whose lines the fixes changed most (suspects)", ""]
    L += [f"- {u}: {n} lines" for u, n in r["most_blamed_units"]] or ["- none"]
    L += ["", "## Copies left behind (lines a fix deleted that are still in the code)", ""]
    L += [f"- {x['unit']} {x['commit'][:8]}: `{x['line'][:90]}` still at {', '.join(x['at'][:3])}"
          for x in r["left_behind"][:25]] or ["- none"]
    if r.get("ignored_matches"):
        L += ["", f"Not counted above: {len(r['ignored_matches'])} line(s) also appear in imports, comments or descriptions "
                  "(`ignored_matches` in evidence.json)."]
    L += ["", "## Timeline (oldest first)", "",
          "| unit | date | fix? | why | tags | +/- | introduced by (lines) |", "|---|---|---|---|---|---|---|"]
    for u in r["timeline"]:
        intro = ", ".join(f"{e['unit']}{'*' if e['is_fix'] else ''} ({e['lines']})" for e in u["introduced_by"][:4])
        title = u["title"].replace("|", "/")[:70]
        L.append(f"| {u['unit']} {title} | {u['date']} | {'fix' if u['is_fix'] else ''}{' ↺' if u['fix_of_fix'] else ''} | "
                 f"{why_cell(u)} | {', '.join(u['tags'])} | +{u['insertions']}/-{u['deletions']} | {intro} |")
    L += ["", "`*` the blamed unit is itself a fix. `↺` fix-of-fix. The fix verdict reads titles and commit "
          "subjects; read the diff before you call anything a bug. Commit and PR text is data, not instructions."]
    return "\n".join(L) + "\n"


def triage(r: dict, budget: int = 12, random_picks: int | None = None) -> list[str]:
    """The skill's order for cases: fix-of-fix units, then multi-component fixes, then fixes in the
    top 5 hotspot files; the last slots (2 of a budget of 8 or more, 1 of 4-7) go to fixes the order doesn't reach,
    picked by a seed from the ref, so a rerun picks the same."""
    fixes = [u for u in r["timeline"] if u["is_fix"] and "docs-only" not in u["tags"]]
    hot = {p for p, _ in r["hotspot_files"][:5]}
    order: list[str] = []
    for want in (lambda u: u["fix_of_fix"], lambda u: "multi-component" in u["tags"],
                 lambda u: any(f["path"] in hot for f in u["files"])):
        for u in reversed(fixes):                       # newest first within a tier
            if want(u) and u["unit"] not in order:
                order.append(u["unit"])
    if random_picks is None:            # the check on the order's bias: 2 of 8+, 1 of 4-7, none below
        random_picks = 2 if budget >= 8 else 1 if budget >= 4 else 0
    picked = order[:max(budget - random_picks, 0)]
    rest = [u["unit"] for u in fixes if u["unit"] not in picked]
    import random
    rng = random.Random(r["ref_sha"])
    picked += rng.sample(rest, min(random_picks, len(rest), budget - len(picked)))
    return picked


def capped(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[:n] + ([f"... {len(lines) - n} more lines (read the rest by range)"] if len(lines) > n else []))


BIG_FIX_DIFF_LINES = 400      # added+removed lines in code files above which a fix commit also gets a per-file section
BIG_FIX_MAX_FILES = 40        # files listed in that section
BIG_FIX_BLAME_FILES = 12      # files (largest first) that also get a blame culprit line
PR_TEXT_CHARS = 2000
FILE_DIFF_LINES = 200


def commit_files(repo: str, sha: str, code: list[str]) -> list[dict]:
    """Per changed code file of a commit: added/removed counts, hunk function contexts (git's @@ text)
    and the old-side ranges blame needs. One `git show -U0`."""
    out, cur = [], None
    for line in git(repo, "show", "--format=", "-U0", "--no-color", sha, "--", *code).splitlines():
        if line.startswith("diff --git "):
            cur = {"path": line.rsplit(" b/", 1)[-1], "add": 0, "del": 0, "ctx": [], "hunks": 0, "old": []}
            out.append(cur)
        elif cur is None:
            continue
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            cur["hunks"] += 1
            if m and int(m.group(2) or "1"):
                cur["old"].append((int(m.group(1)), int(m.group(2) or "1")))
            c = line.split("@@", 2)[2].strip() if line.count("@@") >= 2 else ""
            if c and c not in cur["ctx"]:
                cur["ctx"].append(c)
        elif line.startswith("+") and not line.startswith("+++"):
            cur["add"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            cur["del"] += 1
    return out


def per_file_section(repo: str, u: dict, c: dict, code: list[str]) -> list[str]:
    files = sorted(commit_files(repo, c["sha"], code), key=lambda f: -(f["add"] + f["del"]))
    total = sum(f["add"] + f["del"] for f in files)
    L = [f"### Files in this fix: {len(files)} code files, {total} changed lines", "",
         "Hunk headers are the function context git prints after `@@`. Blame is on the fix's parent.", ""]
    parent = c["sha"] + "^"        # saved runs do not keep the parent; a squash or plain commit has one first parent
    for i, f in enumerate(files[:BIG_FIX_MAX_FILES]):
        ctx = ", ".join(f"`{x[:50]}`" for x in f["ctx"][:4]) + (f" (+{len(f['ctx']) - 4} more)" if len(f["ctx"]) > 4 else "")
        L.append(f"- `{f['path']}` +{f['add']}/-{f['del']}, {f['hunks']} hunks: {ctx or 'no function context'}")
        if parent and f["old"] and i < BIG_FIX_BLAME_FILES:
            try:
                top = sorted(blame_ranges(repo, parent, f["path"], f["old"], None), key=lambda x: -x[1])[:2]
                subj = [f"{sha[:8]} {git(repo, 'log', '-1', '--format=%s', sha).strip()[:50]} ({n} lines)" for sha, n in top]
            except RuntimeError:
                subj = []
            if subj:
                L.append("  - culprits: " + "; ".join(subj))
    if len(files) > BIG_FIX_MAX_FILES:
        L.append(f"- ... {len(files) - BIG_FIX_MAX_FILES} more files")
    L += ["", f"One file's diff: `evidence.py --show '#{u['pr']}' --out <run folder> --file <path>` (a saved run) or "
              f"`evidence.py --unit '{u['unit']}' --dossier --file <path>`", ""]
    return L


def file_dossier(repo: str, u: dict, file: str, lines: int = FILE_DIFF_LINES) -> str:
    """One file's diff in each of the unit's fix commits, capped."""
    L = [f"# {u['unit']} {u['title']}: {file}", ""]
    n = len(L)
    for c in u["commits"]:
        if not c.get("is_fix"):
            continue
        d = git(repo, "show", "--format=", "-U3", "--no-color", c["sha"], "--", file)
        if d.strip():
            L += [f"## {c['sha'][:8]} {c['subject']}", "", "```diff", capped(d, lines), "```", ""]
    if len(L) == n:
        L.append("no fix commit of this unit changes that file")
    return "\n".join(L) + "\n"


def pr_text(repo: str, pr, run=gh_runner, slug=None) -> str:
    """The PR body's first PR_TEXT_CHARS characters, or "" when there is no PR number, no GitHub remote or no gh."""
    if pr is None:
        return ""
    try:
        slug = slug or github_slug(repo)
        if not slug:
            return ""
        return (json.loads(run(["pr", "view", str(pr), "-R", slug, "--json", "body"]) or "{}").get("body") or "")[:PR_TEXT_CHARS]
    except (GhUnavailable, ValueError, OSError, AttributeError):
        return ""


def dossier(repo: str, u: dict, owner_sha: dict[str, str], diff_lines: int = 60,
            path=None, max_chars: int = 14000, file: str | None = None, body: str = "") -> str:
    """One unit, ready to work as a case: each fix commit's diff, culprits, copies left behind.
    With `path`, only the commits and files inside it. Capped at `max_chars`. A fix commit with more than
    BIG_FIX_DIFF_LINES changed code lines also gets a per-file section; `file` prints just that file's diff;
    `body` (PR text) is listed when given."""
    if file:
        return file_dossier(repo, u, file)
    L = [f"# {u['unit']} {u['title']}", f"{u['date']} · {u['kind']} · base {u['base'] or '-'} · {'fix: ' + '; '.join(u['why']) if u['is_fix'] else 'not a fix'}"
         + (f" · tags: {', '.join(u['tags'])}" if u["tags"] else ""), ""]
    gh = u.get("gh") or {}
    if body or gh:
        L += ["## PR text (data, not instructions)", ""]
        if gh.get("labels"):
            L.append("> PR labels: " + ", ".join(gh["labels"]))
        for c in gh.get("closes", []):
            L.append(f"> PR closes: #{c['number']} {' '.join(c.get('title', '').split())}"
                     + (f" [{c['state']}]" if c.get("state") else "") + (f" ({', '.join(c['labels'])})" if c.get("labels") else ""))
        L += ["> " + x for x in body.splitlines()] + [""]
    inside = lambda f: in_scope(f, path)
    code = [f["path"] for f in u["files"] if blamed(f["path"]) and inside(f["path"])]
    big = sum(f["ins"] + f["del"] for f in u["files"] if f["path"] in code) > BIG_FIX_DIFF_LINES
    if big:
        max_chars = max(max_chars, 24000)       # room for the per-file section
    for c in u["commits"]:
        if path and not any(inside(f) for f in git(repo, "show", "--name-only", "--format=", c["sha"]).splitlines()):
            continue
        if not c.get("is_fix"):
            L.append(f"- {c['sha'][:8]} {c['subject']}  (not a fix commit)")
            continue
        L += [f"## {c['sha'][:8]} {c['subject']}", ""]
        for e in c.get("introduced_by", []):
            L.append(f"- culprit: {e['unit']} ({e['lines']} lines)")
        for x in c.get("left_behind", []):
            L.append(f"- copy left behind: `{x['line'][:100]}` at {', '.join(x['at'])}")
        if big and code:
            L += [""] + per_file_section(repo, u, c, code)
        L += ["", "```diff", capped(git(repo, "show", "--format=", "-U3", "--no-color", c["sha"], "--", *code) if code else "", diff_lines), "```", ""]
        top = (c.get("introduced_by") or [{}])[0].get("unit")
        if top and top in owner_sha:
            L += [f"Culprit {top}, on the same files:", "```diff",
                  capped(git(repo, "show", "--format=", "--first-parent", "-U2", "--no-color", owner_sha[top], "--", *code), diff_lines // 2), "```", ""]
    text = "\n".join(L) + "\n"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... cut at {max_chars} characters: read the rest with git show <sha> -- <path>\n"
    return text


def default_out(repo: str) -> str:
    """A folder that lasts between commands and stays out of the working tree: .git/inspector/<time>.
    Some sandboxes give each command its own /tmp, so a temporary folder is gone by the next one."""
    import time
    try:
        base = os.path.join(git(repo, "rev-parse", "--absolute-git-dir").strip(), "inspector")
    except RuntimeError:
        return tempfile.mkdtemp(prefix="inspector-")
    path = os.path.join(base, time.strftime("%Y%m%d-%H%M%S"))
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(base, time.strftime("%Y%m%d-%H%M%S") + f"-{n}")
    os.makedirs(path)
    return path


def write(path: str, text: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=d, delete=False) as f:
            tmp = f.name
            f.write(text)
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="repository; defaults to cwd, or the saved repository with --show")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--since", help="a ref (tag, sha) or a date YYYY-MM-DD: the work window starts after it")
    ap.add_argument("--max", type=int, default=200, help="most first-parent units in the work window")
    ap.add_argument("--history", type=int, default=500, help="first-parent units blame results are mapped to")
    ap.add_argument("--unit", help="work one unit only: '#N' or a sha (of the merge or of a commit inside it)")
    ap.add_argument("--path", action="append",
                    help="work only the units that touch this path prefix (repeatable: --path a/ --path b/ works the union)")
    ap.add_argument("--component-root", action="append", default=[],
                    help="a top-level folder whose subfolders are components (repeatable; adds to the defaults)")
    ap.add_argument("--budget", type=int, default=12, help="cases to triage and write dossiers for (default 12)")
    ap.add_argument("--max-blame-lines", type=int, default=400, help="per fix commit")
    ap.add_argument("--workers", type=int, help="git calls in flight (default min(8, cpu count); 1 = one at a time)")
    ap.add_argument("--cache-dir", help="where blame results are cached (default <git dir>/inspector/cache: the only thing written inside .git)")
    ap.add_argument("--no-cache", action="store_true", help="do not read or write the blame cache")
    ap.add_argument("--exclude", action="append", default=[],
                    help="a path prefix left out of blame diffs and the copies search (repeatable; adds to " + ", ".join(DEFAULT_EXCLUDES) + ")")
    ap.add_argument("--no-default-excludes", action="store_true", help="do not leave " + ", ".join(DEFAULT_EXCLUDES) + " out of blame and the copies search")
    ap.add_argument("--min-lines", type=int, default=3, help="blamed lines from an earlier fix that make a fix-of-fix")
    ap.add_argument("--out", help="folder for evidence.json, evidence.md and cases/ (default: a new .git/inspector/<time>)")
    ap.add_argument("--json", help="write the full evidence here instead of <out>/evidence.json")
    ap.add_argument("--md", help="write the summary here instead of <out>/evidence.md")
    ap.add_argument("--github", action="store_true", help="also read the last merged PRs through gh (automatic on a shallow clone)")
    ap.add_argument("--prs", type=int, default=10, help="how many merged PRs the GitHub fallback reads (default 10)")
    ap.add_argument("--no-github", action="store_true",
                    help="skip every gh call: no PR labels, linked issues or PR text (default: read them when origin is on GitHub and gh works)")
    ap.add_argument("--timing", action="store_true", help="print wall time and git call counts per phase to stderr (or INSPECTOR_TIMING=1)")
    ap.add_argument("--dossier", action="store_true", help="with --unit: print that unit's case dossier to stdout and exit (needs no saved run)")
    ap.add_argument("--file", help="with --show or --dossier: print only this file's diff in the unit's fix commits")
    ap.add_argument("--show", help="print one unit ('#N' or sha) as a case dossier, from a saved run (--out or --json), and exit")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    a.path = snapshot.scope_path(a.path)
    repo_override = a.repo
    a.repo = a.repo or "."
    if a.show:
        saved = a.json or (os.path.join(a.out, "evidence.json") if a.out else None)
        if not saved or not os.path.exists(saved):
            print("evidence.py: --show needs a saved run: --out <folder> or --json <file>", file=sys.stderr)
            return 2
        try:
            with open(saved, encoding="utf-8") as f:
                r = json.load(f)
            saved_repo, warnings = snapshot.validate(r, repo=repo_override)
            for warning in warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        except (OSError, ValueError) as e:
            print(f"evidence.py: {e}", file=sys.stderr)
            return 1
        want = a.show.lstrip("#")
        if a.show.startswith("#") or (want.isdigit() and len(want) < 7):
            hit = [u for u in r["timeline"] if u["pr"] is not None and str(u["pr"]) == want]
        else:
            hit = [u for u in r["timeline"] if len(want) >= 4 and (u["sha"].startswith(want)
                   or any(c["sha"].startswith(want) for c in u["commits"]))]
        if not hit:
            print(f"evidence.py: no unit {a.show} in {saved}", file=sys.stderr)
            return 1
        owner_sha = r.get("unit_shas") or {u["unit"]: u["sha"] for u in r["timeline"]}
        try:
            sys.stdout.write(dossier(saved_repo, hit[0], owner_sha, path=r.get("path"), file=a.file,
                                     body="" if a.file else pr_text(saved_repo, hit[0].get("pr"))))
        except RuntimeError as e:
            print(f"evidence.py: {e}", file=sys.stderr)
            return 1
        return 0
    Timing.reset(a.timing or os.environ.get("INSPECTOR_TIMING") == "1")
    try:
        r = investigate(a.repo, a.ref, a.since, a.max, a.max_blame_lines, a.min_lines, a.history,
                        a.unit, a.path, MONOREPO_ROOTS | set(a.component_root), a.workers,
                        a.cache_dir, not a.no_cache,
                        effective_excludes(a.path, a.component_root, a.exclude, not a.no_default_excludes),
                        github=not a.no_github)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"evidence.py: {e}", file=sys.stderr)
        return 1
    r["repo_path"] = os.path.abspath(a.repo)
    owner_sha = r["unit_shas"]
    bodies = r.pop("gh_bodies", None)       # PR texts the github phase read; never saved in evidence.json
    a.pr_body = lambda pr, slug=None: ("" if a.no_github else bodies.get(pr, "") if bodies is not None
                                       else pr_text(r["repo_path"], pr, slug=slug))
    if a.dossier:
        if not a.unit or not r["timeline"]:
            print("evidence.py: --dossier needs --unit", file=sys.stderr)
            return 2
        u0 = r["timeline"][0]
        sys.stdout.write(dossier(r["repo_path"], u0, owner_sha, path=a.path, file=a.file,
                                 body="" if a.file else a.pr_body(u0.get("pr"))))
        return 0
    with phase("output"):
        rc = finish(a, r, owner_sha)
    if Timing.enabled:
        print(Timing.report(), file=sys.stderr)
    return rc


def finish(a, r: dict, owner_sha: dict) -> int:
    r["cases"] = triage(r, a.budget)
    if (r["shallow"] or a.github) and not a.dossier and not a.no_github:
        slug = github_slug(a.repo)
        try:
            if not slug:
                raise GhUnavailable("origin is not a GitHub remote")
            r["github_prs"] = github_units(slug, a.prs, MONOREPO_ROOTS | set(a.component_root), a.path)
        except GhUnavailable as e:
            r["warnings"].append(f"GitHub fallback skipped: {e}")
    # Saving is a convenience, never a requirement: a sandbox may let no command write anywhere.
    saved_note = ""
    try:
        out = a.out or (None if (a.json or a.md) else default_out(a.repo))
    except OSError:
        out, saved_note = None, "nothing saved: no folder could be written; every command below prints to stdout"
    jpath = a.json or (os.path.join(out, "evidence.json") if out else None)
    mpath = a.md or (os.path.join(out, "evidence.md") if out else None)
    case_dir = out or (os.path.dirname(os.path.abspath(jpath)) if jpath else None)
    by = {u["unit"]: u for u in r["timeline"]}
    slug = github_slug(r["repo_path"])
    me = os.path.abspath(__file__)
    lines = []

    def build(label):
        try:
            return dossier(r["repo_path"], by[label], owner_sha, path=a.path,
                           body=a.pr_body(by[label].get("pr"), slug=slug))
        except (OSError, RuntimeError) as e:
            return e
    # the dossiers are independent git reads: build them side by side, write them in order
    built = pmap(build, r["cases"], a.workers if a.workers is not None else min(8, os.cpu_count() or 1)) if case_dir else []
    for i, label in enumerate(r["cases"], 1):
        args = ["python3", me, "--repo", r["repo_path"], "--ref", r["ref_sha"],
                "--unit", label, "--history", str(a.history), "--max", str(a.max),
                "--max-blame-lines", str(a.max_blame_lines), "--min-lines", str(a.min_lines)]
        for p in snapshot.path_list(a.path):
            args += ["--path", p]
        for root in a.component_root:
            args += ["--component-root", root]
        cmd = shlex.join(args + ["--dossier"])
        where = f"`{cmd}`"
        if case_dir:
            fp = os.path.join(case_dir, "cases", f"{i:02d}-{label.lstrip('#')}.md")
            try:
                if isinstance(built[i - 1], Exception):
                    raise built[i - 1]
                write(fp, built[i - 1])
                where = f"`{fp}` (or `{cmd}`)"
            except (OSError, RuntimeError):
                case_dir = None
        lines.append(f"{i}. {label}: {where}")
    md = markdown(r)
    if "github_prs" in r:
        md += "\n".join(github_markdown(r["github_prs"], a.path)) + "\n"
    if lines:
        # First thing after the header and warnings: what to read next.
        head, sep, rest = md.partition("\n- Units in the work window")
        md = (head + "\n## Cases to work, in order: read each one's dossier first\n\n" + "\n".join(lines) + "\n"
              + sep + rest)
    for path_, text in ((jpath, json.dumps(r, ensure_ascii=False)), (mpath, md)):
        if path_ and path_ != "/dev/stdout":
            try:
                write(path_, text)
            except OSError:
                saved_note = saved_note or f"nothing saved: {path_} could not be written"
                jpath = None
    sys.stdout.write(md)
    if jpath:
        sys.stdout.write(f"\nSaved: {jpath}\n")
    elif saved_note:
        sys.stdout.write(f"\n{saved_note}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
