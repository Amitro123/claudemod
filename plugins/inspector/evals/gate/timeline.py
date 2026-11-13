#!/usr/bin/env python3
"""Print the timeline of an inspector run from the files' mtimes. Stdlib only, read-only on the run folder.

    python timeline.py --run RUN_FOLDER [--json]

Reads `<run>/plan/expect.json` (written by skills/inspect/scripts/plan.py) for the phases, the agents of each
phase and the files each agent must leave, then stats those files. Steps, in order: collect (evidence.json, the
start), each planned agent phase (brief, investigate and verify, one entry per wave), and the script steps
between them: merge (leads.json, dedupe.md), plan verify (plan/chunk-*.json), merge verdicts (merged.json),
handoff (open-bugs.md). A step starts when the one before ended, except a later wave of a phase: its agents
start as slots free up, so it starts when the first agent of the wave before finished. A step ends at its newest file.
Per agent: the time of its newest file relative to the phase start. Critical path: the slowest agent of each phase.

Limits: an mtime is the LAST write. A card is written first as a stub, then final; only the final write is seen,
so a card's time is when the reader finished it, not when it started. A file rewritten later (a merge run again)
moves its step. An agent with no output file (the docs-checker returns text) has no time.
Exit 0 every planned file is present, 1 at least one is missing (the timeline is still printed),
2 unreadable input (no run folder, no or invalid plan/expect.json).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time


class Invalid(Exception):
    pass


def mtime(run: str, rel: str) -> float | None:
    try:
        return os.path.getmtime(os.path.join(run, rel))
    except OSError:
        return None


def load_expect(run: str) -> dict:
    if not os.path.isdir(run):
        raise Invalid(f"{run}: not a folder")
    path = os.path.join(run, "plan", "expect.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise Invalid(f"plan/expect.json: cannot read ({e}); plan.py writes it") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("phases"), list) or \
            not all(isinstance(p, dict) for p in doc["phases"]):
        raise Invalid("plan/expect.json: expected an object with `phases`, a list of objects")
    return doc


def script_step(run: str, name: str, files: list[str]) -> dict:
    return {"name": name, "kind": "script", "files": {f: mtime(run, f) for f in files}}


def agent_phase(run: str, p: dict) -> dict:
    wave = f" (wave {p['wave']} of {p['waves']})" if "wave" in p else ""
    agents = []
    dispatch = p.get("dispatch") or []
    for d in dispatch if isinstance(dispatch, list) else []:
        if not isinstance(d, dict):
            continue
        outs = d.get("outputs") if isinstance(d.get("outputs"), list) else []
        label = str(d.get("prompt") or d.get("agent") or "?").removesuffix(".prompt.md")
        agents.append({"agent": d.get("agent"), "label": label, "files": {o: mtime(run, o) for o in outs}})
    if not dispatch and isinstance(p.get("outputs"), list):  # no per-agent record: one row for the phase
        agents.append({"agent": None, "label": p.get("name"), "files": {o: mtime(run, o) for o in p["outputs"]}})
    return {"name": f"{p.get('name')}{wave}", "kind": "agents", "agents": agents, "wave": p.get("wave", 1)}


def steps_of(run: str, exp: dict) -> list[dict]:
    steps = [script_step(run, "collect", ["evidence.json"])]
    phases = exp["phases"]
    parallel = exp.get("mode") == "parallel"
    inv = [i for i, p in enumerate(phases) if p.get("name") == "investigate"]
    for i, p in enumerate(phases):
        if p.get("name") == "verify" and (i == 0 or phases[i - 1].get("name") != "verify"):
            chunks = [c.get("chunk") for c in exp.get("verifier_chunks") or [] if isinstance(c, dict) and c.get("chunk")]
            steps.append(script_step(run, "plan verify", chunks or ["plan/expect.json"]))
        if p.get("dispatch") or p.get("outputs"):  # a verify phase with no lead starts no agent
            steps.append(agent_phase(run, p))
        if parallel and inv and i == inv[-1]:
            steps.append(script_step(run, "merge", ["leads.json", "dedupe.md"]))
    if not any(p.get("name") == "verify" for p in phases):
        steps.append({"name": "verify", "kind": "unplanned"})
        return steps
    steps.append(script_step(run, "merge verdicts", ["merged.json"]))
    steps.append(script_step(run, "handoff", ["open-bugs.md"]))
    return steps


def timeline(run: str) -> dict:
    exp = load_expect(run)
    steps = steps_of(run, exp)
    seen = [t for s in steps for t in all_times(s) if t is not None]
    t0 = steps[0]["files"]["evidence.json"]
    notes = []
    if t0 is None:
        t0 = min(seen) if seen else None
        notes.append("evidence.json missing: the run starts at the oldest file found")
    missing, crit = [], []
    prev_end = t0
    first_free = None          # when the first agent of the wave before finished: a later wave starts then
    for s in steps:
        if s["kind"] == "unplanned":
            notes.append("verify not planned yet (plan.py --phase verify): the timeline stops at the merge")
            continue
        s["start"] = first_free if s.get("wave", 1) > 1 and first_free is not None else prev_end
        if s["kind"] == "agents":
            for a in s["agents"]:
                ts = [t for t in a["files"].values() if t is not None]
                a["end"] = max(ts) if ts else None
                a["missing"] = [f for f, t in a["files"].items() if t is None]
                a["rel"] = None if a["end"] is None or s["start"] is None else round(a["end"] - s["start"], 1)
                missing += a["missing"]
            done = [a for a in s["agents"] if a["end"] is not None]
            s["end"] = max((a["end"] for a in done), default=None)
            first_free = min((a["end"] for a in done), default=None)
            if done and s["start"] is not None:
                slow = max(done, key=lambda a: a["end"])
                crit.append({"phase": s["name"], "agent": slow["label"], "seconds": slow["rel"]})
        else:
            ts = [t for t in s["files"].values() if t is not None]
            s["end"] = max(ts) if ts else None
            s["missing"] = [f for f, t in s["files"].items() if t is None]
            missing += s["missing"]
        s["seconds"] = None if s["start"] is None or s["end"] is None else round(s["end"] - s["start"], 1)
        if s["seconds"] is not None and s["seconds"] < 0:
            notes.append(f"{s['name']}: ends before the step before it (a file there was rewritten later)")
        if s["end"] is not None:
            prev_end = s["end"] if prev_end is None else max(prev_end, s["end"])
    if any(s["kind"] == "agents" and any(f.startswith("cards/") for a in s["agents"] for f in a["files"]) for s in steps):
        notes.append("cards: the final write's time only; the first stub write is not recoverable from mtime")
    end = max(seen) if seen else None
    return {"run": run.replace("\\", "/"), "mode": exp.get("mode"), "start": t0, "end": end,
            "seconds": None if t0 is None or end is None else round(end - t0, 1),
            "steps": [s for s in steps if s["kind"] != "unplanned"], "critical_path": crit,
            "missing": missing, "notes": notes}


def all_times(s: dict) -> list:
    if s["kind"] == "agents":
        return [t for a in s["agents"] for t in a["files"].values()]
    return list(s.get("files", {}).values())


def clock(t: float | None) -> str:
    return "--:--:--" if t is None else time.strftime("%H:%M:%S", time.localtime(t))


def dur(sec: float | None) -> str:
    if sec is None:
        return "?"
    sign, sec = ("-" if sec < 0 else ""), abs(sec)
    return f"{sign}{int(sec // 60)}m{sec % 60:04.1f}s"


def text(tl: dict) -> str:
    L = [f"Run {tl['run']} ({tl['mode']}): {clock(tl['start'])} -> {clock(tl['end'])}, {dur(tl['seconds'])}", ""]
    L.append(f"{'step':<28} {'start':>8} {'end':>8} {'duration':>10}")
    for s in tl["steps"]:
        L.append(f"{s['name']:<28} {clock(s['start']):>8} {clock(s['end']):>8} {dur(s['seconds']):>10}"
                 + (f"   missing: {', '.join(s['missing'])}" if s.get("missing") else ""))
        if s["kind"] == "agents":
            for a in sorted(s["agents"], key=lambda a: (a["end"] is None, a["end"] or 0)):
                files = ", ".join(a["files"]) or "no file"
                miss = f"   missing: {', '.join(a['missing'])}" if a["missing"] else ""
                L.append(f"  {a['label']:<26} {'+' + dur(a['rel']) if a['rel'] is not None else '?':>19}  {files}{miss}")
    L += ["", "Critical path (slowest agent per phase):"]
    L += [f"- {c['phase']}: {c['agent']} {dur(c['seconds'])}" for c in tl["critical_path"]] or ["- no agent finished"]
    if tl["missing"]:
        L += ["", f"Missing planned files ({len(tl['missing'])}): {', '.join(tl['missing'])}"]
    if tl["notes"]:
        L += ["", "Notes:"] + [f"- {n}" for n in tl["notes"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="the run folder (the collector's --out)")
    ap.add_argument("--json", action="store_true", help="print the timeline as JSON (times are epoch seconds)")
    a = ap.parse_args(argv)
    try:
        tl = timeline(a.run)
    except Invalid as e:
        print(f"timeline.py: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(tl, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(text(tl))
    return 1 if tl["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
