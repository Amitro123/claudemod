"""Digest a finished agent run so a skill can be written from what it actually did.

    python trace.py --latest [--cwd DIR]        # the newest Claude Code session of this project
    python trace.py PATH [--format text|jsonl|claude-jsonl]
    python trace.py --find [--cwd DIR]          # list transcripts it can read, newest first
    options: --json (machine output) --out FILE --no-mask --steps N (default 80)

Prints: the task, the steps (repeats collapsed), each failure and the call that came after it, things tried 3+
times, calls that were blocked or denied, the skills and sub-agents used, and the final answer. Emails, GUIDs,
tokens, session links and user names in paths are masked unless --no-mask: the digest goes into a skill.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript as T  # noqa: E402

BLOCK_RE = re.compile(r"\b(blocked|denied|not allowed|permission|refused|rejected by|requires approval)\b", re.I)


def norm(cmd: str) -> str:
    c = " ".join(cmd.split())
    c = re.sub(r"^cd \S+ (&&|;) ", "", c)
    return c


def key(call: T.Call) -> str:
    if call.tool in ("Bash", "Shell", "PowerShell", "run_terminal_cmd"):
        toks = norm(str(call.input.get("command", ""))).split()
        return f"{call.tool}:{' '.join(toks[:2])}"
    return f"{call.tool}:{call.brief(60)}"


def first_line(s: str, width: int = 200) -> str:
    for ln in s.splitlines():
        if ln.strip():
            ln = ln.strip()
            return ln if len(ln) <= width else ln[: width - 1] + "…"
    return ""


def digest(sess: T.Session, steps: int = 80) -> dict:
    calls = sess.calls
    errors = [i for i, c in enumerate(calls) if c.ok is False]
    failures = []
    for i in errors:
        c = calls[i]
        nxt = calls[i + 1] if i + 1 < len(calls) else None
        failures.append({"step": i + 1, "tool": c.tool, "call": c.brief(), "error": first_line(c.result),
                         "next": nxt.brief() if nxt else None, "next_ok": nxt.ok if nxt else None,
                         "same_kind_next": bool(nxt and key(nxt) == key(c))})
    if sess.format == "text":
        for i, c in enumerate(calls):
            hits = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", c.result) if T.PROBLEM_RE.search(s)]
            if hits:
                nxt = calls[i + 1] if i + 1 < len(calls) else None
                failures.append({"step": i + 1, "tool": c.tool, "call": c.brief(), "error": " / ".join(hits)[:400],
                                 "next": nxt.brief() if nxt else None, "next_ok": None, "same_kind_next": False})
    exact = Counter((c.tool, norm(c.brief(400))) for c in calls)
    kinds = Counter(key(c) for c in calls)
    repeats = [{"what": k, "times": n} for k, n in kinds.most_common() if n >= 3]
    loops = [{"call": f"{t}: {b}", "times": n} for (t, b), n in exact.items() if n >= 2]
    blocked = [{"step": i + 1, "call": c.brief(), "said": first_line(c.result)}
               for i, c in enumerate(calls) if c.result and BLOCK_RE.search(first_line(c.result, 400))]
    collapsed, last = [], None
    for i, c in enumerate(calls):
        k = (c.tool, norm(c.brief(400)))
        if collapsed and k == last:
            collapsed[-1]["times"] += 1
            collapsed[-1]["ok"] = c.ok
            continue
        collapsed.append({"step": i + 1, "tool": c.tool, "call": c.brief(), "ok": c.ok, "times": 1,
                          "observed": first_line(c.result, 240) if sess.format == "text" else None})
        last = k
    skills = sorted({str(c.input.get("skill") or c.input.get("name")) for c in calls if c.tool == "Skill"})
    agents = [{"type": a.subagent_type, "description": a.description, "work_calls": len(a.work_calls),
               "reported_tool_uses": a.reported_tool_uses, "status": a.status} for a in sess.agents]
    by_tool = Counter(c.tool for c in calls)
    return {
        "transcript": sess.path, "format": sess.format, "notes": sess.notes,
        "stats": {"calls": len(calls), "errors": len(errors), "prompts": len(sess.prompts),
                  "seconds": T.seconds_between(sess.start, sess.end), "by_tool": dict(by_tool.most_common())},
        "task": sess.prompts[0] if sess.prompts else "",
        "followups": sess.prompts[1:],
        "steps": collapsed[:steps], "steps_omitted": max(0, len(collapsed) - steps),
        "failures": failures, "repeats": repeats, "exact_repeats": loops, "blocked": blocked,
        "skills": skills, "agents": agents,
        "final": sess.texts[-1] if sess.texts else "",
    }


def mark(ok) -> str:
    return {True: "ok", False: "FAILED", None: "?"}[ok]


def render(d: dict) -> str:
    s = d["stats"]
    out = [f"# Trace digest: {Path(d['transcript']).name}", "",
           f"format {d['format']}; {s['calls']} calls, {s['errors']} failed; {s['prompts']} user prompts"
           + (f"; {s['seconds'] / 60:.0f} min" if s.get("seconds") else "")
           + "; by tool: " + ", ".join(f"{k} {v}" for k, v in s["by_tool"].items())]
    out += [f"note: {n}" for n in d["notes"]]
    out += ["", "## Task", "", d["task"][:3000] or "(none found)"]
    if d["followups"]:
        out += ["", "## Later prompts", ""] + [f"- {p[:400]}" for p in d["followups"]]
    out += ["", "## Steps", ""]
    for st in d["steps"]:
        times = f" ×{st['times']}" if st["times"] > 1 else ""
        out.append(f"{st['step']}. [{st['tool']}] {st['call']} ({mark(st['ok'])}){times}")
        if st.get("observed"):
            out.append(f"   after: {st['observed']}")
    if d["steps_omitted"]:
        out.append(f"... {d['steps_omitted']} more steps (--steps to raise)")
    out += ["", "## Failures and what came next", ""]
    out += [f"- step {f['step']} [{f['tool']}] {f['call']}\n  error: {f['error'] or '(no text)'}\n  next: {f['next'] or '(end)'}"
            + (f" ({mark(f['next_ok'])})" if f["next"] else "") for f in d["failures"]] or ["(none)"]
    out += ["", "## Tried 3+ times (same tool and first words)", ""]
    out += [f"- {r['what']}: {r['times']}" for r in d["repeats"]] or ["(none)"]
    if d["exact_repeats"]:
        out += ["", "## The exact same call more than once", ""] + [f"- {r['call']}: {r['times']}" for r in d["exact_repeats"]]
    out += ["", "## Blocked or denied", ""]
    out += [f"- step {b['step']}: {b['call']} -> {b['said']}" for b in d["blocked"]] or ["(none)"]
    out += ["", "## Skills and sub-agents", "", "skills: " + (", ".join(d["skills"]) or "none")]
    out += [f"- {a['type']}: {a['description']} ({a['work_calls']} calls"
            + (f", reported {a['reported_tool_uses']}" if a["reported_tool_uses"] is not None else "") + ")" for a in d["agents"]]
    out += ["", "## Final answer", "", d["final"][:4000] or "(none)"]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--find", action="store_true")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--everywhere", action="store_true", help="look in every project's transcripts, not only this folder's")
    ap.add_argument("--format", choices=["text", "jsonl", "claude-jsonl"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--no-mask", action="store_true")
    ap.add_argument("--steps", type=int, default=80)
    a = ap.parse_args(argv)
    if a.find:
        for f in T.candidates(a.cwd, everywhere=a.everywhere)[:20]:
            print(f)
        return 0
    path = a.path
    if a.latest or not path:
        found = T.candidates(a.cwd, everywhere=a.everywhere)
        if not found:
            print("No transcript found. Pass its path (a Cursor export or a pasted chat saved as .md works).", file=sys.stderr)
            return 2
        path = str(found[0])
    d = digest(T.load(path, a.format), a.steps)
    if a.json:  # masked value by value, so the JSON stays JSON
        text = json.dumps(d if a.no_mask else T.mask_data(d), ensure_ascii=False, indent=2)
    else:
        text = render(d) if a.no_mask else T.mask(render(d))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Saved: {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
