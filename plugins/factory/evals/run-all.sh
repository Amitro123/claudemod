#!/usr/bin/env bash
# Runs every factory eval case ONE AT A TIME (per-case --case '<id>*'), then prints a summary table.
# WSL only. Paid: each case makes model calls (with-plugin arm + no-plugin arm unless ABLATION=none).
# Auth comes from the env vars you export yourself (OpenRouter); this script never reads or prints them.
#
#   evals/run-all.sh                      all cases
#   evals/run-all.sh spec-01 sec-02       only cases whose id starts with these
#   RUNS=3 MAX_COST=3 ABLATION=none MODEL=anthropic/claude-sonnet-5.5 evals/run-all.sh
set -u
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."                      # plugins/factory (the plugin under test; cases are evals/*/case.yaml)
RUNS="${RUNS:-1}"
MAX_COST="${MAX_COST:-1.5}"                  # USD per case (both arms together)
ABLATION="${ABLATION:-with-without}"
THRESHOLD="${THRESHOLD:-0.7}"
OUT="evals/results"; mkdir -p "$OUT"
TOOL_ARGS=(--allow-tools Bash Edit Write)
# ALLOW_TOOLS=none drops all grants; ALLOW_TOOLS="Edit Write" (no Bash) works without socat. NOTE: spec-* cases must write
# .factory/spec.md and declare no allowed_tools in case.yaml, so they need Write granted; with none their file graders throw.
if [ -n "${ALLOW_TOOLS:-}" ]; then if [ "$ALLOW_TOOLS" = none ]; then TOOL_ARGS=(); else read -r -a _t <<< "$ALLOW_TOOLS"; TOOL_ARGS=(--allow-tools "${_t[@]}"); fi; fi
KEEP_ARGS=(); [ "${KEEP_TEMP:-}" = 1 ] && KEEP_ARGS=(--keep-temp)
MODEL_ARGS=(); [ -n "${MODEL:-}" ] && MODEL_ARGS=(--model "$MODEL")

if [ "$#" -gt 0 ]; then IDS=("$@"); else IDS=(); for d in evals/*/case.yaml; do IDS+=("$(basename "$(dirname "$d")")"); done; fi

for id in "${IDS[@]}"; do
  echo "=== $id"
  # Bash/Edit/Write are granted to every case; read-only cases never list them in allowed_tools.
  claude plugin eval . --case "${id}*" --runs "$RUNS" --max-cost-usd "$MAX_COST" \
    --ablation "$ABLATION" --scaffold --no-publish --trust-plugin --threshold "$THRESHOLD" \
    "${MODEL_ARGS[@]}" --json "$OUT/out-${id}.json" "${TOOL_ARGS[@]}" "${KEEP_ARGS[@]}" \
    > "$OUT/log-${id}.txt" 2>&1
  echo "exit $?  (log: $OUT/log-${id}.txt)"
done

python3 - "$OUT" "${IDS[@]}" <<'PYEOF'
import json, os, sys
out, ids = sys.argv[1], sys.argv[2:]
rows = []
for i in ids:
    p = os.path.join(out, "out-%s.json" % i)
    if not os.path.exists(p):
        rows.append((i, "no-json", "", "", "")); continue
    try:
        d = json.load(open(p))
    except Exception as e:
        rows.append((i, "bad-json", "", "", "")); continue
    for c in d.get("cases", []):
        a = c.get("aggregates", {})
        f = lambda k: ("%.2f" % a[k]) if isinstance(a.get(k), (int, float)) else "-"
        rows.append((c.get("name", i), f("score"), f("scoreWithout"), f("delta"), f("passRate")))
print("\n%-52s %6s %6s %6s %6s" % ("case", "WITH", "W/OUT", "delta", "pass"))
for r in rows:
    print("%-52s %6s %6s %6s %6s" % r)
PYEOF
