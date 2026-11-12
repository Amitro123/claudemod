#!/usr/bin/env python3
"""Merge the verifier's verdicts into the leads, matching by `where` (exact).

    python merge_verdicts.py --leads leads.json --verdicts v1.json [v2.json ...]
                             [--out merged.json] [--drop-not-real]

`--verdicts` may be left out only when leads.json is an empty array (a run with no lead to verify): the
output is then `[]`, so the run folder still holds the merged.json the release gate requires.

Each lead gains `verdict` (REAL | REAL-LOW | NOT REAL | UNVERIFIABLE, or `unverified` when no
verdict exists), `verified_by`, `false_claims`; the verifier's corrected labels replace the lead's
(the originals stay under `original_category` / `original_reach`); the verifier's `unverifiable`
parts are appended to `not_verified`. A verdict's `probe_check` (what the verifier did with the reader's saved
probe) is kept as `verifier_probe_check`. A lead with a saved probe (`probe_file`) whose REAL or REAL-LOW has no
`probe_check.independent` (the verifier's own probe, a variation, or a code-path analysis citing path:line at the ref)
keeps its verdict but gets `verdict_basis`: `"reader probe only"` when a `probe_check` was given, `"independent check
not recorded"` when none was; plus a `not_verified` line and a warning. handoff.py and evals/scorecard.py count these
apart: a reader's probe that passes does not by itself confirm a lead. Two leads that share a `where` are refused; give each a distinct suffix
` [lead N]` (a space, `[lead `, the number, `]`) on the `where` of each of them, in the verdict as well; the release gate
(`evals/gate/check_run.py`) compares leads, verdicts and merged leads on the `where` without that suffix. Exit 2 on invalid JSON, a verdict matching no lead, two leads with the same `where`, or two
different verdicts for one `where` (identical duplicates are fine).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leadsio  # noqa: E402


PROBE_ONLY_BASIS, NOT_RECORDED_BASIS = "reader probe only", "independent check not recorded"
PROBE_ONLY = "the verdict rests on the reader's saved probe alone: no independent check by the verifier"
NOT_RECORDED = "the verifier recorded no check of the reader's saved probe and no independent check (probe_check)"


def load_array(path: str, what: str) -> list:
    try:
        with open(path, encoding="utf-8-sig") as f:
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


def merge(leads: list[dict], verdicts: list[dict], probe_only: list[str] | None = None) -> tuple[list[dict], int]:
    probe_only = probe_only if probe_only is not None else []
    seen: dict[str, int] = {}
    for x in leads:
        w = str(x.get("where"))
        seen[w] = seen.get(w, 0) + 1
    dup = sorted(w for w, n in seen.items() if n > 1)
    if dup:
        raise ValueError("two leads share the same where: " + ", ".join(dup)
                         + "; make `where` unique (for example add a line range or a suffix like ` [lead 2]`)")
    by_where: dict[str, dict] = {}
    for v in verdicts:
        w = str(v.get("where"))
        if w in by_where and by_where[w] != v:
            raise ValueError(f"verdicts for {w} disagree ({by_where[w].get('verdict')} vs {v.get('verdict')}); "
                             "keep one verdict per where")
        by_where[w] = v
    known = set(seen)
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
        check = v.get("probe_check")
        if isinstance(check, dict) and check:
            m["verifier_probe_check"] = check
        if lead.get("probe_file") is not None and m["verdict"].upper() in ("REAL", "REAL-LOW") \
                and not (isinstance(check, dict) and str(check.get("independent") or "").strip()):
            if isinstance(check, dict) and check:
                m["verdict_basis"] = PROBE_ONLY_BASIS
                probe_only.append(f"{lead.get('where')}: {m['verdict']} rests on the reader's saved probe alone; "
                                  "the verifier recorded no independent check (probe_check.independent)")
            else:
                m["verdict_basis"] = NOT_RECORDED_BASIS
                probe_only.append(f"{lead.get('where')}: {m['verdict']} has no recorded independent check: the lead has a "
                                  "saved probe and the verdict no probe_check")
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
        basis_note = {PROBE_ONLY_BASIS: [PROBE_ONLY], NOT_RECORDED_BASIS: [NOT_RECORDED]}.get(m.get("verdict_basis"), [])
        extra = [e for e in as_list(v.get("unverifiable")) + basis_note if e not in have]
        if as_list(v.get("unverifiable")):
            m["verifier_unverifiable"] = as_list(v.get("unverifiable"))
        if extra:
            m["not_verified"] = have + extra
        out.append(m)
    return out, relabelled


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leads", required=True)
    ap.add_argument("--verdicts", nargs="*", action="extend", default=[],
                    help="verdict files; every occurrence of the flag counts (may be omitted only when leads.json is empty)")
    ap.add_argument("--out")
    ap.add_argument("--drop-not-real", action="store_true")
    a = ap.parse_args(argv)
    try:
        leads = load_array(a.leads, "leads")
        leadsio.validate_leads(leads, "leads")
        if leads and not a.verdicts:
            raise ValueError("--verdicts is required when leads.json has leads")
        verdicts = []
        for p in a.verdicts:
            one = load_array(p, "verdicts")
            print(f"verdicts file {p}: {len(one)} verdicts", file=sys.stderr)
            verdicts += one
        probe_only: list[str] = []
        merged, relabelled = merge(leads, verdicts, probe_only)
    except ValueError as e:
        print(f"merge_verdicts: {e}", file=sys.stderr)
        return 2
    for w in probe_only:
        print(f"merge_verdicts: warning: {w}", file=sys.stderr)
    counts = Counter(m["verdict"] for m in merged)
    if a.drop_not_real:
        merged = [m for m in merged if m["verdict"].upper() != "NOT REAL"]
    text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        from evidence import write              # temp file + os.replace: a failed run never leaves a truncated file
        write(a.out, text, newline="\n")
    else:
        sys.stdout.write(text)
    print("merge_verdicts: " + ", ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
          + f"; relabelled: {relabelled}; written: {len(merged)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
