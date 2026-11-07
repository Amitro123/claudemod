#!/usr/bin/env bash
# Runs backtest-01 twice, side by side: the inspector alone, and the inspector with the model-router
# plugin loaded beside it (its hooks, its work budget, its routed-worker). Paid; same needs as run-all.sh.
#
#   evals/run-with-router.sh <path to the model-router plugin folder>
#   RUNS=3 evals/run-with-router.sh ../keshet-claude-skills/plugins/model-router
#
# A case may load other plugins only from under the folder `claude plugin eval` runs on, so this
# builds that folder in a temporary directory: inspector/, model-router/ and two copies of the case.
set -eu
ROUTER="$(cd "${1:?usage: run-with-router.sh <model-router plugin folder>}" && pwd)"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # plugins/inspector
RUNS="${RUNS:-3}"; JOBS="${JOBS:-6}"; MAX_COST="${MAX_COST:-9}"
W="$(mktemp -d "${TMPDIR:-/tmp}/inspector-router-XXXXXX")"
cp -r "$HERE" "$W/inspector"; cp -r "$ROUTER" "$W/model-router"
rm -rf "$W/inspector/evals/results" "$W/model-router/evals/results"
for v in solo both; do
  d="$W/evals/bt-$v"; mkdir -p "$d"
  cp -r "$HERE/evals/backtest-01-followups-at-50/." "$d/"
  sed -i.bak "s/^name: .*/name: bt-$v/" "$d/case.yaml" && rm -f "$d/case.yaml.bak"
  if [ "$v" = solo ]; then echo "plugins: [../../inspector]" >> "$d/case.yaml"
  else echo "plugins: [../../inspector, ../../model-router]" >> "$d/case.yaml"; fi
done
cd "$W"
claude plugin eval . --case 'bt-*' --runs "$RUNS" -j "$JOBS" --max-cost-usd "$MAX_COST" --ablation none \
  --scaffold --no-publish --trust-plugin --json out.json --allow-tools Bash Write Agent > log.txt 2>&1 || true
python3 - out.json <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1]))
print("%-8s %-5s %-6s %-28s %6s" % ("case", "run", "score", "key bugs", "cost"))
for c in r["cases"]:
    for i, a in enumerate(c["arms"]["with"]):
        g = {x["name"]: x for x in a.get("graders", [])}
        keys = sorted(n[4:] for n in g if n.startswith("key-") and g[n]["passed"])
        print("%-8s %-5d %6.2f %-28s %6.2f" % (c["name"], i, a["score"], ",".join(keys), a["costUsd"]))
print("total: $%.2f   (folder: %s)" % (r.get("costUsd", 0), sys.argv[1]))
PYEOF
