#!/usr/bin/env python3
"""Merge the verifier's verdicts into the leads, matching by `where` (exact).

    python merge_verdicts.py --leads leads.json --verdicts v1.json [v2.json ...]
                             [--out merged.json] [--drop-not-real]

Each lead gains `verdict` (REAL | REAL-LOW | NOT REAL | UNVERIFIABLE, or `unverified` when no
verdict exists), `verified_by`, `false_claims`; the verifier's corrected labels replace the lead's
(the originals stay under `original_category` / `original_reach`); the verifier's `unverifiable`
parts are appended to `not_verified`. Exit 2 on invalid JSON or a verdict matching no lead.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter


def load_array(path: str, what: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"{what} {path}: invalid JSON or unreadable ({e})") from e
    if not isinstance(data, list):
        raise ValueError(f"{what} {path}: expected a JSON array")
    return data


def as_list(v: object) -> list:
    if v is None or v == "" or v == []:
        return []
    return list(v) if isinstance(v, list) else [v]


def merge(leads: list[dict], verdicts: list[dict]) -> tuple[list[dict], int]:
    by_where = {str(v.get("where")): v for v in verdicts}
    known = {str(x.get("where")) for x in leads}
    unmatched = sorted(w for w in by_where if w not in known)
    if unmatched:
        raise ValueError("verdicts match no lead: " + ", ".join(unmatched))
    out, relabelled = [], 0
    for lead in leads:
        m = dict(lead)
        v = by_where.get(str(lead.get("where")))
        if v is None:
            m["verdict"] = "unverified"
            out.append(m)
            continue
        m["verdict"] = str(v.get("verdict") or "unverified")
        m["verified_by"] = "verifier"
        m["false_claims"] = as_list(v.get("false_claims"))
        if v.get("evidence"):
            m["verifier_evidence"] = v["evidence"]
        changed = False
        for k, val in (v.get("corrected") or {}).items():
            if val in (None, ""):
                continue
            if k in ("category", "reach") and m.get(k) != val:
                m.setdefault(f"original_{k}", m.get(k))
                changed = True
            m[k] = val
        relabelled += changed
        have = as_list(m.get("not_verified"))
        extra = [e for e in as_list(v.get("unverifiable")) if e not in have]
        if extra:
            m["not_verified"] = have + extra
        out.append(m)
    return out, relabelled


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leads", required=True)
    ap.add_argument("--verdicts", required=True, nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--drop-not-real", action="store_true")
    a = ap.parse_args(argv)
    try:
        leads = load_array(a.leads, "leads")
        verdicts = [v for p in a.verdicts for v in load_array(p, "verdicts")]
        merged, relabelled = merge(leads, verdicts)
    except ValueError as e:
        print(f"merge_verdicts: {e}", file=sys.stderr)
        return 2
    counts = Counter(m["verdict"] for m in merged)
    if a.drop_not_real:
        merged = [m for m in merged if m["verdict"].upper() != "NOT REAL"]
    text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    print("merge_verdicts: " + ", ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
          + f"; relabelled: {relabelled}; written: {len(merged)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
