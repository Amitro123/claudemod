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
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys


def at(where: str) -> tuple[str, int] | None:
    m = re.match(r"^`?([^`:\s]+):(\d+)", (where or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


def near(a: tuple[str, int] | None, b: tuple[str, int] | None, slack: int = 3) -> bool:
    return bool(a and b and (a[0] == b[0] or a[0].endswith("/" + b[0]) or b[0].endswith("/" + a[0]))
                and abs(a[1] - b[1]) <= slack)


def norm_unit(u: str | None) -> str:
    return (u or "").strip().split()[0].lstrip("#").lower() if u else ""


def crosscheck(evidence: dict, cards: list[dict]) -> dict:
    by_unit = {u["unit"]: u for u in evidence["timeline"]}
    out_cards, decided = [], set()
    for c in cards:
        unit = by_unit.get(c.get("unit", "")) or next(
            (u for u in evidence["timeline"] if any(x["sha"].startswith(str(c.get("commit", "-"))[:7])
                                                    for x in u["commits"])), None)
        commit = next((x for x in (unit or {}).get("commits", []) if c.get("commit") and
                       x["sha"].startswith(str(c["commit"])[:7])), None)
        blamed = [e["unit"] for e in (commit or {}).get("introduced_by", [])] or \
                 [e["unit"] for e in (unit or {}).get("introduced_by", [])]
        cu = c.get("culprit") or {}
        mine = norm_unit(cu.get("unit")) or norm_unit(cu.get("sha"))
        if not unit:
            culprit = "unit not in the evidence"
        elif not mine or mine == "unknown":
            culprit = "both unknown" if not blamed else f"reader unknown; blame says {', '.join(blamed[:3])}"
        elif any(mine == norm_unit(b) or norm_unit(b).startswith(mine) or mine.startswith(norm_unit(b))
                 for b in blamed if norm_unit(b)):
            culprit = "agree"
        elif not blamed:
            culprit = f"reader only ({cu.get('unit') or cu.get('sha')}); blame found none"
        else:
            culprit = f"disagree: reader {cu.get('unit') or cu.get('sha')}, blame {', '.join(blamed[:3])}"

        copies = [(x, (h.split(":")[0], int(h.split(":")[1]))) for src in ([commit] if commit else (unit or {}).get("commits", []))
                  for x in (src or {}).get("left_behind", []) for h in x["at"] if re.match(r".+:\d+$", h)]
        sibs = []
        for s in (c.get("complete") or {}).get("siblings", []):
            loc = at(s.get("where", ""))
            hit = next((h for x, h in copies if near(loc, h)), None)
            if hit:
                decided.add(hit)
            sibs.append({"where": s.get("where"), "level": s.get("level"), "breaks": s.get("breaks"),
                         "source": "both" if hit else "reader only"})
        for note in (c.get("complete") or {}).get("checked_clear", []):
            loc = at(note)
            for _, h in copies:
                if near(loc, h):
                    decided.add(h)
        out_cards.append({"case": c.get("case") or c.get("unit"), "culprit": culprit,
                          "mechanism_level": (c.get("mechanism") or {}).get("level"),
                          "siblings": sibs, "complete": (c.get("complete") or {}).get("verdict")})
    worked = {norm_unit(c.get("unit")) for c in cards}
    unchecked = [{"unit": x["unit"], "line": x["line"], "at": x["at"]} for x in evidence.get("left_behind", [])
                 if norm_unit(x["unit"]) in worked and not any(
                     (h.split(":")[0], int(h.split(":")[1])) in decided for h in x["at"] if re.match(r".+:\d+$", h))]
    agree = sum(c["culprit"] in ("agree", "both unknown") for c in out_cards)
    return {"cards": len(out_cards), "culprits_agree": agree, "cases": out_cards,
            "copies_left_unchecked": unchecked}


def markdown(r: dict) -> str:
    L = ["# Cross-check: case readers (diffs) against the collector (git)", "",
         f"- Cards: {r['cards']}; culprit agrees with blame: {r['culprits_agree']}", "",
         "| case | culprit | mechanism | complete | siblings (source) |", "|---|---|---|---|---|"]
    for c in r["cases"]:
        sib = "; ".join(f"{s['where']} {s['level']} ({s['source']})" for s in c["siblings"]) or "none"
        L.append(f"| {c['case']} | {c['culprit']} | {c['mechanism_level']} | {c['complete']} | {sib} |")
    L += ["", "## Copies left behind that no card decided", ""]
    L += [f"- {x['unit']}: `{x['line'][:90]}` at {', '.join(x['at'])}" for x in r["copies_left_unchecked"]] or ["- none"]
    L += ["", "A culprit both sources name, or a sibling both found, is stronger than either alone. A "
          "disagreement is a question to settle by reading, not a vote."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", required=True, help="the collector's evidence.json")
    ap.add_argument("--cards", required=True, help="the folder of case cards (*.json)")
    ap.add_argument("--json", help="write the result here too")
    a = ap.parse_args(argv)
    try:
        with open(a.evidence, encoding="utf-8") as f:
            ev = json.load(f)
    except (OSError, ValueError) as e:
        print(f"crosscheck.py: {e}", file=sys.stderr)
        return 1
    cards, bad = [], []
    for p in sorted(glob.glob(os.path.join(a.cards, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                cards.append(json.load(f))
        except (OSError, ValueError):
            bad.append(os.path.basename(p))
    r = crosscheck(ev, cards)
    r["unreadable_cards"] = bad
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
    sys.stdout.write(markdown(r) + (f"\nUnreadable cards (not JSON): {', '.join(bad)}\n" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
