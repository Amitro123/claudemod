#!/usr/bin/env python3
"""Per-version quality record for an Inspector run. A maintainers' tool, stdlib only; not shipped in the skill folder.

  scorecard.py score --merged merged.json [--gold gold.json] [--metrics metrics.json]
                     [--append history.jsonl] [--label TEXT] [--date YYYY-MM-DD] [--format json|md|both]
  scorecard.py compare --history history.jsonl

`score` reads the handoff input (leads with verdict, category, reach), computes one row, prints it as JSON
and as a short Markdown table, and appends the JSON row to the history file when --append is given.
`compare` prints the last two rows of a history file side by side with the deltas.
Gold files for real projects belong OUTSIDE the repository; see README-scorecard.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

VERDICTS = ("REAL", "REAL-LOW", "UNVERIFIABLE", "unverified", "NOT REAL")
CONFIRMED = ("REAL", "REAL-LOW")
PLUGIN_JSON = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
TEXT_FIELDS = ("what", "breaks", "change", "test")  # content only; `where` is matched separately as the path


def load_json(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"scorecard: cannot read {path}: {exc}")


def read_leads(path: str) -> list[dict]:
    data = load_json(path)
    if isinstance(data, dict):
        data = data.get("leads", [data])
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise SystemExit(f"scorecard: {path}: expected a JSON array of leads")
    return data


def verdict_of(lead: dict) -> str:
    v = lead.get("verdict")
    return v if v in VERDICTS else "unverified"


def duplicate_clusters(leads: list[dict]) -> list[list[str]]:
    """Connected groups of leads linked by possible_duplicate_of (either direction); size >= 2."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for lead in leads:
        refs = lead.get("possible_duplicate_of") or []
        for other in ([refs] if isinstance(refs, str) else refs):
            if lead.get("where") and isinstance(other, str):
                parent[find(lead["where"])] = find(other)
    groups: dict[str, set[str]] = {}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)
    return sorted(sorted(g) for g in groups.values() if len(g) > 1)


def lead_text(lead: dict) -> str:
    return " ".join(str(lead.get(k, "")) for k in TEXT_FIELDS).lower()


def score_gold(leads: list[dict], gold: list[dict]) -> dict:
    """An item is covered when one lead matches a paths_any substring AND a words_any keyword (case-insensitive).
    A lead the verifier rejected (NOT REAL) does not cover anything."""
    live = [l for l in leads if verdict_of(l) != "NOT REAL"]
    covered, uncovered = [], []
    for item in gold:
        paths = [p.lower() for p in item.get("paths_any", [])]
        words = [w.lower() for w in item.get("words_any", [])]
        hit = next((l for l in live if any(p in str(l.get("where", "")).lower() for p in paths)
                    and any(w in lead_text(l) for w in words)), None)
        if hit:
            covered.append({"id": item.get("id"), "title": item.get("title"), "lead": hit.get("where"),
                            "verdict": verdict_of(hit), "severity": item.get("severity")})
        else:
            uncovered.append({"id": item.get("id"), "title": item.get("title"), "severity": item.get("severity")})
    return {"items": len(gold), "covered": len(covered), "recall": round(len(covered) / len(gold), 3) if gold else None,
            "covered_items": covered, "uncovered_items": uncovered}


def find_key(obj, names: tuple[str, ...]):
    """First numeric value under any of `names`, searched depth-first (a run-metrics report nests its totals)."""
    if isinstance(obj, dict):
        for n in names:
            if isinstance(obj.get(n), (int, float)) and not isinstance(obj.get(n), bool):
                return obj[n]
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


def score_metrics(metrics, confirmed: int) -> dict:
    cost = find_key(metrics, ("cost_usd", "total_cost_usd", "cost"))
    return {"cost_usd": cost, "requests": find_key(metrics, ("requests", "request_count", "total_requests")),
            "minutes": find_key(metrics, ("minutes", "duration_minutes")),
            "cost_per_verified_lead": round(cost / confirmed, 4) if cost is not None and confirmed else None}


def plugin_version(path: Path = PLUGIN_JSON) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def build_row(leads, gold=None, metrics=None, label=None, date=None, version=None) -> dict:
    counts = {v: 0 for v in VERDICTS}
    for l in leads:
        counts[verdict_of(l)] += 1
    confirmed = counts["REAL"] + counts["REAL-LOW"]
    denom = len(leads) - counts["UNVERIFIABLE"]
    security = [l for l in leads if l.get("category") == "security"]
    clusters = duplicate_clusters(leads)
    return {"version": version if version is not None else plugin_version(), "label": label,
            "date": date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            "leads": len(leads), "verdicts": counts, "confirmed": confirmed,
            "precision": round(confirmed / denom, 3) if denom else None, "unverifiable": counts["UNVERIFIABLE"],
            "not_real": counts["NOT REAL"],
            "security": {"labelled": len(security), "survived": sum(verdict_of(l) in CONFIRMED for l in security)},
            "duplicate_clusters": len(clusters), "duplicate_cluster_members": clusters,
            "gold": score_gold(leads, gold) if gold is not None else None,
            "cost": score_metrics(metrics, confirmed) if metrics is not None else None}


def fmt(v) -> str:
    return "n/a" if v is None else str(v)


def markdown(row: dict) -> str:
    c = row["verdicts"]
    L = [f"### Inspector scorecard: version {fmt(row['version'])}" + (f" ({row['label']})" if row.get("label") else ""), "",
         "| Measure | Value |", "|---|---|",
         f"| Leads | {row['leads']} |",
         "| Verdicts | " + ", ".join(f"{v} {c[v]}" for v in VERDICTS) + " |",
         f"| Precision (REAL + REAL-LOW) / (leads - UNVERIFIABLE) | {fmt(row['precision'])} "
         f"({row['confirmed']} / {row['leads'] - row['unverifiable']}; UNVERIFIABLE {row['unverifiable']} left out) |",
         f"| NOT REAL | {row['not_real']} |",
         f"| Security-labelled | {row['security']['labelled']}, survived the verifier {row['security']['survived']} |",
         f"| Possible-duplicate clusters | {row['duplicate_clusters']} |"]
    g = row.get("gold")
    L.append("| Recall on gold | " + (f"{fmt(g['recall'])} ({g['covered']} / {g['items']})" if g else "n/a (no gold file)") + " |")
    m = row.get("cost")
    L.append("| Cost per verified lead | " + (f"{fmt(m['cost_per_verified_lead'])} USD (cost {fmt(m['cost_usd'])}, requests "
             f"{fmt(m['requests'])}, minutes {fmt(m['minutes'])})" if m else "n/a (no metrics file)") + " |")
    if g:
        L += ["", "Covered gold items:"]
        L += [f"- {i['id']}: {i['title']} <- lead `{i['lead']}` ({i['verdict']})" for i in g["covered_items"]] or ["- none"]
        L += ["", "Uncovered gold items:"]
        L += [f"- {i['id']}: {i['title']}" for i in g["uncovered_items"]] or ["- none"]
    return "\n".join(L) + "\n"


def flatten(row: dict) -> dict:
    flat = {"version": row.get("version"), "date": row.get("date"), "label": row.get("label"), "leads": row.get("leads"),
            "precision": row.get("precision"), "unverifiable": row.get("unverifiable"), "not_real": row.get("not_real"),
            "security_labelled": (row.get("security") or {}).get("labelled"),
            "security_survived": (row.get("security") or {}).get("survived"),
            "duplicate_clusters": row.get("duplicate_clusters"),
            "recall": (row.get("gold") or {}).get("recall"),
            "cost_per_verified_lead": (row.get("cost") or {}).get("cost_per_verified_lead")}
    for v in VERDICTS:
        flat[f"verdict_{v}"] = (row.get("verdicts") or {}).get(v)
    return flat


def compare_markdown(a: dict, b: dict) -> str:
    fa, fb = flatten(a), flatten(b)
    L = ["| Measure | Previous | Latest | Delta |", "|---|---|---|---|"]
    for k in fa:
        x, y = fa[k], fb[k]
        num = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y))
        L.append(f"| {k} | {fmt(x)} | {fmt(y)} | {(f'{y - x:+.3g}') if num else ''} |")
    return "\n".join(L) + "\n"


def read_history(path: str) -> list[dict]:
    rows = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"scorecard: cannot read {path}: {exc}")
    for n, line in enumerate(lines, 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                raise SystemExit(f"scorecard: {path} line {n}: not JSON")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("score", help="score one run")
    s.add_argument("--merged", required=True, help="the handoff input: a JSON array of leads (verdict, category, reach)")
    s.add_argument("--gold", help="optional gold file kept outside the repository")
    s.add_argument("--metrics", help="optional JSON: a run-metrics report or {cost_usd, requests, minutes}")
    s.add_argument("--append", help="append the JSON row to this JSONL history file")
    s.add_argument("--label", help="free text stored with the row (for example the scope)")
    s.add_argument("--date", help="row date, default today (UTC)")
    s.add_argument("--plugin-json", help="plugin.json to read the version from (default: this checkout's)")
    s.add_argument("--format", choices=("json", "md", "both"), default="both")
    c = sub.add_parser("compare", help="last two history rows side by side")
    c.add_argument("--history", required=True)
    a = ap.parse_args(argv)
    if a.mode == "compare":
        rows = read_history(a.history)
        if len(rows) < 2:
            print(f"scorecard: {a.history} has {len(rows)} row(s); compare needs two", file=sys.stderr)
            return 2
        sys.stdout.write(compare_markdown(rows[-2], rows[-1]))
        return 0
    gold = load_json(a.gold) if a.gold else None
    if gold is not None and not (isinstance(gold, list) and all(isinstance(i, dict) for i in gold)):
        raise SystemExit(f"scorecard: {a.gold}: expected a JSON list of gold items")
    row = build_row(read_leads(a.merged), gold, load_json(a.metrics) if a.metrics else None, a.label, a.date,
                    plugin_version(Path(a.plugin_json)) if a.plugin_json else None)
    if a.append:
        with open(a.append, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if a.format in ("json", "both"):
        print(json.dumps(row, ensure_ascii=False))
    if a.format in ("md", "both"):
        if a.format == "both":
            print()
        sys.stdout.write(markdown(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
