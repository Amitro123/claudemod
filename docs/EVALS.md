# Evaluation guide

How the claudemod eval system works, how to run it, and how to turn production failures into new
test cases. For the complete guide to LLM evaluation concepts (offline vs online, scorer types,
regression gates), see [The Complete Guide to LLM Evaluation](https://machinelearningmastery.com/the-complete-guide-to-llm-evaluation/).

## Eval layers

The project uses two eval layers, matching the offline/online distinction in the guide:

### Layer 1: Offline (free, every push)

Deterministic checks that run in CI on every push and PR. No model calls, no API keys.

| What | Where | CI workflow |
|---|---|---|
| Plugin validation + unit tests (all mods) | `claude plugin validate` + `claude plugin test` | `mods.yml` |
| Factory history tests (real-git) | `node --test plugins/factory/tests/history.real-git.mjs` | `mods.yml` (factory-history job) |
| Inspector pytest suite | `python -m pytest plugins/inspector/tests -q` | `inspector.yml` |
| Mistake-brain pytest suite | `python -m pytest plugins/brain-hud/tests/skill -q` | `skill.yml` |
| Shared texts sync check | `node tools/sync-texts.mjs --check` | `texts.yml` |

Run locally:

```bash
# Factory (equivalent to evals/run-offline.sh)
cd plugins/factory && claude plugin validate . && claude plugin test .

# Inspector (equivalent to evals/run-offline.sh)
cd plugins/inspector && claude plugin validate . && python3 -m pytest tests -q
```

### Layer 2: Online (paid, manual)

Cases that call the model API. Each case builds a small repository with a known answer and measures
whether the skill finds it. Run manually before a release or via the `regression evals` workflow.

**Inspector** (6 cases, ~$2–3 per full run):

| Case | Type | Measures |
|---|---|---|
| `backtest-01` | Value (key bugs found) | Recall on 8 key graders (K1, K2, K8, K12, K14–K17) from real history |
| `chain-01`, `sec-01`, `sibling-01`, `history-01` | Discipline (correct reasoning) | Regression on past skill bugs |
| `control-01` | False-positive control | No spurious high-confidence leads |

**Factory** (13 cases, ~$4–5 per full run):

| Case | Type | Measures |
|---|---|---|
| `appr-04` | Value (Δ with/without) | Sensitive-area escalation rule |
| `plan-01` | Value (Δ with/without) | Task sizing and planning quality |
| `spec-01` | Value (Δ with/without) | Spec criteria quality |
| `sec-01/02`, `code-01/02`, `appr-01/02/03` | Controls | False-positive and regression checks |
| `build-01/02`, `spec-02` | Discipline | Builder and spec-writer guardrails |

Run all:

```bash
cd plugins/inspector && evals/run-all.sh                  # all inspector cases
cd plugins/factory   && evals/run-all.sh                  # all factory cases
RUNS=3 evals/run-all.sh appr-04 plan-01 spec-01          # key cases only, 3 runs
```

Run via GitHub Actions (manual trigger, requires `ANTHROPIC_API_KEY` secret):

```
Actions → regression evals (paid) → Run workflow → choose plugin, set runs
```

## Scorer types in this project

Mapped to the terminology in the guide:

| Scorer type | Guide term | Examples in this project |
|---|---|---|
| Regex on output files | Rule-based / deterministic | `skill-fired.md`, `does-not-approve.md`, `verdict-pass.md` |
| File-content assertions | Rule-based / deterministic | `committed.md`, `tests-were-run.md`, `no-edit-out-of-scope.md` |
| LLM judge with rubric | LLM-as-judge | `plan-judgement.md`, `scope-judgement.md`, `finding-quality.md` |
| Pytest assertions | Unit test | `test_evidence.py`, `test_golden_history.py`, `test_gate_check.py` |
| Scorecard (precision/recall) | Aggregate metrics | `scorecard.py` on inspector runs |

## Regression gates

### Free gate (CI, every push)

All workflows in `.github/workflows/` must pass. These are branch protection checks.

### Paid gate (manual, before release)

1. Run key cases with `RUNS=3` via the `regression evals` workflow or locally.
2. For inspector, score the run and check thresholds:
   ```bash
   python3 evals/scorecard.py score --merged merged.json [--gold gold.json] --format json > /tmp/row.json
   python3 evals/gate/scorecard_gate.py --row /tmp/row.json
   ```
   `scorecard_gate.py` reads `evals/gate/thresholds.json` and exits non-zero if a threshold is
   breached. A configured (non-null) threshold whose metric is missing from the row also fails;
   pass `--allow-missing` to downgrade to a warning during development.

   Current provisional thresholds:
   - **recall_min 0.75** — the meaningful gate (recall on gold-file bugs).
   - **precision_min 0.90** — real runs show 0.94–0.97; the original 0.70 never bites so it was
     raised. This is still a floor, not a target.
   - **not_real_max** — TODO, set after baseline runs.

   Thresholds are currently **provisional** (see `status` field); update them after
   recording 2–3 baseline runs on a fixed project.
3. For factory, compare the summary table from `run-all.sh` against previous runs. The key
   value-measuring cases are `appr-04`, `plan-01`, `spec-01` (see FACTORY-SUITE.md for expected Δ).

### What needs a human

- **Baseline runs**: run the key cases 2–3 times on the current version to establish baseline
  numbers. Record them with `scorecard.py score --append history.jsonl`. Then update
  `thresholds.json` with real values and set `status` to `"baselined"`.
- **Setting the secret**: add `ANTHROPIC_API_KEY` (or your provider's auth vars) as a repository
  secret in GitHub Settings → Secrets → Actions.
- **Choosing final thresholds**: the values in `thresholds.json` are starting points from
  RELEASING.md proposals. Adjust after observing variance across runs.

## Turning failures into golden cases

The project already does this—inspector's `backtest-01` graders K15–K17 were added after real runs
found three bugs the original key didn't include. Follow the same pattern:

1. **Identify the failure.** A production run (or a user report) surfaces a bug the skill missed,
   or a false positive the skill produced.
2. **Reproduce it.** Find the commit range or PR where the failure lives. If possible, isolate it
   in a small repository (like the existing `scaffold.sh` scripts do).
3. **Add a grader.** Write a regex or LLM-judge grader in `evals/<case>/graders/` that checks for
   the specific failure. Regex graders are preferred when a deterministic check is possible.
4. **Verify the case.** Run the case with `--runs 1` to confirm the grader catches the failure
   (with the current skill) or passes (after the fix).
5. **Add to the key.** If the failure is a real bug from production, add it to the backtest key
   or the gold file so recall is measured against it.

### Example: K15–K17 in backtest-01

```
plugins/inspector/evals/backtest-01-followups-at-50/graders/key-K15.md
plugins/inspector/evals/backtest-01-followups-at-50/graders/key-K16.md
plugins/inspector/evals/backtest-01-followups-at-50/graders/key-K17.md
```

These were added after the case readers found three real bugs not in the original key. The bugs
were verified on main, then pinned as graders so future versions must also find them.

## Post-release monitoring

No automated post-release monitoring is in place yet. Until it is, the feedback loop is:

1. Run the inspector on a real project after a release (the acceptance run from RELEASING.md).
2. Score it with `scorecard.py` and append to the history.
3. Compare with the previous version: `scorecard.py compare --history history.jsonl`.
4. If recall drops or precision falls, investigate the uncovered items and add graders.

This is a manual analogue of the online evaluation layer described in the guide. Automating it
(e.g. a scheduled workflow on a canary project) is a future improvement.
