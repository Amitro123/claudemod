"""Read an agent session's transcript into one shape: tool calls, their results, user prompts and sub-agent runs.

Formats:
- claude-jsonl: Claude Code's `~/.claude/projects/<project>/<session>.jsonl`, with sub-agents in
  `<session>/subagents/agent-<id>.jsonl` (+ `.meta.json`), or as `isSidechain` rows of the main file.
- jsonl: one message per line with `role` and `content` (or `message: {role, content}`); content is text or
  Anthropic-style blocks (`tool_use`, `tool_result`, `text`) or OpenAI-style `tool_calls` / `role: tool`.
- text: a pasted or exported transcript (markdown or plain text, e.g. a Cursor chat export). Commands are taken
  from backtick spans and fenced blocks; results are not paired with calls, so `ok` is unknown.

Stdlib only, so the scripts run wherever Python 3.9+ does (Claude Code, Cursor, a plain terminal).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

AGENT_TOOLS = {"Agent", "Task"}
HANDBACK_TOOLS = {"SubagentHandback"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


@dataclass
class Call:
    id: str
    tool: str
    input: dict
    ts: str | None = None
    result: str = ""
    ok: bool | None = None  # None: no result seen, or a text transcript
    result_ts: str | None = None

    def brief(self, width: int = 160) -> str:
        i = self.input
        s = i.get("command") or i.get("file_path") or i.get("path") or i.get("pattern") or i.get("url") \
            or i.get("query") or i.get("description") or i.get("skill") or json.dumps(i, ensure_ascii=False)
        s = " ".join(str(s).split())
        return s if len(s) <= width else s[: width - 1] + "…"


@dataclass
class AgentRun:
    call_id: str
    agent_id: str | None
    description: str
    subagent_type: str
    model: str | None
    prompt: str
    status: str | None = None
    reported_tool_uses: int | None = None
    report: str = ""
    transcript: str | None = None
    calls: list[Call] = field(default_factory=list)
    finished: bool | None = None
    start: str | None = None
    end: str | None = None
    launched: str | None = None  # the main agent's call time
    started_by: str = "main"  # "plugin" for one a plugin or mod started, with no Agent call of the main agent
    dispatch: int = 1  # which dispatch of this agent id (a resume is the next), of `dispatches`
    dispatches: int = 1

    @property
    def work_calls(self) -> list[Call]:
        return [c for c in self.calls if c.tool not in HANDBACK_TOOLS]


@dataclass
class Session:
    path: str
    format: str
    prompts: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)  # assistant text, in order
    calls: list[Call] = field(default_factory=list)
    agents: list[AgentRun] = field(default_factory=list)
    start: str | None = None
    end: str | None = None
    notes: list[str] = field(default_factory=list)


def _text_of(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(str(b.get("text", "")))
                elif "content" in b:
                    out.append(_text_of(b["content"]))
            else:
                out.append(str(b))
        return "\n".join(x for x in out if x)
    if isinstance(content, dict):
        return _text_of(content.get("content") or content.get("text"))
    return str(content)


def _is_meta_prompt(text: str) -> bool:
    t = text.lstrip()
    return not t or t.startswith(("<system-reminder", "<local-command", "<command-", "Caveat:"))


def _rows(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                rows.append(r)
    return rows


def _usage_from_text(text: str) -> tuple[str | None, int | None]:
    aid = re.search(r"agentId:\s*([A-Za-z0-9_-]+)", text)
    n = re.search(r"tool_uses:\s*(\d+)", text)
    return (aid.group(1) if aid else None, int(n.group(1)) if n else None)


def _parse_claude_rows(rows: list[dict], sess: Session, sidechain: bool) -> dict[str, Call]:
    by_id: dict[str, Call] = {}
    for r in rows:
        if bool(r.get("isSidechain")) != sidechain and "isSidechain" in r:
            continue
        ts = r.get("timestamp")
        if ts:
            sess.start = sess.start or ts
            sess.end = ts
        msg = r.get("message") or {}
        content = msg.get("content")
        if r.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    c = Call(id=b.get("id", ""), tool=b.get("name", "?"), input=b.get("input") or {}, ts=ts)
                    by_id[c.id] = c
                    sess.calls.append(c)
                elif b.get("type") == "text" and b.get("text", "").strip():
                    sess.texts.append(b["text"])
        elif r.get("type") == "user":
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        c = by_id.get(b.get("tool_use_id", ""))
                        if c is None:
                            continue
                        c.result = _text_of(b.get("content"))
                        c.ok = not bool(b.get("is_error"))
                        c.result_ts = ts
                        tur = r.get("toolUseResult")
                        if c.tool in AGENT_TOOLS and isinstance(tur, dict):
                            c.input = {**c.input, "_result": tur}
            elif not r.get("isMeta"):
                t = _text_of(content)
                if not _is_meta_prompt(t):
                    sess.prompts.append(t)
    return by_id


def _agent_from_call(c: Call, session_dir: Path | None, main_rows: list[dict]) -> AgentRun:
    tur = c.input.get("_result") if isinstance(c.input.get("_result"), dict) else {}
    aid, n = _usage_from_text(c.result)
    a = AgentRun(call_id=c.id, agent_id=tur.get("agentId") or aid, description=c.input.get("description", ""),
                 subagent_type=c.input.get("subagent_type") or tur.get("agentType") or "general-purpose",
                 model=c.input.get("model"), prompt=c.input.get("prompt", ""), status=tur.get("status"),
                 reported_tool_uses=n if n is not None else tur.get("totalToolUseCount"), start=c.ts, end=c.result_ts, launched=c.ts)
    hb = tur.get("handbackReport")
    if isinstance(hb, dict):
        a.report = hb.get("text", "")
    elif isinstance(tur.get("content"), list):
        a.report = _text_of(tur["content"])
    if a.agent_id and session_dir is not None:
        f = session_dir / "subagents" / f"agent-{a.agent_id}.jsonl"
        meta = session_dir / "subagents" / f"agent-{a.agent_id}.meta.json"
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                a.finished = m.get("finished")
                a.model = a.model or m.get("model")
                a.subagent_type = m.get("agentType") or a.subagent_type
            except (OSError, json.JSONDecodeError):
                pass
        if f.exists():
            sub = Session(path=str(f), format="claude-jsonl")
            _parse_claude_rows(_rows(f), sub, sidechain=True)
            a.transcript, a.calls = str(f), sub.calls
            a.start, a.end = sub.start or a.start, sub.end or a.end
    if not a.calls and a.agent_id:
        side = [r for r in main_rows if r.get("isSidechain") and r.get("agentId") == a.agent_id]
        if side:
            sub = Session(path="(sidechain rows)", format="claude-jsonl")
            _parse_claude_rows(side, sub, sidechain=True)
            a.transcript, a.calls = "(sidechain rows of the main transcript)", sub.calls
    if not a.report:
        for x in a.calls:
            if x.tool in HANDBACK_TOOLS:
                a.report = str(x.input.get("message", ""))
        if not a.report:
            a.report = c.result
    return a


def _instant(ts: str | None) -> float | None:
    """An ISO timestamp as seconds since the epoch: `Z` or `+00:00`, any number of fraction digits (Python
    3.9's fromisoformat takes only 3 or 6), a naive time read as UTC. None when it isn't one."""
    if not ts:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$", ts.strip())
    if not m:
        return None
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    tz = m.group(3) or "+00:00"
    tz = "+00:00" if tz == "Z" else (tz if ":" in tz else f"{tz[:3]}:{tz[3:]}")
    try:
        return datetime.fromisoformat(f"{m.group(1).replace(' ', 'T')}.{frac}{tz}").timestamp()
    except ValueError:
        return None


def _split_resumed(agents: list[AgentRun]) -> None:
    """A resumed agent is dispatched again under the same id, and each dispatch loaded its whole transcript.
    Each dispatch keeps its own brief and gets the calls from its launch to the next dispatch's: every call is
    counted once, against the brief it was made under."""
    by_id: dict[str, list[AgentRun]] = {}
    for a in agents:
        if a.agent_id:
            by_id.setdefault(a.agent_id, []).append(a)
    for runs in by_id.values():
        if len(runs) < 2:
            continue
        # By the instant, not the string: "…:01Z" and "…:01.5+00:00" don't sort as text.
        runs.sort(key=lambda a: _instant(a.launched) or 0.0)
        calls = runs[0].calls
        for i, a in enumerate(runs):
            start = _instant(a.launched) if i else None
            end = _instant(runs[i + 1].launched) if i + 1 < len(runs) else None
            a.calls = [c for c in calls if (start is None or (_instant(c.ts) or 0.0) >= start) and (end is None or (_instant(c.ts) or 0.0) < end)]
            a.dispatch = i + 1
            a.dispatches = len(runs)


def _agents_without_a_call(session_dir: Path, seen: set[str]) -> list[AgentRun]:
    """Sub-agents a plugin or mod started (the factory's reviewers): their transcripts sit in `subagents/` with no
    Agent call in the main transcript. The brief is the first user message, the type and model come from the meta."""
    sub = session_dir / "subagents"
    out = []
    for f in sorted(sub.glob("agent-*.jsonl")) if sub.is_dir() else []:
        aid = f.stem[len("agent-"):]
        if aid in seen:
            continue
        meta = {}
        m = sub / f"agent-{aid}.meta.json"
        if m.exists():
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        rows = _rows(f)
        s = Session(path=str(f), format="claude-jsonl")
        _parse_claude_rows(rows, s, sidechain=True)
        brief = next((_text_of(r["message"]["content"]) for r in rows if r.get("type") == "user" and not r.get("isMeta")
                      and isinstance((r.get("message") or {}).get("content"), str)), "")
        a = AgentRun(call_id=f"file:{aid}", agent_id=aid, description=meta.get("description", ""),
                     subagent_type=meta.get("agentType") or "?", model=meta.get("model"), prompt=brief,
                     status="completed" if meta.get("finished") else None, transcript=str(f), calls=s.calls,
                     finished=meta.get("finished"), start=s.start, end=s.end, launched=s.start)
        a.started_by = "plugin" if meta.get("pluginSteered") or meta.get("modShaped") else "unknown"
        hb = [c for c in s.calls if c.tool in HANDBACK_TOOLS]
        a.report = str(hb[-1].input.get("message", "")) if hb else (s.texts[-1] if s.texts else "")
        out.append(a)
    return out


def _load_claude(path: Path) -> Session:
    rows = _rows(path)
    sess = Session(path=str(path), format="claude-jsonl")
    _parse_claude_rows(rows, sess, sidechain=False)
    session_dir = path.with_suffix("")
    for c in sess.calls:
        if c.tool in AGENT_TOOLS:
            sess.agents.append(_agent_from_call(c, session_dir if session_dir.is_dir() else None, rows))
    _split_resumed(sess.agents)
    sess.agents += _agents_without_a_call(session_dir, {a.agent_id for a in sess.agents if a.agent_id})
    for a in sess.agents:
        if not a.calls:
            sess.notes.append(f"agent {a.agent_id or a.call_id}: no transcript of its own found; only its brief and report")
    return sess


def _load_generic_jsonl(path: Path) -> Session:
    sess = Session(path=str(path), format="jsonl")
    by_id: dict[str, Call] = {}
    for r in _rows(path):
        m = r.get("message") if isinstance(r.get("message"), dict) else r
        role = m.get("role") or r.get("type")
        content = m.get("content")
        ts = r.get("timestamp") or m.get("timestamp")
        if ts:
            sess.start = sess.start or ts
            sess.end = ts
        if role == "assistant":
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        c = Call(id=b.get("id", f"c{len(sess.calls)}"), tool=b.get("name", "?"), input=b.get("input") or {}, ts=ts)
                        by_id[c.id] = c
                        sess.calls.append(c)
                    elif isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                        sess.texts.append(b["text"])
            elif isinstance(content, str) and content.strip():
                sess.texts.append(content)
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"raw": fn.get("arguments")}
                c = Call(id=tc.get("id", f"c{len(sess.calls)}"), tool=fn.get("name", "?"), input=args if isinstance(args, dict) else {"raw": args}, ts=ts)
                by_id[c.id] = c
                sess.calls.append(c)
        elif role == "tool":
            c = by_id.get(m.get("tool_call_id", ""))
            if c:
                c.result, c.ok, c.result_ts = _text_of(content), None, ts
        elif role == "user":
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        c = by_id.get(b.get("tool_use_id", ""))
                        if c:
                            c.result, c.ok, c.result_ts = _text_of(b.get("content")), not bool(b.get("is_error")), ts
            else:
                t = _text_of(content)
                if not _is_meta_prompt(t):
                    sess.prompts.append(t)
    return sess


CMD_WORDS = ("git ", "gh ", "az ", "python", "py ", "pip ", "npm ", "npx ", "node ", "curl ", "kubectl ", "docker ",
             "terraform ", "bicep ", "pwsh", "powershell", "$env:", "$", "Get-", "Set-", "Invoke-", "rg ", "grep ",
             "gitleaks", "pytest", "make ", "cargo ", "go ", "dotnet ")
PROBLEM_RE = re.compile(r"\b(failed|was blocked|were blocked|got stripped|stripped of|was truncated|truncated at|corrupted|"
                        r"timed out|not on PATH|exit code [1-9]|exit 1|was rejected|returned 0 commits|is missing|"
                        r"could not|couldn't|unexplained|not recognized|access denied|403|401)\b", re.I)


def _load_text(path: Path) -> Session:
    sess = Session(path=str(path), format="text")
    text = path.read_text(encoding="utf-8", errors="replace")
    sess.notes.append("text transcript: calls are taken from backtick spans and fenced blocks; their results are "
                      "not paired, so a failure is read from the prose that follows")
    blocks = re.split(r"\n\s*\n", text)
    pending: Call | None = None
    for i, para in enumerate(blocks):
        p = para.strip()
        if not p:
            continue
        fenced = re.findall(r"```(?:\w+)?\n(.*?)```", p, flags=re.S)
        whole = [ln.strip()[1:-1] for ln in p.splitlines()
                 if len(ln.strip()) > 4 and ln.strip().startswith("`") and ln.strip().endswith("`") and not ln.strip().startswith("```")]
        cmds = [x.strip() for x in fenced + whole if x.strip().startswith(CMD_WORDS) or x.strip().startswith(("&", "@'"))]
        if cmds:
            for x in cmds:
                c = Call(id=f"t{len(sess.calls)}", tool="Shell", input={"command": x})
                sess.calls.append(c)
                pending = c
            prose = "\n".join(ln for ln in p.splitlines() if not (ln.strip().startswith("`") and ln.strip().endswith("`"))
                              and not set(ln.strip()) <= set("-"))
            if not prose.strip():
                continue
            p = prose.strip()
        if pending is not None and len(pending.result) < 3000:
            pending.result = (pending.result + "\n" + p).strip()
        sess.texts.append(p)
        if i == 0:
            sess.prompts.append(p)
    return sess


def detect(path: Path) -> str:
    if path.suffix.lower() == ".jsonl":
        for r in _rows(path)[:50]:
            if "sessionId" in r and ("parentUuid" in r or r.get("type") in ("user", "assistant", "summary")):
                return "claude-jsonl"
        return "jsonl"
    return "text"


def load(path: str | os.PathLike, fmt: str | None = None) -> Session:
    p = Path(path)
    fmt = fmt or detect(p)
    if fmt == "claude-jsonl":
        return _load_claude(p)
    if fmt == "jsonl":
        return _load_generic_jsonl(p)
    return _load_text(p)


def project_slug(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def candidates(cwd: str | None = None, home: str | None = None, everywhere: bool = False) -> list[Path]:
    """Known transcript locations, newest first, for the project at `cwd` only: Claude Code's folder for that path,
    and a Cursor project folder whose name is that path's (Cursor's `~/.cursor/projects/<name>/agent-transcripts/`,
    unverified on every version). No match is an empty list, never another project's transcript. `everywhere`
    (or no `cwd`) lists every project's."""
    h = Path(home or Path.home())
    found: list[Path] = []
    base = h / ".claude" / "projects"
    cur = h / ".cursor" / "projects"
    scoped = bool(cwd) and not everywhere
    if scoped:
        d = base / project_slug(cwd)
        found += list(d.glob("*.jsonl")) if d.is_dir() else []
    elif base.is_dir():
        found += list(base.glob("*/*.jsonl"))
    if cur.is_dir():
        want = _norm(project_slug(cwd)) if scoped else None
        for d in cur.glob("*/agent-transcripts"):
            if want is not None and _norm(d.parent.name) != want:
                continue
            found += [f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in (".jsonl", ".txt", ".md", ".json")]
    return sorted(set(found), key=lambda f: f.stat().st_mtime, reverse=True)


def seconds_between(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    try:
        return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return None


# The local part starts where a run of its characters starts (not at every word boundary inside the run: a long
# `a.a.a.` run with no @ was scanned to its end from each boundary, quadratic; issue #196).
EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
GUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Token shapes start at a non-alphanumeric (an underscore or hyphen before one is a file-name joint, not a word).
# Kept the same as inspector's copy (decide.py): its #199 added sk_/rk_ live|test, npm_, AIza and ASIA, and the
# 2026-11-25 inspector run found retro without them.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                      r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|(?:AKIA|ASIA)[0-9A-Z]{16}|"
                      r"sk-[A-Za-z0-9_-]{20,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}|npm_[A-Za-z0-9]{30,}|"
                      r"AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*)")
# Any case (`bearer`, `BEARER`); the 16-character minimum keeps prose such as "the bearer of bad news" readable.
# No `\b` before the word: in the text json.dumps gives (`\nBearer`, Call.brief()'s fallback) a letter sits right
# before it, and the token went unmasked (review of #207). Nor before `x-api-key`, for the same reason.
BEARER_RE = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}")
# An X-Api-Key header in any case: the name (possibly quoted, as in JSON or a curl -H argument), then `:` or `=`, then the key.
X_API_KEY_RE = re.compile(r"""(?i)(x-api-key\\?["']?[ \t]*[:=][ \t]*\\?["']?)[^\s"'\\]+""")
# An Authorization header: the scheme word (Bearer, Basic, Negotiate, NTLM, any name) is consumed with the value, and
# both are hidden; the value stops at whitespace or a quote so a JSON string stays valid. And curl -u / --user
# credentials: a colon is required (so `sudo -u bob` and `git push -u origin` stay) but either side of it may be empty
# (`-u :PAT` Azure DevOps, `-u sk_live_x:` Stripe); `docker run -u 1000:1000` is masked too, on purpose.
# Same shapes as brain-hud's host_layout._SECRETS (a test compares them).
# The header name may be quoted (JSON, Python dict) and so may the value; the match stays on one line. A quoted
# curl credential cut off before its closing quote (digest text is cut) runs to the end of its line. An unquoted
# credential stops at a quote that closes a string (a quote followed by whitespace, a comma, a bracket, a colon or
# the end), but runs through a quote inside it (`pa"ss`). The argument-list form ["curl", "-u", "alice:pw"] is
# paired by ARGV_USER_RE in text and by mask_data in decoded JSON. A quote may carry a backslash (`\"`, the form
# json.dumps gives, which Call.brief() falls back to). An unquoted credential also stops at a shell separator
# (`;` `|` `&` `)`), so `curl -u a:pw;echo ok` keeps `echo ok`; a comma is NOT a stop: it is a legal password
# character, and `,more` lost after a credential is the safe side.
AUTH_HEADER_RE = re.compile(r"""(?i)\b(authorization\\?["']?[ \t]*:[ \t]*\\?["']?)(?:[A-Za-z][\w.-]*[ \t]+)?[^\s"'\\]+""")
CURL_USER_RE = re.compile(r"""(?<![^\s"'])(-u[ \t]*|--user(?:[ \t]+|=))"""
                          r"""(?:\\?"[^"\n]*:[^"\n]*(?:"|(?=\n)|\Z)|\\?'[^'\n]*:[^'\n]*(?:'|(?=\n)|\Z)"""
                          r"""|[^\s:"';|&)]*:(?:[^\s"';|&)]|["'](?=[^\s"',;:)\]}]))*)""")
# The argument-list text form: a backslash inside a string is part of it unless it escapes the closing quote. The
# user side excludes ':' so the first colon is the only candidate (no quadratic backtracking on colon-heavy lines).
# The single-backslash branch must not match a backslash that is followed by another one: that pair belongs to the
# `\\\\` branch alone. Without the `\\` in the guard the group is ambiguous and a run of N backslashes backtracked
# in 2^(N/2) ways (issue #196). The value also ends at a line end or the end of the text, after an optional backslash:
# a digest cuts long lines, and a list cut inside the value kept the password (issue #198).
ARGV_USER_RE = re.compile(r"""(\\?["'](?:-u|--user)\\?["']\s*,\s*\\?["'])(?:[^"'\\\n:]|\\\\|\\(?![\\"']))*:(?:[^"'\\\n]|\\\\|\\(?![\\"']))*(?=\\?(?:["']|\n|\Z))""")
SESSION_URL_RE = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9]+")
# The board's refusals, shared: a whole private-key block (to its END line, or to the end of the text), and the
# 52-character lowercase base32 shape of an Azure DevOps PAT.
# A key cut off before its END line stops at the end of the string it sits in (an unescaped quote: the text is
# often a JSON line) rather than taking the rest of the line with it.
PRIVATE_KEY_RE = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|(?=(?<!\\)")|\Z)', re.S)
ADO_PAT_RE = re.compile(r"(?<![A-Za-z0-9])[a-z2-7]{52}(?![A-Za-z0-9])")
HOME_RE = re.compile(r"(?i)(?<![\w/])([A-Z]:\\Users\\|/Users/|/home/)([^\\/\s'\"`\[]+)")


def mask_data(obj):
    """mask() over every string inside decoded JSON (keys too), structure kept: masking the serialized text
    can't tell a string's closing quote from an escaped one, and cut through JSON syntax."""
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, dict):
        return {mask_data(k) if isinstance(k, str) else k: mask_data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        out, after_flag = [], False
        for v in obj:
            # argument list ["curl", "-u", "alice:pw"]: the credential is the string after the flag
            out.append("[token]" if after_flag and isinstance(v, str) and ":" in v else mask_data(v))
            after_flag = isinstance(v, str) and v.strip() in ("-u", "--user")
        return out
    return obj


def mask(text: str) -> str:
    """Hide values a skill must never carry: private-key blocks, tokens and PAT shapes, Authorization and X-Api-Key headers,
    curl -u/--user credentials, emails (domain kept), GUIDs, session links, user names in paths. Heuristics: a secret in no known shape is not caught."""
    text = PRIVATE_KEY_RE.sub("[private-key]", text)
    text = TOKEN_RE.sub("[token]", text)
    text = ADO_PAT_RE.sub("[token]", text)
    text = AUTH_HEADER_RE.sub(r"\1[token]", text)
    text = ARGV_USER_RE.sub(r"\1[token]", text)
    text = CURL_USER_RE.sub(r"\1[token]", text)
    text = BEARER_RE.sub(r"\1[token]", text)
    text = X_API_KEY_RE.sub(r"\1[token]", text)
    text = EMAIL_RE.sub(lambda m: "[address]@" + m.group(1).lower(), text)
    text = GUID_RE.sub("[guid]", text)
    text = SESSION_URL_RE.sub("[session-link]", text)
    text = HOME_RE.sub(lambda m: m.group(1) + "[user]", text)
    return text
