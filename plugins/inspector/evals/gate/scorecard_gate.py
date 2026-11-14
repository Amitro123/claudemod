#!/usr/bin/env python3
"""Check a scorecard row against thresholds.json and exit non-zero if any threshold is breached.

    scorecard_gate.py --row ROW_JSON [--thresholds thresholds.json]
    scorecard_gate.py --history HISTORY_JSONL [--thresholds thresholds.json]

`--row` reads a single JSON scorecard row (the output of `scorecard.py score --format json`).
`--history` reads a JSONL history file and checks the last row.

Reads thresholds from thresholds.json (default: next to this script). A threshold set to null is
skipped. Exit 0 when all thresholds pass, 1 when at least one is breached, 2 on invalid input.
Prints a short report to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_THRESHOLDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.json")


def load_json(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"scorecard_gate: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def check(row: dict, thresholds: dict) -> list[dict]:
    t = thresholds.get("thresholds", thresholds)
    results = []

    def gate(name: str, actual, threshold, direction: str):
        if threshold is None or actual is None:
            results.append({"name": name, "status": "skipped", "actual": actual, "threshold": threshold})
            return
        if direction == "min" and actual < threshold:
            results.append({"name": name, "status": "FAIL", "actual": actual, "threshold": threshold,
                            "detail": f"{actual} < {threshold}"})
        elif direction == "max" and actual > threshold:
            results.append({"name": name, "status": "FAIL", "actual": actual, "threshold": threshold,
                            "detail": f"{actual} > {threshold}"})
        else:
            results.append({"name": name, "status": "pass", "actual": actual, "threshold": threshold})

    gate("precision_min", row.get("precision"), t.get("precision_min"), "min")

    gold = row.get("gold") or {}
    gate("recall_min", gold.get("recall"), t.get("recall_min"), "min")

    gate("not_real_max", row.get("not_real"), t.get("not_real_max"), "max")

    cost = row.get("cost") or {}
    gate("cost_per_verified_lead_max", cost.get("cost_per_verified_lead"),
         t.get("cost_per_verified_lead_max"), "max")

    gate("duplicate_clusters_max", row.get("duplicate_clusters"),
         t.get("duplicate_clusters_max"), "max")

    return results


def report(results: list[dict], status_label: str) -> str:
    lines = [f"Scorecard gate ({status_label}):", ""]
    for r in results:
        mark = {"pass": "PASS", "FAIL": "FAIL", "skipped": "SKIP"}[r["status"]]
        detail = f"  ({r.get('detail', '')})" if r.get("detail") else ""
        lines.append(f"  [{mark}] {r['name']}: actual={r['actual']} threshold={r['threshold']}{detail}")
    failed = [r for r in results if r["status"] == "FAIL"]
    lines.append("")
    if failed:
        lines.append(f"{len(failed)} threshold(s) breached.")
    else:
        lines.append("All thresholds passed.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--row", help="path to a single JSON scorecard row")
    group.add_argument("--history", help="path to a JSONL history file (checks the last row)")
    ap.add_argument("--thresholds", default=DEFAULT_THRESHOLDS, help="path to thresholds.json")
    a = ap.parse_args(argv)

    thr = load_json(a.thresholds)
    if not isinstance(thr, dict):
        print("scorecard_gate: thresholds file must be a JSON object", file=sys.stderr)
        return 2

    if a.row:
        row = load_json(a.row)
        if not isinstance(row, dict):
            print("scorecard_gate: --row must be a JSON object", file=sys.stderr)
            return 2
    else:
        try:
            text = Path(a.history).read_text(encoding="utf-8")
            lines = [json.loads(l) for l in text.splitlines() if l.strip()]
        except (OSError, ValueError) as exc:
            print(f"scorecard_gate: cannot parse history: {exc}", file=sys.stderr)
            return 2
        if not lines:
            print("scorecard_gate: history file is empty", file=sys.stderr)
            return 2
        row = lines[-1]

    status_label = thr.get("status", "unknown")
    results = check(row, thr)
    print(report(results, status_label))

    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
