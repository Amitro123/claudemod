#!/usr/bin/env python3
"""Merge case cards and sweeper leads into leads.json, deterministically. Stdlib only.

    python merge_cards.py --cards <folder> [--sweep a.json b.json ...] --expect 1,2,3 --out leads.json [--log dedupe.md] [--repair-escapes]

`--expect` lists the card ids: each must exist as `<folder>/<id>.json` and parse, else exit 2 naming
them before anything is written. Every lead of each card's `complete.siblings` and of each sweeper
file (an array) is kept field for field, plus `found_by` (card id or `sweeper`). Two leads are merged
only when they are exact duplicates: the same file and the same set of line ranges in `where`, and the
same words and comparison operators (`<`, `>`, `<=`, `>=`, `==`, `!=`) in `what` (case, spacing and other punctuation ignored). The stronger level is kept (reproduced >
read > suspect > inferred; tie: more filled fields, then first) and gets `also_found_by` and
`merged_from`. A `where` that cannot be parsed is never merged. Every other same-file pair within 10
lines, and every pair whose line ranges intersect (`path:15` is 15-15), stays as two leads with all their
fields; both get `possible_duplicate_of` (the other's `where`) and the log lists the pair with the
reason (`lines overlap`, `similar wording` at word similarity 0.5 or more, else `within 10 lines`, plus the
similarity). When exact duplicates differ in other fields, the winner gains the fields it lacks and a
conflicting value of the loser is recorded under `merged_variants`; nothing is dropped silently.
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
RANK = ("reproduced", "read", "suspect", "inferred")
WHERE_RE = re.compile(r"^(?P<f>[^\s,]+?):(?P<r>L?\d+(?:\s*-\s*L?\d+)?(?:\s*,\s*L?\d+(?:\s*-\s*L?\d+)?)*)$")
OVERLAP, SIMILAR, NEARBY = "lines overlap", "similar wording", "within 10 lines"
SIMILAR_AT = 0.5  # word similarity from which a flagged pair is called "similar wording"
OWN_KEYS = ("found_by", "also_found_by", "merged_from", "merged_variants", "possible_duplicate_of", "case")
WORD_RE = re.compile(r"[a-z0-9_]+")
IDENT_RE = re.compile(r"[a-z0-9_]+|[<>=!]+")  # identity tokens: words plus comparison operators (`<` and `>` are different claims)


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


def exact_key(lead: dict, parsed) -> tuple | None:
    """Identity of an exact duplicate: the file and the set of line ranges of `where`, and the words of `what`
    (case, spacing and other punctuation ignored; comparison operators count). None when `where` cannot be parsed or `what` is empty: never merged."""
    text = str(lead.get("what") or "").lower()
    what = tuple(IDENT_RE.findall(text)) if WORD_RE.search(text) else ()
    if not parsed or not what:
        return None
    return parsed[0], frozenset(parsed[1]), what


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
        leadsio.validate_leads(data, os.path.basename(p))  # objects, and the same complete/siblings rules
        for x in data:
            leads.append({**x, "found_by": "sweeper"})
        print(f"sweep file {p}: {len(data)} leads", file=sys.stderr)
    print(f"sweep files loaded: {len(paths)}", file=sys.stderr)
    return leads


def dedupe(raw: list[dict]):
    """Return (final leads, merges, possible duplicates); merges are (i, j, score), possible are (i, j, score, reason) over raw."""
    parsed = [parse_where(lead.get("where")) for lead in raw]
    toks = [words(lead.get("what")) for lead in raw]
    parent = list(range(len(raw)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    merges, possible = [], []
    first: dict[tuple, int] = {}
    for i in range(len(raw)):  # exact duplicates only: same normalized `where` set and same normalized `what`
        key = exact_key(raw[i], parsed[i])
        if key is None:
            continue
        if key in first:
            merges.append((first[key], i, 1.0))
            parent[find(i)] = find(first[key])
        else:
            first[key] = i
    for i in range(len(raw)):
        for j in range(i + 1, len(raw)):
            if find(i) == find(j) or not parsed[i] or not parsed[j] or parsed[i][0] != parsed[j][0]:
                continue
            g = gap(parsed[i][1], parsed[j][1])
            if g <= NEAR:  # kept apart whatever the wording; a person decides
                sc = jaccard(toks[i], toks[j])
                possible.append((i, j, sc, OVERLAP if g <= 0 else SIMILAR if sc >= SIMILAR_AT else NEARBY))
    groups: dict[int, list[int]] = {}
    for i in range(len(raw)):
        groups.setdefault(find(i), []).append(i)
    final, out_of = [], {}
    for root, idxs in groups.items():
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
            variants = []
            for i in others:  # nothing the loser said is dropped: fill gaps, record conflicts
                diff = {}
                for k, v in raw[i].items():
                    if k in OWN_KEYS or v in (None, "", [], {}):
                        continue
                    if out.get(k) in (None, "", [], {}):
                        out[k] = v
                    elif out[k] != v:
                        diff[k] = v
                if diff:
                    variants.append({"found_by": str(raw[i]["found_by"]), "where": str(raw[i].get("where")), **diff})
            if variants:
                out["merged_variants"] = variants
        out_of[root] = out
        final.append((min(idxs), out))
    for i, j, _, _ in possible:  # flag each way; never merges or drops anything
        a, b = out_of[find(i)], out_of[find(j)]
        if a is not b:
            for x, y in ((a, b), (b, a)):
                refs = x.setdefault("possible_duplicate_of", [])
                if str(y.get("where")) not in refs:
                    refs.append(str(y.get("where")))
    final.sort(key=lambda t: t[0])
    return [o for _, o in final], merges, possible


def tally(leads: list[dict], key: str) -> str:
    c = Counter(str(lead.get(key) or "-") for lead in leads)
    return ", ".join(f"{k}: {v}" for k, v in sorted(c.items())) or "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", required=True, help="folder holding <id>.json cards")
    ap.add_argument("--sweep", nargs="*", action="extend", default=[],
                    help="sweeper files (each a JSON array of leads); every occurrence of the flag counts")
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

    lines = ["# Dedupe log", "", "## Merges"]
    lines += [f"- {ref(i)} + {ref(j)} (exact duplicate)" for i, j, _ in merges] or ["- none"]
    lines += ["", "## Possible duplicates (kept)"]
    lines += [f"- {ref(i)} / {ref(j)} ({why}; similarity {sc:.2f}; not merged, a person decides)" for i, j, sc, why in possible] or ["- none"]
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
    if possible:
        print(f"possible duplicates: {len(possible)} (see log)")
    for i, s in enumerate(final):
        where = lint_leads.text(s.get("where")) or f"#{i + 1}"
        for rule, sev, msg in lint_leads.lint(s):
            print(f"{where} | {rule} | {sev} | {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
