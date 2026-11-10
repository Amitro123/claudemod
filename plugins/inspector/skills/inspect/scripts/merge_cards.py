#!/usr/bin/env python3
"""Merge case cards and sweeper leads into leads.json, deterministically. Stdlib only.

    python merge_cards.py --cards <folder> [--sweep a.json b.json ...] --expect 1,2,3 --out leads.json [--log dedupe.md] [--repair-escapes]

`--expect` lists the card ids: each must exist as `<folder>/<id>.json` and parse, else exit 2 naming
them before anything is written. Every lead of each card's `complete.siblings` and of each sweeper
file (an array) is kept field for field, plus `found_by` (card id or `sweeper`). Only an exact duplicate
is merged: the same normalized `where` (file and line-range set) and the same normalized `what` text.
The stronger level is kept (reproduced > read > suspect > inferred; tie: more filled fields, then first)
and gets `also_found_by` and `merged_from`. Word similarity never deletes a lead: same-file leads within
10 lines whose words (length >= 4) have Jaccard similarity >= 0.5 are both kept, each with
`possible_duplicate_of` (the other's `where`), and listed under "Possible duplicates (kept)" in the log.
A `where` that cannot be parsed is never merged.
`--repair-escapes` (opt-in; default is to refuse): a card or sweeper file that fails with an invalid
backslash escape (a regex class like backslash-s written with one backslash) gets every stray backslash doubled, is re-parsed,
kept as `<name>.orig` and named in the log. Then the lint_leads checks are printed (they change nothing). Exit 0 ok, 2 invalid input.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leadsio  # noqa: E402
import lint_leads  # noqa: E402

NEAR = 10
THRESHOLD = 0.5
RANK = ("reproduced", "read", "suspect", "inferred")
WHERE_RE = re.compile(r"^(?P<f>[^\s,]+?):(?P<r>L?\d+(?:\s*-\s*L?\d+)?(?:\s*,\s*L?\d+(?:\s*-\s*L?\d+)?)*)$")
WORD_RE = re.compile(r"[a-z0-9_]+")


def parse_where(w: object):
    """(file, [(start, end), ...]) or None when the string cannot be read safely."""
    if not isinstance(w, str):
        return None
    m = WHERE_RE.match(w.strip())
    if not m:
        return None
    rs = []
    for tok in m["r"].split(","):
        nums = [int(n) for n in re.findall(r"\d+", tok)]
        rs.append((min(nums), max(nums)))
    return m["f"].replace("\\", "/"), rs


def gap(a, b) -> int:
    """Smallest distance between two range lists; 0 or negative when they overlap."""
    return min(max(s1, s2) - min(e1, e2) for s1, e1 in a for s2, e2 in b)


def words(s: object) -> set[str]:
    return {w for w in WORD_RE.findall(str(s or "").lower()) if len(w) >= 4}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def level_rank(lead: dict) -> int:
    v = str(lead.get("level") or "").strip().lower()
    for i, k in enumerate(RANK):
        if v.startswith(k):
            return i
    return len(RANK)


def filled(lead: dict) -> int:
    return sum(v not in (None, "", [], {}) for v in lead.values())


def best(group: list[dict]) -> dict:
    return min(group, key=lambda lead: (level_rank(lead), -filled(lead)))  # min is stable: first wins a tie


def die(msg: str) -> int:
    print(f"merge_cards.py: {msg}", file=sys.stderr)
    return 2


_ESC_RE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _double_stray(m: "re.Match[str]") -> str:
    return m.group(0) if m.group(1) else "\\\\"


def repair_escapes(path: str, exc: Exception) -> bool:
    """Double stray backslashes in `path` when `exc` is an invalid-escape error; True when repaired and re-parsed.

    The original bytes are kept as `<path>.orig`; the file is rewritten only after the repaired text parses."""
    if not isinstance(exc, json.JSONDecodeError) or "escape" not in exc.msg:
        return False
    with open(path, "rb") as f:
        raw = f.read()
    fixed = _ESC_RE.sub(_double_stray, raw.decode("utf-8"))
    try:
        json.loads(fixed)
    except ValueError:
        return False
    with open(path + ".orig", "wb") as f:
        f.write(raw)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(fixed)
    return True


def load_cards(folder: str, ids: list[str], repair: bool = False, repaired: list[str] | None = None) -> list[dict]:
    leads, bad = [], []
    for cid in ids:
        p = os.path.join(folder, f"{cid}.json")
        if not os.path.isfile(p):
            bad.append(f"card {cid}: missing ({p})")
            continue
        if repair and repaired is not None:
            try:
                with open(p, encoding="utf-8") as f:
                    json.load(f)
            except ValueError as exc:
                if repair_escapes(p, exc):
                    repaired.append(f"card {cid} ({p})")
            except OSError:
                pass
        try:
            items = leadsio.read_items(p)
        except leadsio.LeadsError as exc:
            bad.append(f"card {cid}: {exc}")
            continue
        for s in leadsio.leads_of(items):
            leads.append({**s, "found_by": cid})
    if bad:
        raise leadsio.LeadsError("; ".join(bad))
    return leads


def load_sweeps(paths: list[str], repair: bool = False, repaired: list[str] | None = None) -> list[dict]:
    leads = []
    for p in paths:
        try:
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except ValueError as exc:
                if not (repair and repaired is not None and repair_escapes(p, exc)):
                    raise
                repaired.append(f"sweep ({p})")
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
        except (OSError, ValueError) as exc:
            raise leadsio.LeadsError(f"{p}: invalid JSON or unreadable ({exc})")
        if not isinstance(data, list):
            raise leadsio.LeadsError(f"{p}: expected an array of leads")
        for i, x in enumerate(data):
            if not isinstance(x, dict):
                raise leadsio.LeadsError(f"{os.path.basename(p)}[{i}]: expected an object")
            leads.append({**x, "found_by": "sweeper"})
    return leads


def norm_text(s: object) -> str:
    return " ".join(str(s or "").lower().split())


def exact_key(lead: dict, parsed) -> tuple | None:
    """Identity of an exact duplicate: the same file and line-range set in `where`, and the same `what` text
    (case and whitespace ignored). None when `where` cannot be parsed: such a lead is never merged."""
    if not parsed:
        return None
    return parsed[0], frozenset(parsed[1]), norm_text(lead.get("what"))


def dedupe(raw: list[dict]):
    """Return (final leads, merges, possible); merges/possible are (i, j, score) over raw.

    Only an exact duplicate is merged. Lexical similarity never deletes a lead: a nearby same-file pair
    with word similarity >= THRESHOLD keeps both leads, each listing the other's `where` in
    `possible_duplicate_of`. `possible` also holds the nearby pairs below THRESHOLD (listed in the log only)."""
    parsed = [parse_where(lead.get("where")) for lead in raw]
    toks = [words(lead.get("what")) for lead in raw]
    keys = [exact_key(lead, parsed[i]) for i, lead in enumerate(raw)]
    group_of = list(range(len(raw)))
    first: dict[tuple, int] = {}
    merges = []
    for i, k in enumerate(keys):
        if k is None:
            continue
        if k in first:
            group_of[i] = first[k]
            merges.append((first[k], i, 1.0))
        else:
            first[k] = i
    possible = []
    for i in range(len(raw)):
        for j in range(i + 1, len(raw)):
            if group_of[i] == group_of[j] or not parsed[i] or not parsed[j] or parsed[i][0] != parsed[j][0]:
                continue
            if gap(parsed[i][1], parsed[j][1]) > NEAR:
                continue
            possible.append((i, j, jaccard(toks[i], toks[j])))
    groups: dict[int, list[int]] = {}
    for i in range(len(raw)):
        groups.setdefault(group_of[i], []).append(i)
    outs: dict[int, dict] = {}
    for g, idxs in groups.items():
        win = best([raw[i] for i in idxs])
        wi = next(i for i in idxs if raw[i] is win)
        out = dict(win)
        others = [i for i in idxs if i != wi]
        if others:
            seen: list[str] = []
            for i in others:
                fb = str(raw[i]["found_by"])
                if fb != str(win["found_by"]) and fb not in seen:
                    seen.append(fb)
            out["also_found_by"] = seen
            out["merged_from"] = [str(raw[i].get("where")) for i in others]
        outs[g] = out
    for i, j, sc in possible:
        if sc < THRESHOLD:
            continue
        for a, b in ((group_of[i], group_of[j]), (group_of[j], group_of[i])):
            lst = outs[a].setdefault("possible_duplicate_of", [])
            w = str(outs[b].get("where"))
            if w not in lst:
                lst.append(w)
    return [outs[g] for g in sorted(groups)], merges, possible


def tally(leads: list[dict], key: str) -> str:
    c = Counter(str(lead.get(key) or "-") for lead in leads)
    return ", ".join(f"{k}: {v}" for k, v in sorted(c.items())) or "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", required=True, help="folder holding <id>.json cards")
    ap.add_argument("--sweep", nargs="*", default=[], help="sweeper files (each a JSON array of leads)")
    ap.add_argument("--expect", required=True, help="comma-separated card ids, e.g. 1,2,3")
    ap.add_argument("--out", required=True)
    ap.add_argument("--log")
    ap.add_argument("--repair-escapes", action="store_true",
                    help="double stray backslashes in a card that fails with an invalid escape (keeps <name>.orig, logged)")
    a = ap.parse_args(argv)
    ids = [x.strip() for x in a.expect.split(",") if x.strip()]
    if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r"[\w.-]+", x) for x in ids):
        return die(f"--expect needs distinct ids such as 1,2,3 (got {a.expect!r})")
    repaired: list[str] = []
    try:
        raw = load_cards(a.cards, ids, a.repair_escapes, repaired) + load_sweeps(a.sweep, a.repair_escapes, repaired)
    except leadsio.LeadsError as exc:
        return die(f"invalid input: {exc}")
    final, merges, possible = dedupe(raw)

    def ref(i: int) -> str:
        return f"{raw[i]['found_by']} {raw[i].get('where')}"

    similar = [t for t in possible if t[2] >= THRESHOLD]
    nearby = [t for t in possible if t[2] < THRESHOLD]
    lines = ["# Dedupe log", "", "## Merges (exact duplicates: same where, same what)"]
    lines += [f"- {ref(i)} + {ref(j)}" for i, j, _ in merges] or ["- none"]
    lines += ["", "## Possible duplicates (kept)", "",
              "Both leads are in the output, each with `possible_duplicate_of`; verify whether they are one defect."]
    lines += [f"- {ref(i)} / {ref(j)} (similarity {sc:.2f})" for i, j, sc in similar] or ["- none"]
    lines += ["", "## Nearby, different wording (kept)"]
    lines += [f"- {ref(i)} / {ref(j)} (similarity {sc:.2f})" for i, j, sc in nearby] or ["- none"]
    if repaired:
        lines += ["", "## Repaired invalid escapes (original kept as <name>.orig)"] + [f"- {r}" for r in repaired]
    unparsed = [ref(i) for i, lead in enumerate(raw) if parse_where(lead.get("where")) is None]
    if unparsed:
        lines += ["", "## Unparsable where (never merged)"] + [f"- {u}" for u in unparsed]
    counts = [f"raw: {len(raw)}", f"merged: {len(raw) - len(final)}", f"final: {len(final)}",
              f"per level: {tally(final, 'level')}", f"per category: {tally(final, 'category')}",
              f"per reach: {tally(final, 'reach')}"]
    lines += ["", "## Counts"] + [f"- {c}" for c in counts]

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    if a.log:
        with open(a.log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print("; ".join(counts))
    for r in repaired:
        print(f"repaired invalid escapes: {r} (original kept as .orig)")
    if similar:
        print(f"possible duplicates (kept): {len(similar)} (see log)")
    for i, s in enumerate(final):
        where = lint_leads.text(s.get("where")) or f"#{i + 1}"
        for rule, sev, msg in lint_leads.lint(s):
            print(f"{where} | {rule} | {sev} | {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
