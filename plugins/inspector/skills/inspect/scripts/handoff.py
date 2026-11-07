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
    """A case card gives its complete.siblings; an investigator's list gives the leads themselves.
    Each lead keeps who claimed it: the card's case reader, or the investigator."""
    out = []
    for n, x in enumerate(items, 1):
        sibs = (x.get("complete") or {}).get("siblings") if isinstance(x.get("complete"), dict) else None
        case = x.get("case") or x.get("unit") or ""
        if sibs is not None:
            by = x.get("by") or f"case-reader, card {n}" + (f" ({case})" if case else "")
            out += [{**s, "case": case, "by": s.get("by") or by} for s in sibs]
        elif "where" in x:
            out.append({**x, "case": x.get("case", ""), "by": x.get("by") or "investigator"})
    return out


def level_word(v: object) -> str:
    v = str(v or "").strip().lower()
    return next((k for k in RANK if v.startswith(k)), v or "unverified")


def cell(v: object) -> str:
    return " ".join(str(v if v is not None else "").split()).replace("|", "/")


def changes_cell(s: dict) -> str:
    alts = s.get("changes")
    if isinstance(alts, list) and alts:
        parts = [f"{chr(65 + i)}) {cell(c.get('what') if isinstance(c, dict) else c)}"
                 + (f" (breaks: {cell(c.get('breaks'))})" if isinstance(c, dict) and c.get("breaks") else " (breaks: not stated)")
                 for i, c in enumerate(alts[:4])]
        return " · ".join(parts) + (" [one direction only]" if len(alts) == 1 else "")
    return (cell(s.get("change")) or "none given") + " [one direction only, what it breaks not stated]"


def test_cell(s: dict) -> str:
    t = s.get("test")
    if isinstance(t, dict):
        kind = cell(t.get("kind")) or "kind not stated"
        why = f" (not automated: {cell(t.get('why_not_automated'))})" if t.get("why_not_automated") else ""
        return f"{kind}: {cell(t.get('how'))}{why}"
    return f"kind not stated: {cell(t)}" if t else "none given"


def build(leads: list[dict], lower: dict[str, str], drop: set[str], notes: dict[str, str], title: str) -> tuple[str, list[str]]:
    errors, rows = [], []
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
        src = cell(imp.get("source"))
        # An impact is a claim: with no line of code or document behind it, it is unverified, whatever level it was given.
        ilvl = level_word(imp.get("level")) if imp.get("what") and src else "unverified"
        impact_cell = f"{impact} [{ilvl}: {src}]" if src else f"{impact} [unverified: no source]"
        note = f" **Note added after the readers, unverified:** {cell(notes[where])}" if where in notes else ""
        rows.append((RANK.get(lvl, 0), f"| {lvl} | `{where}` | {cell(s.get('what'))}{note} | {impact_cell} | "
                                         f"{cell(s.get('breaks'))} | {changes_cell(s)} | {test_cell(s)} | {cell(s.get('by'))} |"))
    rows.sort(key=lambda r: -r[0])
    L = [f"# {title}", "",
         "Copied word for word from the inspector's agents: each lead's level, its impact's own level and",
         "source, and who claimed it. A level here was only ever lowered, never raised. Everything came",
         "from a model reading repository history and code: verify each claim before you change code.",
         "The changes are directions, not instructions: each says what it would break. A test's kind says",
         "whether the project's harness can run it (see the inspector's references/test-limits.md).", "",
         "| Level | Where | What breaks | Impact [its level: source] | Breaks | Ways to fix (and what each breaks) | Test (kind) | Claimed by |",
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
    text, errors = build(leads_of(items), pairs(a.lower), {d.strip().strip("`") for d in a.drop}, pairs(a.note), a.title)
    for e in errors + [f"unreadable: {b}" for b in bad]:
        print(f"handoff.py: {e}", file=sys.stderr)
    if errors:
        return 2
    if a.out:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            print(f"handoff.py: not saved ({e}); the list is below", file=sys.stderr)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
