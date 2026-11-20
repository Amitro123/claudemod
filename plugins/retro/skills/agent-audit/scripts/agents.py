"""Audit the sub-agents of a session: the brief each one got, what its own transcript shows it did, and the gaps.

    python agents.py --latest [--cwd DIR]          # the newest Claude Code session of this project
    python agents.py SESSION.jsonl
    python agents.py --reports DIR                 # end-of-run report files (any host; see references/brief-contract.md)
    python agents.py SESSION.jsonl --reports DIR   # both; a report is matched to its agent by "agent" or "brief_id"
    options: --json  --out FILE  --no-mask  --all (every session of the project, for budgets)

Per agent, measured from its transcript (or, with only a report file, as it reported itself):
calls (its hand-back call not counted), failed calls, the same call repeated 3+ times, minutes; the budget its
brief declared ("Budget: N tool calls") and whether it went over; the files the brief asked for and whether they
exist; for a read-only brief, writes outside a temp/scratch folder and mutating git commands; its own count of
tool calls against the measured one. Then a budget per agent type from what was observed.
Whether each ask in the brief was met is a judgement: the skill has you make it from the `asks` and `report`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import posixpath
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
for cand in (HERE, HERE.parent.parent / "distill" / "scripts"):
    if (cand / "transcript.py").exists():
        sys.path.insert(0, str(cand))
        break
import transcript as T  # noqa: E402

BUDGET_RE = re.compile(r"\bbudget\b\s*[:=]?\s*(?:of\s+|is\s+|about\s+|at most\s+)?(\d+)\s*(tool[ -]?calls?|calls?|turns?|steps?)", re.I)
READ_ONLY_RE = re.compile(r"read[- ]only|change nothing|do not (?:modify|change|edit|write to the repo)|don't (?:modify|change|edit)|"
                          r"report findings only|no changes to (?:the )?(?:repo|repository|files)", re.I)
PATH_RE = re.compile(r"(?<![\w<>{}/.-])((?:[A-Za-z]:[\\/]|/|\.{1,2}/|~/)?[\w.\-]+(?:[\\/][\w.\-]+)*\.(?:json|md|txt|csv|ya?ml|html|jsonl|log))\b")
DELIVER_LINE_RE = re.compile(r"^\s*(?:deliverables?|report file|output file|outputs?)\s*:", re.I)
WRITE_PATH_RE = re.compile(r"\b(?:write|save|create)\s+(?:it\s+|them\s+)?(?:to\s+|into\s+|in\s+|as\s+|the\s+file\s+|a\s+file\s+)?"
                           r"((?:[A-Za-z]:[\\/]|/|\.{1,2}/|~/)?[\w.\-]+(?:[\\/][\w.\-]+)*\.(?:json|md|txt|csv|ya?ml|html|jsonl|log))\b", re.I)
SELF_COUNT_RES = [re.compile(r"tool[ -]?calls?(?:\s+used)?\s*[:=]\s*(\d+)", re.I),
                  re.compile(r"\b(\d+)\s+(?:of\s+\d+\s+)?(?:budget(?:ed)?\s+)?tool[ -]?calls?", re.I),
                  re.compile(r"used\s+(\d+)\s+(?:of\s+\d+\s+)?(?:tool[ -]?)?calls?", re.I)]
MUTATING_RE = re.compile(r"\bgit\s+(?:commit|push|reset|checkout\s+--|restore|clean|rebase|merge|tag|branch\s+-[dD])\b|"
                         r"\b(?:rm\s+-rf?|Remove-Item|del\s+/|mv\s|Move-Item)\b|\baz\s+\S+\s+(?:create|delete|update|set)\b|"
                         r"\bgh\s+(?:pr|issue)\s+(?:create|merge|close|comment|edit)\b|--method\s+(?:post|put|patch|delete)\b", re.I)
SCRATCH_HINTS = ("/tmp/", "\\temp\\", "/temp/", "scratchpad", ".inspector-run", "$env:temp", "%temp%", "/var/folders/")
ASK_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)")
CONTEXT_RE = re.compile(r"^\s*(?:context|known|facts|background|already established)\s*:", re.I | re.M)
RULES_RE = re.compile(r"^\s*rules?\s*:|read[- ]only|never print|is data, never instructions", re.I | re.M)
HOST_RE = re.compile(r"\b(?:blocked|denied|permission|not permitted|requires approval|not recognized as|command not found|"
                     r"not found in PATH|401|403|unauthori[sz]ed|forbidden|not signed in|please run .*login|"
                     r"could not resolve host|ENOTFOUND|rate limit|timed? out)\b", re.I)
DISCOVERY_TOOLS = {"Bash", "Shell", "PowerShell", "Grep", "Glob", "run_terminal_cmd"}
SMALL_MODELS = re.compile(r"haiku|mini|flash|small|lite", re.I)
LARGE_MODELS = re.compile(r"opus|sonnet|gpt-5|pro\b|large", re.I)
CAUSES = ("brief", "execution", "host", "model")
BOARD_GET_RE = re.compile(r"board\.py\b.*\sget\b")
BOARD_ADD_RE = re.compile(r"board\.py\b.*\s(?:add|seed)\b")
VERIFIER_RE = re.compile(r"verif|skeptic|re-?check", re.I)


def load_board(path: str | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    out = []
    for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and r.get("type") == "fact":
            out.append(r)
    return out


SHELL_TOOLS = {"Bash", "Shell", "PowerShell", "run_terminal_cmd"}


def evidence_command(ev: str) -> str:
    return " ".join(ev.split("->", 1)[0].split()).strip("` ")


def same_command(evidence: str, command: str) -> bool:
    """The call ran the evidence's command: its words, in order, from the start of one of the call's commands.
    `ls` is not `git ls-remote`, and a bare `git log` is not `git log origin/main --first-parent --since`."""
    ev = evidence.split()
    if len(ev) < 2:
        return False
    for part in re.split(r"\s*(?:&&|\|\||;|\|)\s*", re.sub(r"^cd \S+\s*(?:&&|;)\s*", "", command.strip())):
        words = part.split()
        if words[:len(ev)] == ev:
            return True
    return False


def norm_call(c) -> str:
    return re.sub(r"^cd \S+ (?:&&|;) ", "", " ".join(c.brief(300).split()))


def brief_label(prompt: str) -> str | None:
    """The name the brief gives its agent for its report file (`Report file: <run>/agents/check-1.json`)."""
    m = re.search(r"report file\s*:\s*\S*?([\w.-]+)\.json", prompt or "", re.I)
    return m.group(1) if m else None


def first_line(s: str) -> str:
    return next((ln.strip()[:200] for ln in (s or "").splitlines() if ln.strip()), "")


def brief_terms(prompt: str) -> dict:
    budget = None
    m = BUDGET_RE.search(prompt)
    if m:
        unit = m.group(2).lower()
        budget = {"n": int(m.group(1)), "unit": "turns" if unit.startswith("turn") else "tool calls"}
    deliverables = []
    for ln in prompt.splitlines():
        found = PATH_RE.findall(ln) if DELIVER_LINE_RE.match(ln) else [m.group(1) for m in WRITE_PATH_RE.finditer(ln)]
        for p in found:
            if p not in deliverables and not re.search(r"[<>{}*]", p):
                deliverables.append(p)
    asks = [m.group(1).strip() for ln in prompt.splitlines() if (m := ASK_RE.match(ln))]
    return {"budget": budget, "read_only": bool(READ_ONLY_RE.search(prompt)), "deliverables": deliverables, "asks": asks}


def self_count(report: str) -> int | None:
    for rx in SELF_COUNT_RES:
        m = rx.search(report or "")
        if m:
            return int(m.group(1))
    return None


def resolve(p: str, cwd: Path) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else cwd / q


def same_path(w: str, target: Path, cwd: Path) -> bool:
    """The whole path, resolved against the agent's folder (`..` and `.` taken out): a file of the same name in
    another folder is another file."""
    return os.path.normpath(str(resolve(w, cwd))) == os.path.normpath(str(target))


def is_scratch(p: str) -> bool:
    """A scratch path by where it ends up: `/tmp/../repo/x` is in the repo. `..` and `.` are taken out first."""
    raw = p.replace("\\", "/")
    norm = posixpath.normpath(raw) + ("/" if raw.endswith("/") else "")
    if norm.startswith("../") or norm == "..":
        return False  # climbs out of wherever it started: not known to be scratch
    low = "/" + norm.lstrip("/").lower() if raw.startswith("/") else norm.lower()
    return any(h.replace("\\", "/") in low for h in SCRATCH_HINTS)


def audit_run(a: T.AgentRun, cwd: Path, ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    terms = brief_terms(a.prompt)
    calls = a.work_calls
    has_transcript = bool(a.calls)
    failed = [c for c in calls if c.ok is False]
    seen: dict[tuple, list] = {}
    for c in calls:
        seen.setdefault((c.tool, json.dumps(c.input, sort_keys=True, ensure_ascii=False)), []).append(c)
    loops = [{"call": f"{cs[0].tool}: {cs[0].brief()}", "times": len(cs)} for cs in seen.values() if len(cs) >= 3]
    target = lambda c: str(c.input.get("file_path") or c.input.get("notebook_path") or "")
    writes = [target(c) for c in calls if c.tool in T.WRITE_TOOLS and c.ok is not False]
    refused_writes = [target(c) for c in calls if c.tool in T.WRITE_TOOLS and c.ok is False]
    mutating = [c.brief() for c in calls if c.tool in ("Bash", "Shell", "PowerShell") and MUTATING_RE.search(str(c.input.get("command", "")))]
    deliver = []
    for d in terms["deliverables"]:
        path = resolve(d, cwd)
        written_by_it = any(same_path(w, path, cwd) for w in writes)
        deliver.append({"path": d, "exists": path.exists(), "written_by_agent": written_by_it if has_transcript else None})
    outside, tried = [], []
    if terms["read_only"]:
        allowed = [resolve(d, cwd) for d in terms["deliverables"]]
        bad = lambda w: w and not is_scratch(w) and not any(same_path(w, x, cwd) for x in allowed)
        outside = [w for w in writes if bad(w)]
        tried = [w for w in refused_writes if bad(w)]
    measured = len(calls) if has_transcript else None
    claimed = self_count(a.report)
    flags = []
    b = terms["budget"]
    if b and measured is not None and b["unit"] == "tool calls" and measured > b["n"]:
        flags.append(f"over budget: {measured} calls, budget {b['n']}")
    if not b:
        flags.append("no budget in the brief")
    missing = [d["path"] for d in deliver if not d["exists"]]
    if missing:
        flags.append("deliverable missing: " + ", ".join(missing))
    if outside:
        flags.append("read-only brief, wrote: " + ", ".join(outside[:5]))
    if tried:
        flags.append("read-only brief, tried to write (refused): " + ", ".join(tried[:5]))
    if terms["read_only"] and mutating:
        flags.append("read-only brief, ran: " + "; ".join(mutating[:3]))
    if loops:
        flags.append(f"same call {max(x['times'] for x in loops)}x")
    if claimed is not None and measured is not None and claimed != measured:
        hb = len(a.calls) - len(calls)
        why = " (its count includes the hand-back call)" if claimed == measured + hb and hb else ""
        flags.append(f"says {claimed} calls, transcript shows {measured}{why}")
    if a.reported_tool_uses is not None and measured is not None and a.reported_tool_uses != measured:
        flags.append(f"host counted {a.reported_tool_uses} calls, transcript shows {measured}")
    if a.status and a.status != "completed":
        flags.append(f"status {a.status}")
    if a.finished is False:
        flags.append("not finished")
    if not (a.report or "").strip():
        flags.append("empty report")
    if not has_transcript:
        flags.append("no transcript: only the brief and report")
    causes = {k: [] for k in CAUSES}
    checks = {"budget": bool(b), "numbered_asks": len(terms["asks"]) >= 1, "deliverable_paths": bool(terms["deliverables"]),
              "context": bool(CONTEXT_RE.search(a.prompt)), "rules": bool(RULES_RE.search(a.prompt))}
    if not checks["budget"]:
        causes["brief"].append("brief has no budget (tool calls): nothing to hold the agent to, and no cap to measure against")
    rediscovered = sorted({norm_call(c) for c in calls if c.tool in DISCOVERY_TOOLS and norm_call(c) in ctx.get("main_before", set())})
    if rediscovered:
        causes["brief"].append(f"re-ran {len(rediscovered)} command(s) the main agent had already run (their results were not passed): "
                               + "; ".join(x[:80] for x in rediscovered[:3]))
    host_hits = [f"{c.tool}: {c.brief(80)} -> {first_line(c.result)[:100]}" for c in calls if c.ok is False and HOST_RE.search(c.result[:500])]
    causes["host"] += [f"blocked or unavailable: {h}" for h in host_hits[:5]]
    unrecovered = []
    for i, c in enumerate(calls):
        if c.ok is False and not HOST_RE.search(c.result[:500]):
            nxt = calls[i + 1] if i + 1 < len(calls) else None
            explained = nxt is None and " ".join(str(c.input.get("command", c.brief())).split()[:3]).lower() in (a.report or "").lower()
            if (nxt is None and not explained) or (nxt is not None and nxt.ok is False and nxt.tool == c.tool and nxt.input == c.input):
                unrecovered.append(f"{c.tool}: {c.brief(80)}")
    clear_brief = checks["numbered_asks"] and checks["deliverable_paths"]
    if loops:
        causes["execution"].append(f"repeated the same call {max(x['times'] for x in loops)}x")
    if unrecovered:
        causes["execution"].append(f"{len(unrecovered)} failure(s) not recovered from: " + "; ".join(unrecovered[:3]))
    over = bool(b and b["unit"] == "tool calls" and measured is not None and measured > b["n"])
    if b and b["unit"] == "turns":
        flags.append(f"budget in turns ({b['n']}): not checkable from calls, since one turn can make several")
    if over:
        (causes["execution"] if clear_brief else causes["brief"]).append(f"over budget ({measured}/{b['n']})" + ("" if clear_brief else " with unclear asks or deliverables"))
    if missing:
        (causes["execution"] if checks["deliverable_paths"] else causes["brief"]).append("deliverable missing: " + ", ".join(missing))
    if outside or (terms["read_only"] and mutating):
        causes["execution"].append("broke the brief's read-only rule")
    elif tried:
        causes["execution"].append("tried to write outside what the read-only brief allows (the writes were refused)")
    if not (a.report or "").strip() or a.finished is False:
        causes["execution"].append("ended without a report" if not (a.report or "").strip() else "did not finish")
    cmds = [(i, str(c.input.get("command", ""))) for i, c in enumerate(calls) if c.tool in DISCOVERY_TOOLS]
    board_reads = [i for i, cmd in cmds if BOARD_GET_RE.search(cmd)]
    board_writes = [i for i, cmd in cmds if BOARD_ADD_RE.search(cmd)]
    brief_names_board = bool(re.search(r"^\s*board\s*:", a.prompt, re.I | re.M))
    facts = ctx.get("board_facts") or []
    first_fact = min((f.get("ts", "") for f in facts), default=None)
    started_with_board = bool(first_fact and a.launched and (T.seconds_between(first_fact, a.launched) or 0) >= 0)
    if started_with_board:
        checks["board"] = brief_names_board
        if not brief_names_board:
            causes["brief"].append("brief has no Board line, while the run used a board")
    known = []
    for f in ctx.get("board_facts", []):
        gap = T.seconds_between(f.get("ts"), a.launched) if a.launched else None
        if gap is not None and gap >= 0:
            known.append(f)
    shell = [str(c.input.get("command", "")) for c in calls if c.tool in SHELL_TOOLS]
    shell = [x for x in shell if not BOARD_GET_RE.search(x) and not BOARD_ADD_RE.search(x)]
    rerun = sorted({f["key"] for f in known if any(same_command(evidence_command(f.get("evidence", "")), x) for x in shell)})
    is_verifier = bool(VERIFIER_RE.search(f"{a.subagent_type} {a.description}"))
    if brief_names_board and has_transcript and not board_reads and not is_verifier:
        causes["execution"].append("its brief named the board and it never read it")
    first_work = next((i for i, c in enumerate(calls) if not (c.tool in DISCOVERY_TOOLS and (BOARD_GET_RE.search(str(c.input.get("command", ""))) or BOARD_ADD_RE.search(str(c.input.get("command", "")))))), None)
    if is_verifier and board_reads and (first_work is None or board_reads[0] < first_work):
        causes["execution"].append(
            "a verifier read the board before its own check: its verdicts may copy what it was meant to test")
    struggled = bool(loops or unrecovered or missing or over)
    fail_rate = (len(failed) / measured) if measured else 0.0
    model = a.model or ctx.get("default_model") or ""
    if model and SMALL_MODELS.search(model) and struggled and clear_brief and not host_hits:
        causes["model"].append(f"{model} struggled on a clear brief ({len(failed)}/{measured} calls failed): try a stronger model for this agent type")
    elif model and LARGE_MODELS.search(model) and measured is not None and measured <= 6 and not failed and not missing and has_transcript:
        causes["model"].append(f"{model} finished in {measured} calls with no failure: a smaller model may be enough (cost)")
    return {
        "agent": (a.agent_id or a.call_id) + (f"#{a.dispatch}" if a.dispatches > 1 else ""), "agent_id": a.agent_id,
        "dispatch": f"{a.dispatch} of {a.dispatches}" if a.dispatches > 1 else None,
        "brief_label": brief_label(a.prompt), "refused_writes": refused_writes, "type": a.subagent_type, "model": a.model, "description": a.description,
        "source": ("transcript" if has_transcript else "brief and report only") + (", started by a plugin" if a.started_by == "plugin" else ""),
        "calls": measured, "failed": len(failed), "failed_calls": [f"{c.tool}: {c.brief()} -> {first_line(c.result)}" for c in failed][:10],
        "loops": loops, "minutes": round(s / 60, 1) if (s := T.seconds_between(a.start, a.end)) else None,
        "budget": b, "read_only": terms["read_only"], "deliverables": deliver, "writes": writes, "mutating": mutating,
        "self_reported_calls": claimed, "host_reported_calls": a.reported_tool_uses,
        "asks": terms["asks"], "brief": a.prompt, "report": a.report,
        "steps": [f"{c.tool}: {c.brief(120)}" + ("" if c.ok is not False else "  [failed]") for c in calls][:60],
        "flags": flags, "causes": causes, "brief_checks": checks, "skill": ctx.get("skill"),
        "failure_rate": round(fail_rate, 2), "discovery": sorted({norm_call(c) for c in calls if c.tool in SHELL_TOOLS
                                                                   and not BOARD_GET_RE.search(str(c.input.get("command", "")))
                                                                   and not BOARD_ADD_RE.search(str(c.input.get("command", "")))}),
        "board": {"reads": len(board_reads), "writes": len(board_writes), "reran_known": sorted(set(rerun))} if (board_reads or board_writes or ctx.get("board_in_use")) else None,
    }


def shared_discovery(rows: list[dict]) -> None:
    """A command several agents each ran is a fact the brief should have carried."""
    seen = defaultdict(list)
    for r in rows:
        for d in r.get("discovery") or []:
            seen[d].append(r["agent"])
    for r in rows:
        shared = [d for d in r.get("discovery") or [] if len(set(seen[d])) >= 2]
        if shared:
            r["causes"]["brief"].append(f"{len(shared)} command(s) also run by sibling agents (a fact for the brief's Context): "
                                        + "; ".join(x[:80] for x in shared[:3]))


def rollup(rows: list[dict], key: str) -> list[dict]:
    by = defaultdict(list)
    for r in rows:
        by[r.get(key) or "(none)"].append(r)
    out = []
    for k, rs in sorted(by.items()):
        seen = [r for r in rs if isinstance(r.get("calls"), int)]
        calls = sum(r["calls"] for r in seen)
        out.append({"group": k, "agents": len(rs), "observed": len(seen), "reported_only": len(rs) - len(seen), "calls": calls,
                    "failure_rate": round(sum(r.get("failed") or 0 for r in seen) / calls, 2) if calls else None,
                    **{c: sum(1 for r in rs if r.get("causes", {}).get(c)) for c in CAUSES},
                    "clean": sum(1 for r in seen if not any(r.get("causes", {}).get(c) for c in CAUSES))})
    return out


def from_report_file(f: Path) -> dict:
    d = json.loads(f.read_text(encoding="utf-8"))
    brief = d.get("brief") or ""
    terms = brief_terms(brief) if brief else {"budget": None, "read_only": False, "deliverables": [], "asks": d.get("asked") or []}
    if d.get("budget") is not None and not terms["budget"]:
        terms["budget"] = {"n": int(d["budget"]), "unit": "tool calls"}
    deliver = [{"path": x.get("path") if isinstance(x, dict) else x, "exists": Path(x.get("path") if isinstance(x, dict) else x).expanduser().exists(),
                "written_by_agent": None} for x in d.get("deliverables") or []]
    flags = ["self-reported: no transcript checked"]
    n = d.get("tool_calls")
    b = terms["budget"]
    if b and isinstance(n, int) and n > b["n"]:
        flags.append(f"over budget (own count): {n} calls, budget {b['n']}")
    if not b:
        flags.append("no budget in the brief")
    missing = [x["path"] for x in deliver if not x["exists"]]
    if missing:
        flags.append("deliverable missing: " + ", ".join(missing))
    if d.get("blocked"):
        flags.append("blocked: " + "; ".join(map(str, d["blocked"]))[:200])
    return {"agent": d.get("agent") or f.stem, "brief_id": d.get("brief_id"), "type": d.get("type") or "?", "model": d.get("model"), "description": d.get("brief_id") or "",
            "source": f"report file {f.name}", "calls": None, "failed": None, "failed_calls": [], "loops": [], "minutes": None,
            "budget": b, "read_only": terms["read_only"], "deliverables": deliver, "writes": [], "mutating": [],
            "self_reported_calls": n, "host_reported_calls": None, "asks": terms["asks"] or d.get("asked") or [],
            "brief": brief, "report": "\n".join(f"- {x}" for x in d.get("did") or []) + ("\nopen: " + "; ".join(d["open"]) if d.get("open") else ""),
            "steps": [], "flags": flags, "skill": d.get("skill"), "failure_rate": None, "discovery": [],
            "causes": {"brief": [] if b else ["brief has no budget"], "execution": [f"deliverable missing: {m}" for m in missing] if missing else [],
                       "host": [f"blocked: {x}" for x in d.get("blocked") or []], "model": []},
            "brief_checks": {}}


def budgets(rows: list[dict]) -> list[dict]:
    by, own = defaultdict(list), defaultdict(int)
    for r in rows:
        n = r["calls"] if r["calls"] is not None else r["self_reported_calls"]
        if isinstance(n, int):
            by[r["type"]].append(n)
            own[r["type"]] += r["calls"] is None
    out = []
    for t, ns in sorted(by.items()):
        notes = (["one run: a starting point, not a measurement"] if len(ns) == 1 else []) + \
                ([f"{own[t]} of {len(ns)} self-reported"] if own[t] else [])
        out.append({"type": t, "runs": len(ns), "self_reported": own[t], "min": min(ns), "max": max(ns),
                    "suggested_budget": max(5, math.ceil(max(ns) * 1.25)), "note": "; ".join(notes)})
    return out


def cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def rollup_line(x: dict) -> str:
    agents = str(x["agents"]) + (f" ({x['reported_only']} report-only)" if x["reported_only"] else "")
    rate = "?" if x["failure_rate"] is None else format(x["failure_rate"], ".0%")
    return (f"| {cell(x['group'])} | {agents} | {x['calls']} | {rate} | {x['brief']} | {x['execution']} | {x['host']} | "
            f"{x['model']} | {x['clean']} |")


def owners(r: dict) -> str:
    c = r.get("causes") or {}
    parts = [f"{k} {len(c[k])}" for k in CAUSES if c.get(k)]
    return ", ".join(parts) or "none"


def render(rows: list[dict], bud: list[dict], session: str | None, notes: list[str], roll: dict) -> str:
    out = [f"# Sub-agent audit" + (f": {Path(session).name}" if session else ""), ""]
    out += [f"note: {n}" for n in notes]
    if not rows:
        return "\n".join(out + ["No sub-agent runs found."]) + "\n"
    out += ["Each problem has an owner: **brief** (the skill or main agent that wrote the instructions), **execution** "
            "(the sub-agent), **host** (a tool blocked, auth, a missing CLI), **model** (the model chosen for the task).", "",
            "| Agent | Skill | Type / model | Calls (budget) | Failed | Deliverables | Problems by owner |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        b = r["budget"]
        calls = ("?" if r["calls"] is None else str(r["calls"])) + (f" ({b['n']}{' turns' if b['unit'] == 'turns' else ''})" if b else " (none)")
        dl = ", ".join(f"{Path(d['path']).name} {'yes' if d['exists'] else 'MISSING'}" for d in r["deliverables"]) or "none named"
        out.append(f"| {cell(r['agent'][:12])} {cell(r['description'][:40])} | {cell(r.get('skill') or '-')} | {cell(r['type'])} / {cell(r['model'] or '?')} | "
                   f"{calls} | {'?' if r['failed'] is None else r['failed']} | {cell(dl)} | {cell(owners(r))} |")
    for key, title in (("by_skill", "By skill (what its briefs produce)"), ("by_model", "By model")):
        k = key.split("_", 1)[1]
        out += ["", f"## {title}", "", f"| {k.capitalize()} | Agents | Calls | Failure rate | Brief | Execution | Host | Model | Clean |", "|---|---|---|---|---|---|---|---|---|"]
        out += [rollup_line(x) for x in roll[key]]
    out += ["", "## Budgets from what was observed", "", "| Agent type | Runs | Calls min-max | Suggested budget |", "|---|---|---|---|"]
    out += [f"| {cell(x['type'])} | {x['runs']} | {x['min']}-{x['max']} | {x['suggested_budget']}{' (' + x['note'] + ')' if x['note'] else ''} |" for x in bud]
    for r in rows:
        out += ["", f"## {r['agent']}: {r['description']}", "", f"source: {r['source']}"
                + (f"; {r['minutes']} min" if r["minutes"] else "") + (f"; brief written under skill {r['skill']}" if r.get("skill") else ""), ""]
        if r.get("board"):
            bd = r["board"]
            out.append(f"- board: {bd['reads']} reads, {bd['writes']} writes" + (f"; re-derived {', '.join(bd['reran_known'])}" if bd["reran_known"] else ""))
        for k in CAUSES:
            for x in (r.get("causes") or {}).get(k, []):
                out.append(f"- **{k}**: {x}")
        if r["flags"]:
            out.append("- flags: " + "; ".join(r["flags"]))
        out += ["", "Asks in the brief:"]
        out += [f"- {x}" for x in r["asks"]] or ["- (no list; read the brief)"]
        out += ["", "Brief:", "", "> " + "\n> ".join((r["brief"] or "(none)")[:2500].splitlines()), "", "Steps:"]
        out += [f"{i}. {s}" for i, s in enumerate(r["steps"], 1)] or ["(no transcript)"]
        if r["failed_calls"]:
            out += ["", "Failed:"] + [f"- {x}" for x in r["failed_calls"]]
        out += ["", "Report:", "", "> " + "\n> ".join((r["report"] or "(empty)")[:2500].splitlines())]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--everywhere", action="store_true", help="look in every project's transcripts, not only this folder's")
    ap.add_argument("--reports")
    ap.add_argument("--board", help="the run's board.jsonl (/retro:board): facts already known when each agent started")
    ap.add_argument("--skill", help="only agents started while this skill was loaded (with --all: an eval of that skill across sessions)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--no-mask", action="store_true")
    a = ap.parse_args(argv)
    cwd = Path(a.cwd).resolve()
    sessions: list[str] = []
    if a.session:
        sessions = [a.session]
    elif a.latest or a.all or not a.reports:
        found = [str(f) for f in T.candidates(str(cwd), everywhere=a.everywhere) if f.suffix == ".jsonl"]
        sessions = found if a.all else found[:1]
        if not sessions and not a.reports:
            print("No session transcript found. Pass its path, or --reports DIR with end-of-run report files.", file=sys.stderr)
            return 2
    rows, notes = [], []
    all_board_facts = load_board(a.board)
    for s in sessions:
        sess = T.load(s)
        notes += sess.notes
        board_facts = all_board_facts
        if all_board_facts and len(sessions) > 1:
            first = min(f.get("ts", "") for f in all_board_facts)
            inside = sess.start and sess.end and (T.seconds_between(sess.start, first) or 0) >= 0 and (T.seconds_between(first, sess.end) or 0) >= 0
            board_facts = all_board_facts if inside else []
        for x in sess.agents:
            before = [c for c in sess.calls if c.ts and x.launched and c.ts < x.launched and c.tool not in T.AGENT_TOOLS]
            skills = [str(c.input.get("skill")) for c in before if c.tool == "Skill" and c.input.get("skill")]
            ctx = {"main_before": {norm_call(c) for c in before if c.tool in DISCOVERY_TOOLS},
                   "skill": (f"{x.subagent_type.split(':')[0]} (plugin)" if x.started_by == "plugin" and ":" in x.subagent_type
                             else skills[-1] if skills else None), "board_facts": board_facts,
                   "board_in_use": bool(board_facts) or any(BOARD_GET_RE.search(str(c.input.get("command", ""))) or BOARD_ADD_RE.search(str(c.input.get("command", "")))
                                                           for y in sess.agents for c in y.calls)}  # this session's agents only
            rows.append(audit_run(x, cwd, ctx))
    shared_discovery(rows)
    if a.skill:
        rows = [r for r in rows if (r.get("skill") or "").split(":")[-1] == a.skill.split(":")[-1]]
    if a.reports:
        files = sorted(Path(a.reports).glob("*.json"))
        index: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            for key in {r["agent"], r.get("agent_id"), r.get("brief_label"), r.get("description")} - {None, ""}:
                index[key].append(r)
        for f in files:
            try:
                rep = from_report_file(f)
            except (OSError, json.JSONDecodeError, ValueError) as e:
                notes.append(f"{f.name}: not a report file ({type(e).__name__})")
                continue
            found = {id(r): r for key in {rep["agent"], rep.get("brief_id")} - {None, ""} for r in index.get(key, [])}
            match = next(iter(found.values())) if len(found) == 1 else None
            if len(found) > 1:
                rep["flags"].append(f"ambiguous: {len(found)} agents match {rep['agent']!r}; not joined to any")
            elif not found:
                rep["flags"].append("unmatched: no agent of the transcript has this name or brief label")
            if match:
                match["self_report_file"] = f.name
                if rep["self_reported_calls"] is not None and match["calls"] is not None and rep["self_reported_calls"] != match["calls"]:
                    match["flags"].append(f"report file says {rep['self_reported_calls']} calls, transcript shows {match['calls']}")
            else:
                rows.append(rep)
        if not files:
            notes.append(f"no report files in {a.reports}")
    bud = budgets(rows)
    roll = {"by_skill": rollup(rows, "skill"), "by_model": rollup(rows, "model")}
    text = json.dumps({"sessions": sessions, "notes": notes, "agents": rows, "budgets": bud, **roll}, ensure_ascii=False, indent=2) if a.json \
        else render(rows, bud, sessions[0] if len(sessions) == 1 else None, notes, roll)
    if not a.no_mask:
        text = T.mask(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Saved: {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
