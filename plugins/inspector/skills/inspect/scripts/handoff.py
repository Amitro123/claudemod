#!/usr/bin/env python3
"""Turn the readers' leads into a handoff list, word for word.

The open leads go to someone who will act on them (a code agent, an issue, a person). Retyping them
is where accuracy is lost: a "suspect" becomes a "read", and a consequence nobody traced creeps in.
This copies each lead's words and levels from the case cards (their `complete.siblings`) or from an
investigator's list of leads, and lets the caller only drop a lead or lower a level. A note the
caller adds is marked as theirs and unverified.

    python handoff.py --cards <folder of cards> | - [--out file.md] [--title T]
                      [--lower 'path:line=suspect'] [--drop 'path:line'] [--note 'path:line=text']
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crosscheck import read_cards  # noqa: E402

RANK = {"reproduced": 3, "read": 2, "suspect": 1, "unverified": 0}


def leads_of(items: list[dict]) -> list[dict]:
    """A case card gives its complete.siblings; an investigator's list gives the leads themselves."""
    out = []
    for x in items:
        sibs = (x.get("complete") or {}).get("siblings") if isinstance(x.get("complete"), dict) else None
        for s in (sibs if sibs is not None else [x] if "where" in x else []):
            out.append({**s, "case": x.get("case") or x.get("unit") or s.get("case") or ""})
    return out


def level_word(v: object) -> str:
    v = str(v or "").strip().lower()
    return next((k for k in RANK if v.startswith(k)), v or "unverified")


def cell(v: object) -> str:
    return " ".join(str(v if v is not None else "").split()).replace("|", "/")


def needs_host_check(s: dict) -> bool:
    """The lead's impact depends on host/runtime behaviour nobody observed: a boolean or a flag in `flags`."""
    flags = s.get("flags")
    flags = [flags] if isinstance(flags, str) else flags or []
    return bool(s.get("needs_host_check")) or "needs-host-check" in [str(f).strip().lower() for f in flags]


def build(leads: list[dict], lower: dict[str, str], drop: set[str], notes: dict[str, str], title: str,
          warnings: list[str] | None = None) -> tuple[str, list[str]]:
    errors, rows = [], []
    warnings = warnings if warnings is not None else []
    for s in leads:
        where = cell(s.get("where"))
        if where in drop:
            continue
        lvl = level_word(s.get("level"))
        if where in lower:
            new = level_word(lower[where])
            if RANK.get(new, 0) > RANK.get(lvl, 0):
                errors.append(f"{where}: --lower may not raise {lvl} to {new}")
            else:
                lvl = new
        imp = s.get("impact") if isinstance(s.get("impact"), dict) else {"what": s.get("impact"), "level": None}
        impact = cell(imp.get("what")) or "not stated"
        ilvl = level_word(imp.get("level")) if imp.get("what") else "unverified"
        src = cell(imp.get("source"))
        if str(s.get("category") or "").strip().lower() == "security" and ilvl == "unverified":
            warnings.append(f"{where}: category security but the impact is unverified; "
                            "without an observed or traced consequence it is broken-flow, cost or other")
        shown = f"{lvl} [needs-host-check]" if needs_host_check(s) else lvl
        impact_cell = f"{impact} [{ilvl}{': ' + src if src and ilvl != 'unverified' else ''}]"
        note = f" **Note added after the readers, unverified:** {cell(notes[where])}" if where in notes else ""
        rows.append((RANK.get(lvl, 0), f"| {shown} | `{where}` | {cell(s.get('what'))}{note} | {impact_cell} | "
                                         f"{cell(s.get('breaks'))} | {cell(s.get('change'))} | {cell(s.get('test'))} | {cell(s.get('case'))} |"))
    rows.sort(key=lambda r: -r[0])
    L = [f"# {title}", "",
         "Copied word for word from the inspector's case readers: each lead's level, and its impact's own",
         "level, as they gave them. A level here was only ever lowered, never raised. Everything came from",
         "a model reading repository history and code: verify each claim before you change code.", "",
         "| Level | Where | What breaks | Impact [its level: source] | Breaks | The change | The test | From case |",
         "|---|---|---|---|---|---|---|---|"]
    L += [r for _, r in rows] or ["| - | - | no leads | - | - | - | - | - |"]
    return "\n".join(L) + "\n", errors


def pairs(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values:
        k, _, val = v.rpartition("=")
        if k:
            out[k.strip().strip("`")] = val.strip()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", required=True, help="a folder of cards (*.json), or - for stdin (cards or leads)")
    ap.add_argument("--out", help="write the list here too")
    ap.add_argument("--title", default="Open leads, for whoever fixes them")
    ap.add_argument("--lower", action="append", default=[], help="'path:line=level': lower that lead's level")
    ap.add_argument("--drop", action="append", default=[], help="'path:line': leave that lead out")
    ap.add_argument("--note", action="append", default=[], help="'path:line=text': add a note, marked as yours and unverified")
    a = ap.parse_args(argv)
    items, bad = read_cards(a.cards)
    if bad:
        print("handoff.py: invalid cards: " + "; ".join(bad), file=sys.stderr)
        return 2
    warns: list[str] = []
    text, errors = build(leads_of(items), pairs(a.lower), {d.strip().strip("`") for d in a.drop}, pairs(a.note), a.title, warns)
    for w in warns:
        print(f"handoff.py: warning: {w}", file=sys.stderr)
    for e in errors + [f"unreadable: {b}" for b in bad]:
        print(f"handoff.py: {e}", file=sys.stderr)
    if errors:
        return 2
    if a.out:
        try:
            from evidence import write
            write(a.out, text)
        except OSError as e:
            print(f"handoff.py: not saved ({e}); the list is below", file=sys.stderr)
            sys.stdout.write(text)
            return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
