#!/usr/bin/env python3
"""Cross-check what the case readers found in the diffs against what the collector found in git.

Two independent sources: `evidence.json` (blame, copies left behind: mechanical) and the case
cards (`cards/*.json`: a model read the diff and today's code). For each card:

- culprit: does the reader's culprit match blame's (`introduced_by`) for that commit or unit?
- siblings: does each sibling the reader reports sit on a copy the collector found (same file,
  within 3 lines), or did only one side see it?
- copies left behind that no card decided: still to check.

Agreement raises confidence, disagreement is something to look at. Stdlib only.

    python crosscheck.py --evidence <out>/evidence.json --cards <out>/cards [--json out.json]
    python crosscheck.py --repo . [--path P | --since R] --cards - <<'EOF'   # no files: cards on stdin
    [ {card}, {card} ]
    EOF
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # also under `python -I`
import leadsio  # noqa: E402
import snapshot  # noqa: E402


def at(where: str) -> tuple[str, int] | None:
    m = re.match(r"^`?([^`:\s]+):(\d+)", (where or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


def near(a: tuple[str, int] | None, b: tuple[str, int] | None, slack: int = 3) -> bool:
    return bool(a and b and (a[0] == b[0] or a[0].endswith("/" + b[0]) or b[0].endswith("/" + a[0]))
                and abs(a[1] - b[1]) <= slack)


def norm_unit(u: str | None) -> str:
    parts = str(u or "").strip().split()
    return parts[0].lstrip("#").lower() if parts else ""


def same_unit(a: str, b: str) -> bool:
    """PR numbers are exact IDs; only hexadecimal commit IDs allow abbreviation."""
    x, y = norm_unit(a), norm_unit(b)
    if not x or not y:
        return False
    # A bare number is a PR id only below 7 digits (the same rule as evidence.py --unit); a longer
    # all-digit string can still be a commit prefix such as 1234567.
    if (a.strip().startswith("#") or b.strip().startswith("#")
            or (x.isdigit() and len(x) < 7) or (y.isdigit() and len(y) < 7)):
        return x == y
    return x == y or bool(re.fullmatch(r"[0-9a-f]{7,40}", x) and
                          re.fullmatch(r"[0-9a-f]{7,40}", y) and
                          (x.startswith(y) or y.startswith(x)))


def crosscheck(evidence: dict, cards: list[dict]) -> dict:
    by_unit = {u["unit"]: u for u in evidence["timeline"]}
    out_cards, decided, worked = [], set(), set()
    for c in cards:
        unit = by_unit.get(c.get("unit", ""))
        commit, identity_error = None, None
        if c.get("commit"):
            wanted = str(c["commit"]).lower()
            candidates = [(u, x) for u in ([unit] if unit else evidence["timeline"])
                          for x in u["commits"]
                          if re.fullmatch(r"[0-9a-f]{7,40}", wanted)
                          and (x["sha"].startswith(wanted) or wanted.startswith(x["sha"]))]
            if len(candidates) == 1:
                unit, commit = candidates[0]
            else:
                identity_error = "commit ambiguous or not in the evidence"
        if unit:
            worked.add(norm_unit(unit["unit"]))
        source = {} if identity_error else commit if commit is not None else unit or {}
        blamed = [e["unit"] for e in source.get("introduced_by", [])]
        cu = c.get("culprit") or {}
        mine = norm_unit(cu.get("unit")) or norm_unit(cu.get("sha"))
        if identity_error:
            culprit = identity_error
        elif not unit:
            culprit = "unit not in the evidence"
        elif not mine or mine == "unknown":
            culprit = "both unknown" if not blamed else f"reader unknown; blame says {', '.join(blamed[:3])}"
        elif any(same_unit(cu.get("unit") or cu.get("sha") or "", b) for b in blamed):
            culprit = "agree"
        elif not blamed:
            culprit = f"reader only ({cu.get('unit') or cu.get('sha')}); blame found none"
        else:
            culprit = f"disagree: reader {cu.get('unit') or cu.get('sha')}, blame {', '.join(blamed[:3])}"

        copies = [(src["sha"][:12], x, at(h))
                  for src in ([] if identity_error else [commit] if commit else (unit or {}).get("commits", []))
                  for x in src.get("left_behind", []) for h in x["at"] if at(h)]
        sibs = []
        for sibling in (c.get("complete") or {}).get("siblings", []):
            loc = at(sibling.get("where", ""))
            hits = [(sha, x, h) for sha, x, h in copies if near(loc, h)]
            for sha, x, h in hits:
                decided.add((unit["unit"], sha, x["line"], h))
            sibs.append({"where": sibling.get("where"), "level": sibling.get("level"), "breaks": sibling.get("breaks"),
                         "source": "both" if hits else "reader only"})
        for note in (c.get("complete") or {}).get("checked_clear", []):
            loc = at(note)
            for sha, x, h in copies:
                if near(loc, h):
                    decided.add((unit["unit"], sha, x["line"], h))
        out_cards.append({"case": c.get("case") or c.get("unit"), "culprit": culprit,
                          "mechanism_level": (c.get("mechanism") or {}).get("level"),
                          "siblings": sibs, "complete": (c.get("complete") or {}).get("verdict")})
    unchecked = []
    for x in evidence.get("left_behind", []):
        if norm_unit(x["unit"]) not in worked:
            continue
        pending = [h for h in x["at"]
                   if (x["unit"], x.get("commit", "")[:12], x["line"], at(h)) not in decided]
        if pending:
            unchecked.append({"unit": x["unit"], "line": x["line"], "at": pending})
    agree = sum(c["culprit"] == "agree" for c in out_cards)
    return {"cards": len(out_cards), "culprits_agree": agree,
            "culprits_both_unknown": sum(c["culprit"] == "both unknown" for c in out_cards), "cases": out_cards,
            "copies_left_unchecked": unchecked}


def markdown(r: dict) -> str:
    L = ["# Cross-check: case readers (diffs) against the collector (git)", "",
         f"- Cards: {r['cards']}; culprit agrees with blame: {r['culprits_agree']}",
         f"- Both unknown (not corroboration): {r['culprits_both_unknown']}", "",
         "| case | culprit | mechanism | complete | siblings (source) |", "|---|---|---|---|---|"]
    for c in r["cases"]:
        sib = "; ".join(f"{s['where']} {s['level']} ({s['source']})" for s in c["siblings"]) or "none"
        L.append(f"| {c['case']} | {c['culprit']} | {c['mechanism_level']} | {c['complete']} | {sib} |")
    L += ["", "## Copies left behind that no card decided", ""]
    L += [f"- {x['unit']}: `{x['line'][:90]}` at {', '.join(x['at'])}" for x in r["copies_left_unchecked"]] or ["- none"]
    L += ["", "A culprit both sources name, or a sibling both found, is stronger than either alone. A "
          "disagreement is a question to settle by reading, not a vote."]
    return "\n".join(L) + "\n"


def read_cards(src: str) -> tuple[list[dict], list[str]]:
    """Cards and problems, via the shared reader; invalid input is never an empty success."""
    try:
        return leadsio.read_items(src), []
    except leadsio.LeadsError as exc:
        return [], [str(exc)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", help="the collector's evidence.json; without it, the evidence is collected again")
    ap.add_argument("--repo", help="with no --evidence: the repository")
    ap.add_argument("--path", action="append", help="with no --evidence: the same --path the collector ran with (repeatable)")
    ap.add_argument("--since", help="with no --evidence: the same --since the collector ran with")
    ap.add_argument("--ref", help="fallback collection: pin to the original ref SHA")
    ap.add_argument("--unit", help="fallback collection: original unit")
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--history", type=int, default=500)
    ap.add_argument("--max-blame-lines", type=int, default=400)
    ap.add_argument("--min-lines", type=int, default=3)
    ap.add_argument("--component-root", action="append", default=[])
    ap.add_argument("--cards", required=True, help="a folder of case cards (*.json), a .json file, or - for stdin")
    ap.add_argument("--json", help="write the result here too")
    a = ap.parse_args(argv)
    a.path = snapshot.scope_path(a.path)
    cards, bad = read_cards(a.cards)
    if bad:
        print("crosscheck.py: invalid cards: " + "; ".join(bad), file=sys.stderr)
        return 2
    try:
        if a.evidence:
            with open(a.evidence, encoding="utf-8") as f:
                ev = json.load(f)
            _, warnings = snapshot.validate(ev, repo=a.repo, expected_ref=a.ref,
                                            expected_scope={"path": a.path, "since": a.since, "unit": a.unit})
            for warning in warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        else:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import evidence
            ev = evidence.investigate(a.repo or ".", ref=a.ref or "HEAD", since=a.since, path=a.path,
                                      unit=a.unit, limit=a.max, history=a.history,
                                      max_blame=a.max_blame_lines, min_lines=a.min_lines,
                                      roots=evidence.MONOREPO_ROOTS | set(a.component_root))
    except (OSError, ValueError, RuntimeError) as e:
        print(f"crosscheck.py: {e}", file=sys.stderr)
        return 1
    r = crosscheck(ev, cards)
    r["unreadable_cards"] = bad
    failed = False          # a failed save still prints the report: it is the only copy
    if a.json:
        try:
            from evidence import write
            write(a.json, json.dumps(r, ensure_ascii=False, indent=1))
        except OSError as e:
            print(f"crosscheck.py: not saved ({e})", file=sys.stderr)
            failed = True
    sys.stdout.write(markdown(r) + (f"\nUnreadable cards (not JSON): {', '.join(bad)}\n" if bad else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
