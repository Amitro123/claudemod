"""Merge the auditors' rows and the verifier's verdicts into the report table, refusing rows that don't hold up.

    python table.py ROWS.json [ROWS.json ...] [--verdicts V.json ...] [--out FILE] [--show-identities] [--json]

A row: {"id": "c2-r1", "check": 2, "action": "...", "evidence": ["source: ref", ...], "authorized": "yes|no|unknown",
        "approval": "the record that authorizes it (required for yes)", "notes": "...", "blocked": false}
A verdict: {"id": "c2-r1", "verdict": "confirmed|contradicted|unverifiable", "authorized": "<corrected>",
            "evidence": ["the verifier's own source"], "why": "..."}

Refused (exit 2, nothing written): a row with no id, a repeated id, no action, no evidence, an `authorized` other
than yes/no/unknown, a yes without `approval`, or any text holding a token, a bearer value or a private key. A
verdict is refused for an unknown kind, an id no row has, a second verdict for one row, confirmed or contradicted
without its own evidence, contradicted without the `authorized` it supports, or a correction to yes without an
`approval`; the merged rows are then checked again by the row rules.
Emails in rows are shown as ***@domain unless --show-identities (an Activity Log caller is evidence; the user
decides whether a report names people). A verdict that contradicts a row replaces its `authorized` and says so;
an unverifiable one turns yes or no into unknown; rows no verifier saw are marked "(not re-checked)".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ALLOWED = ("yes", "no", "unknown")
SECRET_RES = [re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}|\bglpat-[A-Za-z0-9_-]{20,}|"
                         r"\bxox[baprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{24,}|"
                         r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
              re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"), re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")


def load_list(path: str) -> list[dict]:
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(d, dict):
        d = d.get("rows") or d.get("verdicts") or [d]
    if not isinstance(d, list):
        raise ValueError(f"{path}: expected a JSON array")
    return [x for x in d if isinstance(x, dict)]


def as_list(v) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def problems(rows: list[dict]) -> list[str]:
    errs, seen = [], set()
    for i, r in enumerate(rows):
        rid = r.get("id")
        label = rid or f"row {i + 1}"
        if not rid:
            errs.append(f"{label}: no id")
        elif rid in seen:
            errs.append(f"{label}: id used twice")
        seen.add(rid)
        if not str(r.get("action", "")).strip():
            errs.append(f"{label}: no action")
        if not [e for e in as_list(r.get("evidence")) if e.strip()]:
            errs.append(f"{label}: no evidence source (a command, an API, a file; not an agent's word)")
        a = str(r.get("authorized", "")).lower()
        if a not in ALLOWED:
            errs.append(f"{label}: authorized is {r.get('authorized')!r}; use yes, no or unknown")
        if a == "yes" and not str(r.get("approval") or "").strip():
            errs.append(f"{label}: yes without the approval record that makes it yes")
        blob = json.dumps(r, ensure_ascii=False)
        if any(rx.search(blob) for rx in SECRET_RES):
            errs.append(f"{label}: holds a token, bearer value or private key; report its kind and place, not its value")
    return errs


VERDICTS = ("confirmed", "contradicted", "unverifiable")


def verdict_problems(rows: list[dict], verdicts: list[dict]) -> list[str]:
    """A verdict is checked like a row: a known kind, one per row, a row that exists, its own evidence when it
    decides something, and an approval record when it turns a row into yes."""
    errs, ids, seen = [], {r.get("id") for r in rows}, set()
    for i, v in enumerate(verdicts):
        vid = v.get("id")
        label = f"verdict {vid or i + 1}"
        kind = str(v.get("verdict", "")).lower()
        if not vid:
            errs.append(f"{label}: no id")
        elif vid not in ids:
            errs.append(f"{label}: no row has this id")
        elif vid in seen:
            errs.append(f"{label}: a second verdict for the same row")
        seen.add(vid)
        if kind not in VERDICTS:
            errs.append(f"{label}: verdict is {v.get('verdict')!r}; use confirmed, contradicted or unverifiable")
        if kind in ("confirmed", "contradicted") and not [e for e in as_list(v.get("evidence")) if e.strip()]:
            errs.append(f"{label}: {kind} needs the verifier's own evidence")
        if kind == "contradicted":
            a = str(v.get("authorized", "")).lower()
            if a not in ALLOWED:
                errs.append(f"{label}: contradicted needs the authorized value its evidence supports (yes, no or unknown)")
            elif a == "yes" and not str(v.get("approval") or "").strip():
                errs.append(f"{label}: turns the row into yes without the approval record that makes it yes")
        if any(rx.search(json.dumps(v)) for rx in SECRET_RES):
            errs.append(f"{label}: holds a token, bearer value or private key")
    return errs


def merge(rows: list[dict], verdicts: list[dict]) -> list[dict]:
    by = {v.get("id"): v for v in verdicts if v.get("id")}
    out = []
    for r in rows:
        r = dict(r)
        r["authorized"] = str(r["authorized"]).lower()
        v = by.get(r["id"])
        if not v:
            r["checked"] = "not re-checked"
        else:
            kind = str(v.get("verdict", "")).lower()
            r["checked"] = kind or "?"
            if v.get("evidence"):
                r["evidence"] = as_list(r.get("evidence")) + [f"re-check: {e}" for e in as_list(v["evidence"])]
            if kind == "contradicted" and str(v.get("authorized", "")).lower() in ALLOWED:
                r["notes"] = (str(r.get("notes") or "") + f" Re-check changed {r['authorized']} to {v['authorized']}: {v.get('why', '')}").strip()
                r["authorized"] = str(v["authorized"]).lower()
                if r["authorized"] == "yes":
                    r["approval"] = str(v["approval"])
                else:
                    r.pop("approval", None)
            elif kind == "unverifiable" and r["authorized"] != "unknown":
                r["notes"] = (str(r.get("notes") or "") + f" Re-check could not confirm {r['authorized']}: {v.get('why', '')}").strip()
                r["authorized"] = "unknown"
        out.append(r)
    return sorted(out, key=lambda r: (int(r.get("check") or 0), r["id"]))


def cell(s: str, identities: bool) -> str:
    s = " ".join(str(s).split()).replace("|", "\\|")
    return s if identities else EMAIL.sub(lambda m: "***@" + m.group(1).lower(), s)


def render(rows: list[dict], identities: bool) -> str:
    out = ["| Check | Action | Evidence source | Authorized |", "|---|---|---|---|"]
    for r in rows:
        auth = r["authorized"] + (f" ({r['approval']})" if r["authorized"] == "yes" and r.get("approval") else "")
        if r["checked"] == "not re-checked":
            auth += " (not re-checked)"
        elif r["checked"] == "unverifiable":
            auth += " (re-check could not settle it)"
        action = r["action"] + (f" {r['notes']}" if r.get("notes") else "")
        out.append(f"| {r.get('check', '')} | {cell(action, identities)} | {cell('; '.join(as_list(r['evidence'])), identities)} | {cell(auth, identities)} |")
    blocked = [r for r in rows if r.get("blocked")]
    if blocked:
        out += ["", "Could not be checked:", ""] + [f"- {cell(r['action'], identities)}: {cell(r.get('notes') or '', identities)}" for r in blocked]
    counts = {k: sum(1 for r in rows if r["authorized"] == k) for k in ALLOWED}
    by = {k: sum(1 for r in rows if r["checked"] == k) for k in VERDICTS}
    checked = by["confirmed"] + by["contradicted"]
    out += ["", f"{len(rows)} rows: {counts['yes']} yes, {counts['no']} no, {counts['unknown']} unknown; "
                f"{checked} re-checked with evidence by the verifier ({by['confirmed']} confirmed, {by['contradicted']} contradicted)"
                + (f", {by['unverifiable']} it could not check" if by["unverifiable"] else "") + "."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows", nargs="+")
    ap.add_argument("--verdicts", nargs="*", default=[])
    ap.add_argument("--out")
    ap.add_argument("--show-identities", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows, verdicts = [], []
    try:
        for f in a.rows:
            rows += load_list(f)
        for f in a.verdicts:
            verdicts += load_list(f)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    errs = problems(rows)
    if not errs:
        errs = verdict_problems(rows, verdicts)
    if not errs:
        merged = merge(rows, verdicts)
        errs = [f"after the verdicts, {e}" for e in problems(merged)]
    if errs:
        for e in errs:
            print(f"refused: {e}", file=sys.stderr)
        print(f"{len(errs)} problems; nothing written. Fix the rows and run again.", file=sys.stderr)
        return 2
    text = json.dumps(merged, ensure_ascii=False, indent=2) if a.json else render(merged, a.show_identities)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Saved: {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
