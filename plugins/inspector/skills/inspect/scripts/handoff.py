#!/usr/bin/env python3
"""Turn the readers' leads into a handoff list, word for word.

The open leads go to someone who will act on them (a code agent, an issue, a person). Retyping them
is where accuracy is lost: a "suspect" becomes a "read", and a consequence nobody traced creeps in.
This copies each lead's words and levels from the case cards (their `complete.siblings`) or from an
investigator's list of leads, and lets the caller only drop a lead or lower a level. A note the
caller adds is marked as theirs and unverified. When any lead has no verifier verdict, the first line of
the output is `UNVERIFIED: N of M leads were not checked by an independent verifier; ...` (leads
rejected by the verifier count as verified); with all verdicts there is no banner.

Known limitation: `cell()` escapes `|` and collapses whitespace but keeps the lead's text as written, Markdown
links included, because the handoff promises the readers' words unchanged. Treat the file as text to read, not
to render with trust.

    python handoff.py --cards <folder | file.json | ->  [--out file.md] [--title T]
                      [--lower 'path:line=suspect'] [--drop 'path:line'] [--note 'path:line=text']
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leadsio  # noqa: E402

SEC_FIELDS = ("security_input", "security_boundary", "security_sink", "security_actor")
REACH_ORDER = {"default-on": 0, "conditional": 1, "unknown": 2, "opt-in": 3}
RANK = {"reproduced": 3, "read": 2, "suspect": 1, "unverified": 0}


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


def change_unverified(s: dict) -> bool:
    """An explicit `change_status` wins; without one, a needs-host-check lead's change is unverified."""
    st = s.get("change_status")
    if isinstance(st, str) and st.strip().lower() in ("verified", "unverified"):
        return st.strip().lower() == "unverified"
    return needs_host_check(s)


def reach_of(s: dict) -> str:
    """`default-on` | `conditional` | `opt-in` | `unknown`; `reach_when` is appended (`conditional: format drift`).
    A reach that already carries its text (`opt-in: flag`) is kept as given; missing is `unknown`."""
    r = cell(s.get("reach")) if isinstance(s.get("reach"), (str, int, float)) else ""
    when = cell(s.get("reach_when")) if isinstance(s.get("reach_when"), (str, int, float)) else ""
    if r and when and ":" not in r:
        r = f"{r}: {when}"
    return r or "unknown"


def texts(v: object) -> list[str]:
    items = [v] if isinstance(v, str) else v if isinstance(v, list) else []
    return [cell(i) for i in items if isinstance(i, (str, int, float)) and cell(i)]


def would_settle_of(s: dict) -> str:
    """`would settle: a; b` for an UNVERIFIABLE lead: the verifier's own unverifiable parts."""
    items = texts(s.get("verifier_unverifiable"))
    return f" would settle: {'; '.join(items)}" if items and verdict_of(s) == "UNVERIFIABLE" else ""


def not_verified_of(s: dict) -> str:
    """Sub-claims nobody traced, as `not verified: a; b`. Printed only; never a level.
    For an UNVERIFIABLE lead the verifier's parts are printed as `would settle:` instead."""
    items = texts(s.get("not_verified"))
    if verdict_of(s) == "UNVERIFIABLE":
        items = [i for i in items if i not in texts(s.get("verifier_unverifiable"))]
    return f" not verified: {'; '.join(items)}" if items else ""


VERDICTS = ("REAL", "REAL-LOW", "UNVERIFIABLE", "unverified", "NOT REAL")


def verdict_of(s: dict) -> str:
    """The verifier's verdict as merge_verdicts wrote it; no verdict is `unverified`."""
    v = cell(s.get("verdict")).upper().replace("_", "-")
    v = "NOT REAL" if v in ("NOT REAL", "NOT-REAL") else v
    return v if v in VERDICTS and v != "UNVERIFIED" else "unverified"


def verification_of(s: dict) -> str:
    """`false claims: a; b` and `relabelled: category a -> b` for the impact cell, from merge_verdicts' fields."""
    items = texts(s.get("false_claims"))
    out = f" false claims: {'; '.join(items)}" if items else ""
    for k in ("category", "reach"):
        old, new = s.get(f"original_{k}"), s.get(k)
        if isinstance(old, (str, int, float)) and cell(old) != cell(new):
            out += f" relabelled: {k} {cell(old)} -> {cell(new) or 'unknown'}"
    ev = cell(s.get("verifier_evidence")) if isinstance(s.get("verifier_evidence"), (str, int, float)) else ""
    return out + (f" verifier: {ev}" if ev else "")


def probe_file_of(s: dict) -> str:
    """` probe file: probes/x (run: cmd; expect: y)` plus merge_cards' problems with it; '' for a lead with none."""
    pf = s.get("probe_file")
    if not isinstance(pf, dict) or not cell(pf.get("path")):
        return ""
    problems = texts(s.get("probe_file_problems"))
    if problems:
        return f" probe file: {cell(pf.get('path'))}, not to be run: {'; '.join(problems)}"
    return f" probe file: {cell(pf.get('path'))} (run: {cell(pf.get('command')) or '-'}; expect: {cell(pf.get('expect')) or '-'})"


BASIS_TAG = {"reader probe only": ", on the reader's probe only",
             "independent check not recorded": ", no independent check recorded"}


def rejected_entry(s: dict, where: str) -> str:
    ev = cell(s.get("verifier_evidence")) if isinstance(s.get("verifier_evidence"), (str, int, float)) else ""
    fc = "; ".join(texts(s.get("false_claims")))
    return (f"- `{where}` [verdict: NOT REAL] verifier: {ev or 'no evidence given'}"
            + (f" false claims: {fc}" if fc else "") + f" original claim: {cell(s.get('what'))}"
            + (f" (case {cell(s.get('case'))})" if cell(s.get("case")) else ""))


def build(leads: list[dict], lower: dict[str, str], drop: set[str], notes: dict[str, str], title: str,
          warnings: list[str] | None = None) -> tuple[str, list[str]]:
    errors, rows, rejected = [], [], []
    seen: Counter = Counter()
    apart = 0  # REAL or REAL-LOW whose lead has a saved probe and no recorded independent check
    warnings = warnings if warnings is not None else []
    for s in leads:
        where = cell(s.get("where"))
        if where in drop:
            continue
        if verdict_of(s) == "NOT REAL":
            seen["NOT REAL"] += 1
            rejected.append(rejected_entry(s, where))
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
        triple = [(k, cell(s.get(k))) for k in SEC_FIELDS]
        if str(s.get("category") or "").strip().lower() == "security":
            missing = [k for k, v in triple if not v]
            if missing:
                warnings.append(f"{where}: category security but {', '.join(missing)} missing or empty; name the input, "
                                "the boundary and the sink (path:line) and the actor (a party other than the "
                                "owner or maintainers who controls the input), or it is not security")
        counter, refuted = cell(s.get("security_counter")), cell(s.get("security_counter_refuted_by"))
        if str(s.get("category") or "").strip().lower() == "security":
            for k, v in (("security_counter", counter), ("security_counter_refuted_by", refuted)):
                if not v:
                    warnings.append(f"{where}: category security but {k} missing or empty; write the strongest one-line "
                                    "argument that it is only hardening or broken-flow, and the named fact (path:line, "
                                    "doc line or probe) that refutes it, or it is not security")
        parts = []
        if any(v for _, v in triple):
            parts = [f"{n}: {v or '-'}" for n, (_, v) in zip(("in", "boundary", "sink", "actor"), triple)]
        if counter or refuted:
            parts += [f"counter: {counter or '-'}", f"refuted by: {refuted or '-'}"]
        if parts:
            impact += f" ({' | '.join(parts)})"
        shown = f"{lvl} [needs-host-check]" if needs_host_check(s) else lvl
        if s.get("card_status") == "in-progress":
            was = level_word(s.get("original_level")) if s.get("original_level") else ""
            shown += f" [partial: the case reader stopped{'; it had ' + was if was else ''}]"
        prod = str(s.get("observed_in_production") or "").strip().lower()
        prod = prod if prod in ("yes", "no") else "unknown"
        src_p = cell(s.get("observed_source")) if isinstance(s.get("observed_source"), (str, int, float)) else ""
        shown += f" [production: {prod}{': ' + src_p if src_p and prod != 'unknown' else ''}]"
        documented = cell(s.get("documented")) if isinstance(s.get("documented"), (str, int, float)) else ""
        if documented and not (cell(s.get("reconcile")) if isinstance(s.get("reconcile"), (str, int, float)) else "")                 and prod != "yes":
            warnings.append(f"{where}: documented ({documented}) but no reconcile and no observed_in_production yes; "
                            "name the production evidence that would show harm (a freshness query, a reconciliation, "
                            "a job history); severity cannot be set from code alone")
        verdict = verdict_of(s)
        basis = BASIS_TAG.get(s.get("verdict_basis"), "") if verdict in ("REAL", "REAL-LOW") else ""
        apart += bool(basis)
        shown += f" [verdict: {verdict}{basis}]"
        probe = cell(s.get("probe")) if isinstance(s.get("probe"), (str, int, float)) else ""
        saved = probe_file_of(s)
        if lvl in ("reproduced", "read") and not probe and not saved:
            warnings.append(f"{where}: level {lvl} but no probe; give the exact input and output, the command run, "
                            "or the path:line read (for a claim about an external tool, its --help), or lower the "
                            "level / move the claim to not_verified")
        impact_cell = (f"{impact} [{ilvl}{': ' + src if src and ilvl != 'unverified' else ''}]{not_verified_of(s)}{would_settle_of(s)}{verification_of(s)}"
                       + (f" probe: {probe}" if probe else "") + saved)
        rec = cell(s.get("reconcile")) if isinstance(s.get("reconcile"), (str, int, float)) else ""
        if rec:
            impact_cell += f" reconcile: {rec}"
        if documented:
            impact_cell += f" documented: {documented}"
        note = f" **Note added after the readers, unverified:** {cell(notes[where])}" if where in notes else ""
        change = cell(s.get("change")) + (" [change unverified]" if change_unverified(s) else "")
        down = cell(s.get("downstream")) if isinstance(s.get("downstream"), (str, int, float)) else ""
        if down:
            change += f" downstream: {down}"
        kind = cell(s.get("test_kind")).lower() if isinstance(s.get("test_kind"), str) else ""
        kind = kind if kind in ("behavioral", "text-pin", "manual") else "unknown"
        test = f"{cell(s.get('test'))} [test: {kind}]" + (" [weak: pins text only]" if kind == "text-pin" else "")
        reach = reach_of(s)
        rows.append((RANK.get(lvl, 0), 0 if prod == "yes" else 1, REACH_ORDER.get(reach.lower().split(":")[0].strip(), 2),
                     VERDICTS.index(verdict), verdict, f"| {shown} | `{where}` | {cell(s.get('what'))}{note} | {impact_cell} | "
                                         f"{cell(s.get('breaks'))} | {change} | {test} | {cell(s.get('case'))} | {reach} |"))
    rows.sort(key=lambda r: (r[1], -r[0], r[2], r[3]))  # seen in production first, then level, reach, verdict
    seen.update(r[4] for r in rows)
    head = []
    if any(v != "unverified" for v in seen):
        head = [f"Verified: {seen['REAL']} real, {seen['REAL-LOW']} real-low, {seen['UNVERIFIABLE']} unverifiable, "
                f"{seen['NOT REAL']} not real, {seen['unverified']} unverified"
                + (f" ({apart} of the {seen['REAL'] + seen['REAL-LOW']} real or real-low without a recorded independent check)"
                   if apart else ""), ""]
    total = len(rows) + len(rejected)
    banner = []
    if seen["unverified"]:
        banner = [f"UNVERIFIED: {seen['unverified']} of {total} leads were not checked by an independent verifier; "
                  "treat them as candidates, not findings.", ""]
    L = [*banner, f"# {title}", "",
         "Copied word for word from the inspector's case readers: each lead's level, and its impact's own",
         "level, as they gave them. A level here was only ever lowered, never raised. Everything came from",
         "a model reading repository history and code: verify each claim before you change code.", "", *head,
         "| Level | Where | What breaks | Impact [its level: source] | Breaks | The change | The test | From case | Reach |",
         "|---|---|---|---|---|---|---|---|---|"]
    L += [r for *_, r in rows] or ["| - | - | no leads | - | - | - | - | - | - |"]
    if rejected:
        L += ["", "## Rejected by the verifier", "",
              "Not actionable: the verifier found these claims not real. Kept as an audit trail, not as requirements.",
              "", *rejected]
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
    ap.add_argument("--cards", required=True, help="a folder of cards (*.json), a .json file, or - for stdin (cards or leads)")
    ap.add_argument("--out", help="write the list here too")
    ap.add_argument("--title", default="Open leads, for whoever fixes them")
    ap.add_argument("--lower", action="append", default=[], help="'path:line=level': lower that lead's level")
    ap.add_argument("--drop", action="append", default=[], help="'path:line': leave that lead out")
    ap.add_argument("--note", action="append", default=[], help="'path:line=text': add a note, marked as yours and unverified")
    a = ap.parse_args(argv)
    try:
        items = leadsio.read_items(a.cards)
    except leadsio.LeadsError as exc:
        print(f"handoff.py: invalid cards: {exc}", file=sys.stderr)
        return 2
    warns: list[str] = []
    text, errors = build(leadsio.leads_of(items), pairs(a.lower), {d.strip().strip("`") for d in a.drop}, pairs(a.note), a.title, warns)
    for w in warns:
        print(f"handoff.py: warning: {w}", file=sys.stderr)
    for e in errors:
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
