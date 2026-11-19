"""Resolve the facts an audit needs before any check starts, from git alone, in one pass.

    python context.py --repo . [--since 2026-11-16] [--hours 24] [--base main] [--no-network] [--auth] [--out FILE]

Prints JSON: the time window (UTC), the repository, its remotes (credentials stripped from URLs; GitHub, Azure
DevOps or other, with owner and repo), the default branch, the commits on it since --since (filtered by
committer date, which is what `git log --since` uses), the remote's branches (live from `git ls-remote` unless
--no-network), each local branch (upstream, ahead/behind, on the remote or not, commits in the window), each
worktree (branch, uncommitted and untracked counts), ignored folders that hold files, the CLIs on PATH (git, gh,
az, gitleaks, rg), Azure DevOps organizations named in pipeline files. With --auth also whether `gh` and `az`
are signed in (their exit codes only; nothing they print is kept).

It prints no file contents and no secret: it is safe to paste into a sub-agent's brief as its Context.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def git(repo: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, f"{type(e).__name__}"


def strip_credentials(url: str) -> str:
    if "://" in url:
        parts = urlsplit(url)
        if parts.username or parts.password:
            host = parts.hostname or ""
            if parts.port:
                host += f":{parts.port}"
            return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
        return url
    return re.sub(r"^[^@/]+:[^@/]+@", "", url)


def classify_remote(url: str) -> dict:
    u = strip_credentials(url)
    out = {"url": u, "kind": "other", "host": None, "owner": None, "project": None, "repo": None}
    m = re.match(r"^(?:[\w+]+://)?(?:[^@/]+@)?([^/:]+)[/:](.+?)(?:\.git)?/?$", u)
    if not m:
        return out
    host, path = m.group(1).lower(), m.group(2)
    out["host"] = host
    segs = [s for s in path.split("/") if s]
    if host.endswith("github.com") and len(segs) >= 2:
        out.update(kind="github", owner=segs[-2], repo=segs[-1])
    elif host == "dev.azure.com" and "_git" in segs:
        i = segs.index("_git")
        out.update(kind="azure-devops", owner=segs[0], project=segs[i - 1] if i >= 2 else None, repo=segs[i + 1] if i + 1 < len(segs) else None)
    elif host == "ssh.dev.azure.com" and len(segs) >= 4:
        out.update(kind="azure-devops", owner=segs[1], project=segs[2], repo=segs[3])
    elif host.endswith("visualstudio.com") and "_git" in segs:
        i = segs.index("_git")
        out.update(kind="azure-devops", owner=host.split(".")[0], project=segs[i - 1] if i >= 1 else None, repo=segs[i + 1] if i + 1 < len(segs) else None)
    elif host.endswith("gitlab.com") and len(segs) >= 2:
        out.update(kind="gitlab", owner="/".join(segs[:-1]), repo=segs[-1])
    return out


def default_branch(repo: Path, remote: str) -> str | None:
    rc, out = git(repo, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    if rc == 0 and out.strip():
        return out.strip().rsplit("/", 1)[-1]
    for b in ("main", "master", "trunk", "develop"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{b}")[0] == 0:
            return b
    return None


def remote_heads(repo: Path, remote: str, network: bool) -> tuple[list[str], str]:
    if network:
        rc, out = git(repo, "ls-remote", "--heads", remote, timeout=30)
        if rc == 0:
            return sorted(ln.split("refs/heads/", 1)[1] for ln in out.splitlines() if "refs/heads/" in ln), "git ls-remote (live)"
    rc, out = git(repo, "for-each-ref", "--format=%(refname)", f"refs/remotes/{remote}/")
    heads = sorted(r.split(f"refs/remotes/{remote}/", 1)[1] for r in out.split() if not r.endswith("/HEAD"))
    return heads, "local remote-tracking refs (as of the last fetch)" + ("; ls-remote failed" if network else "")


def commits(repo: Path, ref: str, since: str | None, first_parent: bool = False) -> list[dict]:
    args = ["log", ref, "--format=%H%x09%cI%x09%aI%x09%an%x09%P%x09%s"]
    if first_parent:
        args.insert(2, "--first-parent")
    if since:
        args.append(f"--since={since}")
    rc, out = git(repo, *args)
    rows = []
    for ln in out.splitlines() if rc == 0 else []:
        f = ln.split("\t", 5)
        if len(f) == 6:
            rows.append({"sha": f[0][:12], "committed": f[1], "authored": f[2], "author": f[3], "merge": len(f[4].split()) > 1, "subject": f[5]})
    return rows


def worktrees(repo: Path) -> list[dict]:
    rc, out = git(repo, "worktree", "list", "--porcelain")
    items, cur = [], {}
    for ln in (out.splitlines() if rc == 0 else []) + [""]:
        if not ln.strip():
            if cur:
                items.append(cur)
            cur = {}
            continue
        k, _, v = ln.partition(" ")
        if k == "worktree":
            cur["path"] = v
        elif k == "HEAD":
            cur["head"] = v[:12]
        elif k == "branch":
            cur["branch"] = v.replace("refs/heads/", "")
        elif k in ("detached", "bare", "locked", "prunable"):
            cur[k] = True
    for w in items:
        rc, st = git(Path(w["path"]), "status", "--porcelain")
        lines = st.splitlines() if rc == 0 else []
        w["uncommitted"] = sum(1 for x in lines if not x.startswith("??"))
        w["untracked"] = sum(1 for x in lines if x.startswith("??"))
    return items


def ignored_folders(repo: Path, limit: int = 30) -> list[dict]:
    rc, out = git(repo, "status", "--porcelain", "--ignored=matching", "--untracked-files=normal")
    found = []
    for ln in out.splitlines() if rc == 0 else []:
        if ln.startswith("!! "):
            p = ln[3:].strip().strip('"')
            if p.endswith("/") and not re.search(r"(^|/)(node_modules|__pycache__|\.venv|venv|\.pytest_cache|dist|build)/$", p):
                n = sum(1 for _ in (repo / p).rglob("*") if _.is_file()) if (repo / p).is_dir() else 0
                found.append({"path": p, "files": n})
    return found[:limit]


ADO_URL_RE = re.compile(r"https://dev\.azure\.com/([A-Za-z0-9_.-]+)(?:/([A-Za-z0-9_.%-]+))?|https://([A-Za-z0-9-]+)\.visualstudio\.com")


def ado_orgs(repo: Path) -> list[dict]:
    rc, out = git(repo, "ls-files", "*.yml", "*.yaml", "*.json", "*.md", "*.ps1", "*.py")
    seen: dict[str, dict] = {}
    for f in (out.splitlines() if rc == 0 else [])[:4000]:
        if re.search(r"(^|/)(tests?|fixtures?|testdata|spec)/|(^|/)test_[^/]*$|_test\.[a-z]+$", f):
            continue
        p = repo / f
        try:
            if p.stat().st_size > 1_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in ADO_URL_RE.finditer(text):
            org = m.group(1) or m.group(3)
            if org.lower() in ("_apis", "{organization}", "organization"):
                continue
            e = seen.setdefault(org, {"org": org, "projects": set(), "files": []})
            if m.group(2) and not m.group(2).startswith("_"):
                e["projects"].add(m.group(2))
            if len(e["files"]) < 3 and f not in e["files"]:
                e["files"].append(f)
    return [{**v, "projects": sorted(v["projects"])} for v in seen.values()]


def signed_in(cmd: list[str]) -> bool | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def collect(repo: Path, since: str | None, hours: int, base: str | None, network: bool, auth: bool) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rc, root = git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        raise SystemExit(f"{repo}: not a git repository")
    repo = Path(root.strip())
    rc, out = git(repo, "remote", "-v")
    remotes = {}
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = {"name": parts[0], **classify_remote(parts[1])}
    primary = "origin" if "origin" in remotes else (next(iter(remotes)) if remotes else None)
    base = base or (default_branch(repo, primary) if primary else None)
    heads, heads_source = remote_heads(repo, primary, network) if primary else ([], "no remote")
    base_ref = f"{primary}/{base}" if primary and base else (base or "HEAD")
    rc, out = git(repo, "for-each-ref", "--format=%(refname:short)%09%(upstream:short)%09%(upstream:track)%09%(committerdate:iso-strict)", "refs/heads/")
    branches = []
    for ln in out.splitlines():
        name, up, track, date = (ln.split("\t") + ["", "", "", ""])[:4]
        ahead = re.search(r"ahead (\d+)", track)
        behind = re.search(r"behind (\d+)", track)
        b = {"name": name, "upstream": up or None, "ahead": int(ahead.group(1)) if ahead else 0,
             "behind": int(behind.group(1)) if behind else 0, "upstream_gone": "gone" in track,
             "on_remote": name in heads, "last_commit": date}
        if since:
            b["commits_in_window"] = len(commits(repo, name, since))
            if not b["on_remote"]:
                b["unpushed_in_window"] = b["commits_in_window"]
        branches.append(b)
    window = {"now": now.isoformat(), "deploy_window_start": (now - timedelta(hours=hours)).isoformat(), "hours": hours, "since": since}
    rc, head = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    rc2, st = git(repo, "status", "--porcelain")
    return {
        "window": window,
        "repo": {"root": str(repo), "branch": head.strip(), "uncommitted": sum(1 for x in st.splitlines() if not x.startswith("??")),
                 "untracked": sum(1 for x in st.splitlines() if x.startswith("??"))},
        "remotes": list(remotes.values()), "primary_remote": primary, "default_branch": base,
        "base_commits": commits(repo, base_ref, since, first_parent=True) if since else None,
        "base_ref": base_ref,
        "remote_heads": {"count": len(heads), "source": heads_source, "names": heads},
        "branches": branches, "worktrees": worktrees(repo), "ignored_folders": ignored_folders(repo),
        "tools": {t: bool(shutil.which(t)) for t in ("git", "gh", "az", "gitleaks", "rg")},
        "signed_in": {"gh": signed_in(["gh", "auth", "status"]), "az": signed_in(["az", "account", "show", "-o", "none"])} if auth else None,
        "azure_devops": ado_orgs(repo),
        "notes": [
            "`git log --since` filters by committer date; `%ad`/`%aI` print the author date. A rebased or "
            "cherry-picked commit can be authored before the window and committed in it, or the reverse.",
            "Times are UTC. Convert a local time before comparing it with the window.",
            "A branch with on_remote false exists only in this clone: it has no pull request and no review.",
            "Worktrees share refs with the main checkout; run git -C <worktree> for its status, not for its log.",
        ],
    }


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--since")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--base")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    d = collect(Path(a.repo), a.since, a.hours, a.base, not a.no_network, a.auth)
    text = json.dumps(d, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Saved: {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
