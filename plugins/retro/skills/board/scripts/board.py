"""A shared board of facts for a main agent and its sub-agents: one append-only JSONL file in the run folder.

    python board.py --board RUN/board.jsonl add KEY VALUE --by AGENT --evidence "command -> what it showed" [--level read]
    python board.py --board RUN/board.jsonl get [KEY | PREFIX*] --by AGENT [--min-level read] [--history] [--json] [--max-age MINUTES]
    python board.py --board RUN/board.jsonl seed --from context.json --by main     # facts from /inspector:audit's context
    python board.py --board RUN/board.jsonl keys                                   # the current keys, for a brief
    python board.py --board RUN/board.jsonl show                                   # facts, who wrote them, who read what
    (--board may be left out when $AGENT_BOARD names the file.)

A fact is a key (lowercase, dotted: `azure.resource_group`, `git.branch.feat-x.on_remote`), a value (one line, at
most 500 characters), who wrote it, the evidence (the command or file that shows it) and a level: `reproduced`
(ran something and saw it), `read` (read it in a record or file), `claimed` (someone's word: a report, a message).
Nothing is deleted: a new value for a key supersedes the old one, and `get --history` shows both. Adding the
value a key already has appends a confirm (who checked it again, the evidence, when); `get` and `show` give each
fact's last-confirmed time, and `get --max-age MINUTES` keeps only facts written or confirmed that recently. A new key for an attribute the board already holds with the same
value under another namespace (`repo.default_branch = main` when `git.default_branch = main` exists) is
refused, naming the existing key; `--new-key` adds it anyway. With a different value it is written (`gh.version`
and `az.version` are two things) and `show` lists the pair to check. Values that look like a token, a bearer value or a private key are
refused: the board holds where a secret is, never the secret.

Every `get` is logged with who asked, so an audit can tell a fact that was read from one rediscovered.
Several agents may write at once: each record is one locked append.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEVELS = {"claimed": 0, "read": 1, "reproduced": 2}
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,119}$")
SECRET_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}|\bglpat-[A-Za-z0-9_-]{20,}|"
                       r"\bxox[baprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{24,}|"
                       r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|"
                       r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                       r"(?<![A-Za-z0-9])[a-z2-7]{52}(?![A-Za-z0-9])")
MAX_VALUE = 500
LOCK_WAIT_S = 60  # Windows only: fcntl blocks; msvcrt has no blocking lock without a 10 s cap, so we poll


def _utcnow() -> datetime:
    """The one clock the board reads, so tests can move it."""
    return datetime.now(timezone.utc)


def now() -> str:
    return _utcnow().isoformat(timespec="seconds")


def _parse_ts(ts) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class Locked:
    """An exclusive lock on the board for one append or one read, on POSIX and Windows."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        self.f.close()
                        raise TimeoutError(f"{self.path}: another writer held the board's lock for {LOCK_WAIT_S} s; "
                                           f"nothing was written, run the command again") from None
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        return self.f

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()


def records(f) -> list[dict]:
    f.seek(0)
    out = []
    for ln in f:
        ln = ln.strip()
        if ln:
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                out.append(r)
    return out


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with Locked(path) as f:
        return records(f)


def current(recs: list[dict]) -> dict[str, dict]:
    facts: dict[str, dict] = {}
    for r in recs:
        if r.get("type") == "fact":
            facts[r["key"]] = r
    return facts


def next_id(recs: list[dict]) -> int:
    """One more than the highest id on the board: a line that won't parse is skipped, so counting lines could reuse one."""
    return max((r["id"] for r in recs if isinstance(r.get("id"), int)), default=0) + 1


def last_confirmed(recs: list[dict], min_level: str = "claimed") -> tuple[dict[int, str], dict[int, int]]:
    """For each fact id: the latest of its own `ts` and the `ts` of its confirms at `min_level` or above, and how
    many such confirms it has. A claimed confirm can't make a reproduced fact fresh under --min-level reproduced.
    A confirm whose `ts` won't parse is skipped; a fact whose own `ts` won't parse keeps the raw string."""
    latest: dict[int, str] = {}
    best: dict[int, datetime | None] = {}
    counts: dict[int, int] = {}
    for r in recs:
        if r.get("type") == "fact" and "id" in r:
            latest[r["id"]] = r.get("ts")
            best[r["id"]] = _parse_ts(r.get("ts"))
            counts[r["id"]] = 0
    for r in recs:
        if r.get("type") != "confirm" or r.get("fact") not in latest:
            continue
        if LEVELS.get(r.get("level"), 0) < LEVELS[min_level]:
            continue
        fid = r["fact"]
        counts[fid] += 1
        t = _parse_ts(r.get("ts"))
        if t is None:
            continue
        if best[fid] is None or t > best[fid]:
            best[fid], latest[fid] = t, r["ts"]
    return latest, counts


def conflicts(recs: list[dict]) -> dict[str, dict]:
    """Keys whose current fact replaced another writer's different value, with nothing settling it: an `add
    --resolve` (on the new value or a confirm of it), or the first writer confirming the new value. One writer
    replacing their own value is a refresh (the branch was pushed), not a disagreement."""
    by_id = {r["id"]: r for r in recs if r.get("type") == "fact" and isinstance(r.get("id"), int)}
    out = {}
    for key, cur in current(recs).items():
        # Past the current writer's own refreshes to the value they replaced: a second write by B doesn't
        # erase B's disagreement with A. A resolution anywhere on B's run settles it.
        chain, prev, seen = [cur], by_id.get(cur.get("supersedes")), {cur["id"]}
        while prev and prev.get("by") == cur.get("by") and not prev.get("resolution") and prev["id"] not in seen:
            chain.append(prev)
            seen.add(prev["id"])
            prev = by_id.get(prev.get("supersedes"))
        if not prev or prev.get("by") == cur.get("by") or prev.get("value") == cur.get("value") or any(c.get("resolution") for c in chain):
            continue
        ids = {c["id"] for c in chain}
        settled = any(r.get("type") == "confirm" and r.get("fact") in ids and (r.get("resolution") or r.get("by") == prev.get("by"))
                      for r in recs)
        if not settled:
            out[key] = {"key": key, "now": {k: cur.get(k) for k in ("value", "by", "evidence", "level", "ts")},
                        "before": {k: prev.get(k) for k in ("value", "by", "evidence", "level", "ts")}}
    return out


def append(f, rec: dict) -> None:
    f.seek(0, os.SEEK_END)
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    f.flush()
    os.fsync(f.fileno())


def check(key: str, value: str, level: str) -> str | None:
    if not KEY_RE.match(key):
        return f"key {key!r}: use lowercase letters, digits and . _ : / - (at most 120)"
    if "\n" in value or "\r" in value:
        return "value: one line; put a list's items under keys of their own"
    if len(value) > MAX_VALUE:
        return f"value: {len(value)} characters, at most {MAX_VALUE}; put the detail in a file and the path here"
    if SECRET_RE.search(value):
        return "value looks like a secret; write where it is and what kind (scan.py's finding), never the value"
    if level not in LEVELS:
        return f"level {level!r}: use reproduced, read or claimed"
    return None


class DuplicateKey(ValueError):
    """The board already holds this attribute under another key."""


def similar(facts: dict[str, dict], key: str) -> list[str]:
    """Keys for the same attribute under another namespace (`repo.default_branch` beside `git.default_branch`).
    Keys that differ in a name in the middle (`git.branch.a.on_remote`, `git.branch.b.on_remote`) are different facts."""
    parts = key.split(".")
    if len(parts) < 2:
        return []
    out = []
    for k in facts:
        q = k.split(".")
        if k != key and len(q) == len(parts) and q[0] != parts[0] and q[1:] == parts[1:]:
            out.append(k)
    return sorted(out)


def add(path: Path, key: str, value: str, by: str, evidence: str, level: str = "read", new_key: bool = False,
        resolve: str | None = None, at: str | None = None) -> tuple[str, dict]:
    """`resolve`: why this value settles a disagreement (main agent). `at`: when the fact was observed, for facts
    seeded from an earlier record (a context.json); the record keeps the time it was written as `recorded`."""
    err = check(key, value, level) or (None if evidence.strip() else "evidence: name the command, record or file that shows it")
    if err:
        raise ValueError(err)
    if SECRET_RE.search(evidence):
        raise ValueError("evidence looks like it holds a secret; cite the command, not its output")
    if SECRET_RE.search(key) or SECRET_RE.search(by):
        raise ValueError("the key or --by looks like it holds a secret; name the fact, not its value")
    if not by.strip() or len(by) > 80 or "\n" in by:
        raise ValueError("--by: the writer's name, one line, at most 80 characters")
    if resolve is not None and (not resolve.strip() or "\n" in resolve or len(resolve) > MAX_VALUE or SECRET_RE.search(resolve)):
        raise ValueError("--resolve: why this value settles it, one line, at most 500 characters, no secret")
    if at is not None and _parse_ts(at) is None:
        raise ValueError(f"at: {at!r} is not an ISO time")
    stamp = {"ts": at, "recorded": now()} if at else {"ts": now()}
    extra = {"resolution": resolve} if resolve else {}
    with Locked(path) as f:
        recs = records(f)
        facts = current(recs)
        old = facts.get(key)
        if old and old["value"] == value:
            conf = {"type": "confirm", "id": next_id(recs), "key": key, "value": value, "fact": old["id"],
                    "by": by, "evidence": evidence, "level": level, **stamp, **extra}
            append(f, conf)
            return "confirmed", conf
        twins = [] if old else similar(facts, key)
        same = [k for k in twins if facts[k]["value"] == value]
        if same and not new_key:
            have = "; ".join(f"{k} = {facts[k]['value']} (by {facts[k]['by']})" for k in same)
            raise DuplicateKey(f"the board already has this fact: {have}. Nothing to add; use that key from now on, "
                               f"or pass --new-key if {key} is a different fact that happens to have the same value")
        rec = {"type": "fact", "id": next_id(recs), "key": key, "value": value, "by": by, "evidence": evidence,
               "level": level, **stamp, "supersedes": old["id"] if old else None, **extra}
        if twins:
            rec["similar_keys"] = twins
        append(f, rec)
        return ("superseded" if old else "added"), rec


def get(path: Path, pattern: str | None, by: str, min_level: str = "claimed", history: bool = False,
        max_age: float | None = None) -> list[dict]:
    if SECRET_RE.search(by) or SECRET_RE.search(pattern or ""):
        raise ValueError("--by or the pattern looks like it holds a secret")
    if max_age is not None and not (isinstance(max_age, (int, float)) and math.isfinite(max_age) and max_age > 0):
        raise ValueError("--max-age: minutes, a number above 0")
    with Locked(path) as f:
        recs = records(f)
        facts = [r for r in recs if r.get("type") == "fact"] if history else list(current(recs).values())
        if pattern:
            facts = [r for r in facts if (r["key"].startswith(pattern[:-1]) if pattern.endswith("*") else r["key"] == pattern)]
        facts = [r for r in facts if LEVELS.get(r.get("level"), 0) >= LEVELS[min_level]]
        latest, counts = last_confirmed(recs, min_level)
        open_ = conflicts(recs)
        facts = [{**r, "last_confirmed": latest.get(r.get("id"), r.get("ts")), "confirms": counts.get(r.get("id"), 0),
                  **({"conflict": open_[r["key"]]["before"]} if r["key"] in open_ and not history else {})}
                 for r in facts]
        if max_age is not None:
            try:
                since = _utcnow() - timedelta(minutes=max_age)
            except OverflowError:
                raise ValueError(f"--max-age: {max_age:g} minutes reaches before the year 1; give fewer") from None
            facts = [r for r in facts if (t := _parse_ts(r["last_confirmed"])) is not None and t >= since]
        read = {"type": "read", "by": by, "pattern": pattern or "*", "keys": [r["key"] for r in facts], "ts": now()}
        if max_age is not None:
            read["max_age"] = max_age
        append(f, read)
    return facts


def slug(name: str) -> str:
    """A name as key text: `/` and `.` kept, so `feat/x`, `feat-x`, `release/1.2` and `release/1_2` stay apart;
    a name with capitals gets a short hash so `Feat` and `feat` do too."""
    out = re.sub(r"[^a-z0-9_.:/-]", "_", name.lower()).strip("/.") or "_"
    if name != name.lower():
        out += ":" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    return out


def flatten_context(ctx: dict) -> list[tuple[str, str, str]]:
    """The facts every auditor needs, from /inspector:audit's context.json."""
    out: list[tuple[str, str, str]] = []
    root = Path((ctx.get("repo") or {}).get("root") or "") if (ctx.get("repo") or {}).get("root") else None
    w = ctx.get("window") or {}
    for k in ("now", "since", "deploy_window_start"):
        if w.get(k):
            out.append((f"window.{k}", str(w[k]), "context.py window"))
    repo = ctx.get("repo") or {}
    if repo.get("root"):
        out.append(("repo.root", repo["root"], "git rev-parse --show-toplevel"))
    for r in ctx.get("remotes") or []:
        for f in ("url", "kind", "owner", "project", "repo"):
            if r.get(f):
                out.append((f"remote.{slug(r['name'])}.{f}", str(r[f]), "git remote -v"))
    if ctx.get("default_branch"):
        out.append(("git.default_branch", ctx["default_branch"], "git symbolic-ref refs/remotes/<remote>/HEAD"))
    if ctx.get("base_commits") is not None:
        out.append(("git.base_commits_in_window", str(len(ctx["base_commits"])), f"git log {ctx.get('base_ref')} --first-parent --since"))
    heads = ctx.get("remote_heads") or {}
    if "count" in heads:
        out.append(("git.remote_heads.count", str(heads["count"]), heads.get("source", "git ls-remote")))
    for b in ctx.get("branches") or []:
        name = slug(b["name"])
        out.append((f"git.branch.{name}.on_remote", str(b.get("on_remote")).lower(), "git ls-remote --heads"))
        if b.get("commits_in_window") is not None:
            out.append((f"git.branch.{name}.commits_in_window", str(b["commits_in_window"]), "git log --since"))
    for wt in ctx.get("worktrees") or []:
        wt_path = Path(wt.get("path", ""))
        try:
            rel = wt_path.relative_to(root).as_posix() if root else wt_path.name
        except ValueError:
            rel = wt_path.as_posix().lstrip("/")
        out.append((f"git.worktree.{slug(rel) if rel not in ('', '.') else 'root'}.branch", str(wt.get("branch") or "detached"), "git worktree list --porcelain"))
    for t, ok in (ctx.get("tools") or {}).items():
        out.append((f"tool.{t}.installed", str(ok).lower(), "shutil.which"))
    for t, ok in (ctx.get("signed_in") or {}).items():
        if ok is not None:
            out.append((f"tool.{t}.signed_in", str(ok).lower(), f"{t} auth/account exit code"))
    for o in ctx.get("azure_devops") or []:
        out.append((f"ado.org.{o['org'].lower()}", ",".join(o.get("projects") or []) or "(no project named)", "files: " + ", ".join(o.get("files") or [])))
    return out


def board_path(arg: str | None) -> Path:
    p = arg or os.environ.get("AGENT_BOARD")
    if not p:
        raise SystemExit("no board: pass --board PATH or set AGENT_BOARD")
    return Path(p)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_add = sub.add_parser("add")
    a_add.add_argument("key")
    a_add.add_argument("value")
    a_add.add_argument("--by", required=True)
    a_add.add_argument("--evidence", required=True)
    a_add.add_argument("--level", default="read", choices=list(LEVELS))
    a_add.add_argument("--new-key", action="store_true", help="add it although the same attribute exists under another key")
    a_add.add_argument("--resolve", metavar="WHY", help="this value settles a disagreement between writers (main agent)")
    a_get = sub.add_parser("get")
    a_get.add_argument("pattern", nargs="?")
    a_get.add_argument("--by", required=True)
    a_get.add_argument("--min-level", default="claimed", choices=list(LEVELS))
    a_get.add_argument("--history", action="store_true")
    a_get.add_argument("--json", action="store_true")
    a_get.add_argument("--max-age", type=float, metavar="MINUTES",
                       help="only facts written or confirmed in the last MINUTES minutes (for volatile facts)")
    a_seed = sub.add_parser("seed")
    a_seed.add_argument("--from", dest="src", required=True)
    a_seed.add_argument("--by", default="main")
    sub.add_parser("show")
    sub.add_parser("keys", help="the current keys, one per line with its value: paste them into a brief")
    a = ap.parse_args(argv)
    path = board_path(a.board)
    if a.cmd == "add":
        try:
            what, rec = add(path, a.key, a.value, a.by, a.evidence, a.level, a.new_key, a.resolve)
        except ValueError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        print(f"{what}: {rec['key']} = {rec['value']}" + (f" (supersedes #{rec['supersedes']})" if what == "superseded" else "")
              + (f" (fact #{rec['fact']})" if what == "confirmed" else ""))
    elif a.cmd == "get":
        try:
            facts = get(path, a.pattern, a.by, a.min_level, a.history, a.max_age)
        except ValueError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(facts, ensure_ascii=False, indent=2))
        elif not facts:
            print("(no facts)")
        else:
            live = {x["id"] for x in current(load(path)).values()} if a.history else set()
            for r in facts:
                old = " [superseded]" if a.history and r["id"] not in live else ""
                seen = f", last confirmed {r['last_confirmed']}" if r["confirms"] else ""
                was = f" [disagreement: replaced {r['conflict']['value']} by {r['conflict']['by']}, not settled]" if r.get("conflict") else ""
                print(f"{r['key']} = {r['value']}    [{r['level']}, by {r['by']}: {r['evidence']}, written {r['ts']}{seen}]{old}{was}")
    elif a.cmd == "seed":
        ctx = json.loads(Path(a.src).read_text(encoding="utf-8"))
        observed = (ctx.get("window") or {}).get("now")
        if observed is not None and _parse_ts(observed) is None:
            observed = None
        n = {"added": 0, "superseded": 0, "confirmed": 0, "refused": 0}
        for key, value, ev in flatten_context(ctx):
            try:
                what, _ = add(path, key, value, a.by, ev, "read", at=observed)
                n[what] += 1
            except ValueError:
                n["refused"] += 1
        print(", ".join(f"{v} {k}" for k, v in n.items() if v) or "nothing to seed")
    elif a.cmd == "keys":
        for r in sorted(current(load(path)).values(), key=lambda r: r["key"]):
            v = r["value"] if len(r["value"]) <= 60 else r["value"][:59] + "…"
            print(f"{r['key']} = {v}")
    else:
        recs = load(path)
        facts = current(recs)
        reads: dict[str, int] = {}
        for r in recs:
            if r.get("type") == "read":
                reads[r["by"]] = reads.get(r["by"], 0) + 1
        writers: dict[str, int] = {}
        for r in recs:
            if r.get("type") == "fact":
                writers[r["by"]] = writers.get(r["by"], 0) + 1
        latest, counts = last_confirmed(recs)
        open_ = conflicts(recs)
        print(f"{len(facts)} facts ({sum(1 for r in recs if r.get('type') == 'fact')} records, "
              f"{sum(1 for r in recs if r.get('type') == 'confirm')} confirms); "
              f"written by: {', '.join(f'{k} {v}' for k, v in sorted(writers.items())) or 'nobody'}; "
              f"read by: {', '.join(f'{k} {v}' for k, v in sorted(reads.items())) or 'nobody'}")
        for r in sorted(facts.values(), key=lambda r: r["key"]):
            n_conf = counts.get(r.get("id"), 0)
            seen = f", last confirmed {latest[r['id']]} ({n_conf}x)" if n_conf else ""
            print(f"{r['key']} = {r['value']}    [{r['level']}, by {r['by']}, {r.get('ts')}{seen}]")
        for c in open_.values():
            n_, b_ = c["now"], c["before"]
            print(f"disagreement: {c['key']} = {n_['value']} (by {n_['by']}: {n_['evidence']}) replaced "
                  f"{b_['value']} (by {b_['by']}: {b_['evidence']}); settle it: add {c['key']} <value> --resolve \"<why>\"")
        twins = sorted({tuple(sorted([k, *similar(facts, k)])) for k in facts if similar(facts, k)})
        for group in twins:
            vals = {facts[k]["value"] for k in group}
            print(f"{'same attribute, different values (two things, or a conflict to settle)' if len(vals) > 1 else 'same fact, two keys'}: {', '.join(group)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
