#!/usr/bin/env bash
# Runs every inspector eval case ONE AT A TIME (per-case --case '<id>*'), then prints a summary table.
# Paid: each case makes model calls (with-plugin arm + no-plugin arm unless ABLATION=none).
# Linux or macOS; the cases grant Bash (the skill needs git), so the sandbox needs bubblewrap and
# socat on Linux (apt install bubblewrap socat). Auth comes from your environment; this script
# never reads or prints it.
#
#   evals/run-all.sh                       all cases
#   evals/run-all.sh backtest-01           only cases whose id starts with these
#   RUNS=3 MAX_COST=3 ABLATION=none MODEL=<model> KEEP_TEMP=1 evals/run-all.sh
set -u
cd "$(dirname "$0")/.."                      # plugins/inspector
RUNS="${RUNS:-2}"
MAX_COST="${MAX_COST:-3}"                    # USD per case (both arms together)
ABLATION="${ABLATION:-with-without}"
JOBS="${JOBS:-4}"
OUT="evals/results"; mkdir -p "$OUT"
KEEP_ARGS=(); [ "${KEEP_TEMP:-}" = 1 ] && KEEP_ARGS=(--keep-temp)
MODEL_ARGS=(); [ -n "${MODEL:-}" ] && MODEL_ARGS=(--model "$MODEL")

if [ "$#" -gt 0 ]; then IDS=("$@"); else IDS=(); for d in evals/*/case.yaml; do IDS+=("$(basename "$(dirname "$d")")"); done; fi

for id in "${IDS[@]}"; do
  echo "=== $id"
  claude plugin eval . --case "${id}*" --runs "$RUNS" -j "$JOBS" --max-cost-usd "$MAX_COST" \
    --ablation "$ABLATION" --scaffold --no-publish --trust-plugin \
    "${MODEL_ARGS[@]}" --json "$OUT/out-${id}.json" --allow-tools Bash Write "${KEEP_ARGS[@]}" \
    > "$OUT/log-${id}.txt" 2>&1
  echo "exit $?  (log: $OUT/log-${id}.txt)"
done

python3 - "$OUT" "${IDS[@]}" <<'PYEOF'
import json, os, sys
out, ids = sys.argv[1], sys.argv[2:]
print("\n%-34s %-6s %6s %6s %6s %8s" % ("case", "arm", "mean", "min", "max", "cost"))
tot = 0.0
for i in ids:
    p = os.path.join(out, "out-%s.json" % i)
    if not os.path.exists(p):
        print("%-34s no-json" % i); continue
    d = json.load(open(p)); tot += d.get("costUsd", 0) or 0
    for c in d.get("cases", []):
        for arm, runs in c.get("arms", {}).items():
            s = [r["score"] for r in runs]
            if s:
                print("%-34s %-6s %6.2f %6.2f %6.2f %8.2f" % (c["name"][:34], arm, sum(s) / len(s), min(s), max(s),
                                                       sum(r.get("costUsd", 0) for r in runs)))
print("total cost: $%.2f" % tot)
PYEOF
