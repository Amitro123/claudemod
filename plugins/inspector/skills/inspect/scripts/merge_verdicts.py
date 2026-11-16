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

When the leads file sits in a run folder with a plan (`<folder>/plan/expect.json`), every verdict file the plan names
(`verifier_chunks`) must be among `--verdicts` and exist: otherwise exit 2, naming the missing ones, and nothing is
written. In a live run (2026-11-16) the merge was run before the last verifier had finished and wrote a merged.json
with 7 leads `unverified` and no stop. `--partial` merges what exists on purpose. Leads with no plan beside them merge
as before.

`--docs FILE`: the docs-checker's reply, a JSON array of {n, where, answer, text, source} (text around the array, such
as a code fence, is ignored). Each answer is put on its lead as `docs_answer`, and handoff.py prints it beside the doubt;
it never changes a verdict. The answer `yes`/`no` is to the question as the reader asked it, which may confirm the lead or
refute it: a person reads it. A missing or unreadable file, or an answer for a `where` that is no lead, is a warning, not an
error: the documentation check is advisory. Verdicts' corrected `category` / `reach` outside the values references/labels.md
allows are normalized (leadsio.normalize_labels) with a warning.
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


def load_array(path: str, what: str, repaired: list[str] | None = None) -> list:
    try:
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except ValueError as e:
            if repaired is None or not leadsio.repair_escapes(path, e):
                raise
            repaired.append(path)
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"{what} {path}: invalid JSON or unreadable ({e})") from e
    if not isinstance(data, list):
        raise ValueError(f"{what} {path}: expected a JSON array")
    return data


DICT_FIELDS = ("corrected", "probe_check")


def check_verdicts(items: list, path: str) -> None:
    """Every verdict entry is an object with a `where`, and its object fields are objects: a malformed file is
    refused with every problem named (exit 2), never a traceback (second 2026-11-14 inspection)."""
    bad = []
    for i, v in enumerate(items):
        if not isinstance(v, dict):
            bad.append(f"[{i}]: expected an object, got {type(v).__name__}")
            continue
        if not str(v.get("where") or "").strip():
            bad.append(f"[{i}]: no `where`")
        for k in DICT_FIELDS:
            if v.get(k) is not None and not isinstance(v[k], dict):
                bad.append(f"[{i}] {v.get('where')}: `{k}` must be an object, got {type(v[k]).__name__}")
    if bad:
        raise ValueError(f"verdicts {path}: " + "; ".join(bad))


def load_docs(path: str) -> tuple[list[dict], list[str]]:
    """(answers, warnings) from the docs-checker's saved reply. Never raises."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        return [], [f"docs answers {path}: not readable ({e}); the docs-checker's answers are not in the output"]
    a, b = text.find("["), text.rfind("]")
    try:
        data = json.loads(text[a:b + 1]) if a != -1 and b > a else None
    except ValueError:
        data = None
    if not isinstance(data, list):
        return [], [f"docs answers {path}: no JSON array found; the docs-checker's answers are not in the output"]
    out, warn = [], []
    for i, x in enumerate(data):
        if isinstance(x, dict) and str(x.get("where") or "").strip() and str(x.get("text") or x.get("answer") or "").strip():
            out.append(x)
        else:
            warn.append(f"docs answers {path} [{i}]: needs an object with `where` and `text`; skipped")
    return out, warn


def add_docs(merged: list[dict], answers: list[dict]) -> list[str]:
    """Put each docs answer on the lead it names (`where`, with or without a ` [lead N]` suffix). Returns warnings."""
    by = {str(m.get("where")): m for m in merged}
    bare: dict[str, list[dict]] = {}
    for m in merged:
        bare.setdefault(leadsio.LEAD_SUFFIX_RE.sub("", str(m.get("where"))), []).append(m)
    warn = []
    for x in answers:
        w = str(x["where"]).strip()
        hits = [by[w]] if w in by else bare.get(leadsio.LEAD_SUFFIX_RE.sub("", w), [])
        if not hits:
            warn.append(f"docs answer for {w}: no lead has that `where`; not used")
            continue
        ans = {k: " ".join(str(x[k]).split()) for k in ("answer", "text", "source") if str(x.get(k) or "").strip()}
        for m in hits:
            m.setdefault("docs_answers", []).append(ans)
    return warn


def planned_but_missing(leads_path: str, given: list[str]) -> list[str]:
    """Verdict files the run's plan names that were not passed, or do not exist. Empty when there is no plan to read."""
    run = os.path.dirname(os.path.abspath(leads_path))
    try:
        with open(os.path.join(run, "plan", "expect.json"), encoding="utf-8") as f:
            chunks = json.load(f).get("verifier_chunks")
    except (OSError, ValueError, AttributeError):
        return []
    have = {os.path.realpath(p) for p in given if os.path.isfile(p)}
    out = []
    for c in chunks if isinstance(chunks, list) else []:
        name = c.get("verdicts") if isinstance(c, dict) else None
        if isinstance(name, str) and name and os.path.realpath(os.path.join(run, name)) not in have:
            out.append(name)
    return out


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
        corrected = dict(v.get("corrected") or {})
        fixed = {k: corrected[k] for k in ("category", "reach") if corrected.get(k) not in (None, "")}
        if fixed:
            norm = {"where": lead.get("where"), **fixed}
            probe_only += [f"corrected label normalized: {n}" for n in leadsio.normalize_labels(norm, "verifier")]
            for k in fixed:
                corrected[k] = norm[k]
                if norm.get(f"{k}_as_written"):
                    m[f"verifier_{k}_as_written"] = norm[f"{k}_as_written"]
            if norm.get("reach_when") and not str(corrected.get("reach_when") or "").strip() and "reach_as_written" in norm:
                corrected["reach_when"] = norm["reach_when"]
        for k, val in corrected.items():
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
    leadsio.utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leads", required=True)
    ap.add_argument("--verdicts", nargs="*", action="extend", default=[],
                    help="verdict files; every occurrence of the flag counts (may be omitted only when leads.json is empty)")
    ap.add_argument("--out")
    ap.add_argument("--drop-not-real", action="store_true")
    ap.add_argument("--partial", action="store_true",
                    help="merge although the run's plan names verdict files that are missing or were not passed "
                         "(their leads stay `unverified`); without it that is exit 2")
    ap.add_argument("--docs", help="the docs-checker's saved reply (a JSON array); each answer goes on its lead as docs_answers")
    ap.add_argument("--repair-escapes", action="store_true",
                    help="double stray backslashes in a verdicts file (an agent on Windows wrote C:\\Users raw); "
                         "the original is kept as <file>.orig and each repair is printed")
    a = ap.parse_args(argv)
    try:
        leads = load_array(a.leads, "leads")
        leadsio.validate_leads(leads, "leads")
        if leads and not a.verdicts:
            raise ValueError("--verdicts is required when leads.json has leads")
        missing = planned_but_missing(a.leads, a.verdicts)
        if missing and not a.partial:
            raise ValueError(f"the run's plan names {len(missing)} verdict file(s) that are missing or not among --verdicts: "
                             f"{', '.join(missing)}. A verifier has not finished (plan.py --status says which), or a file "
                             "was left out. Nothing was written. Pass every planned file, or --partial to merge what "
                             "exists and leave those leads unverified")
        if missing:
            print(f"merge_verdicts: warning: --partial: merging what exists; no verdicts from {', '.join(missing)}", file=sys.stderr)
        verdicts = []
        for p in a.verdicts:
            repaired: list[str] = []
            one = load_array(p, "verdicts", repaired if a.repair_escapes else None)
            for r in repaired:
                print(f"merge_verdicts: repaired stray backslashes in {r} (original kept as {r}.orig)", file=sys.stderr)
            check_verdicts(one, p)
            print(f"verdicts file {p}: {len(one)} verdicts", file=sys.stderr)
            verdicts += one
        probe_only: list[str] = []
        merged, relabelled = merge(leads, verdicts, probe_only)
    except ValueError as e:
        print(f"merge_verdicts: {e}", file=sys.stderr)
        return 2
    docs_used = 0
    if a.docs:
        answers, warn = load_docs(a.docs)
        warn += add_docs(merged, answers)
        docs_used = sum(len(m.get("docs_answers") or []) for m in merged)
        probe_only += warn
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
          + f"; relabelled: {relabelled}; written: {len(merged)}"
          + (f"; docs answers on leads: {docs_used}" if a.docs else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
