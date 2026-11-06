# inspector evals

Two layers. The first is free and runs in CI; the second costs model calls and is run by hand.

## 1. Free: the collector against known answers (CI)

```bash
python -m pytest plugins/inspector/tests -q        # 27 tests, ~10 s, no model
```

- `test_evidence.py`: small repositories built in the test, one per behaviour:
  - a bug, its fix and a fix of that fix;
  - a feature PR with a "fix lint" commit;
  - a rename, an octopus merge, instruction Markdown;
  - a shallow clone, the `--unit`/`--path`/`--since` scopes, the truncation warning.
- `test_golden_history.py`: the collector on this repository's own history up to #72, against
  labels read by hand:
  - 16 fixes and 20 non-fixes;
  - six fix commits with the unit whose lines they changed;
  - one fix that only adds lines, so it has no culprit.

  CI checks out the full history for it (`fetch-depth: 0`); a shallow clone skips it.

## 2. Paid: what the skill does with the evidence (5 cases)

Each case builds a 4–8 PR repository with a known answer and asks for an investigation. Each case
has one or two free regex graders on the case file and one or two LLM-judged ones.

| Case | Asks about | The answer |
|---|---|---|
| `sibling-01-copy-left-behind` | PR #2 | `to_docs` still unquoted (the fix covered `to_claude_md`); `to_csv` is not a bug |
| `chain-01-culprit-is-a-fix` | PR #3 | the culprit is #2, itself a fix: a fix-of-fix |
| `sec-01-redaction-sibling` | PR #2 | `--password value` (space) still leaks; `--password=value` is redacted |
| `history-01-whole-history` | the whole history, 8 PRs | `email_body` still unescaped; the chain #6 → #8; CSV and the email subject are not leads |
| `control-01-complete-fix` | PR #2 | nothing left: no reproduced or read lead (false-positive check) |

```bash
cd plugins/inspector
claude plugin eval . --runs 2 -j 4 --max-cost-usd 8 --ablation with-without \
  --scaffold --no-publish --trust-plugin --json evals/results/out.json --allow-tools Bash Write
```

The skill needs git, so the cases grant Bash. The eval runs Bash only inside a sandbox: on Linux,
`apt install bubblewrap socat` first. A full run (5 cases × 2 arms × 2 runs) took 3 minutes and
cost $2.28.

### What it measures, and what it doesn't

- **A regression suite for the skill's discipline.** The 2026-11-06 runs caught four real bugs in
  the skill. Each was fixed in SKILL.md and is now pinned by a case:
  - leads with no promise behind them (`control`, `history`; now the "Breaks" column);
  - no fallback when `<scratch>` can't be written;
  - the case file written to the default path, not the one the user named (`chain`);
  - one more miss of the same file, not diagnosed (no `--keep-temp` on that run).
- **Not the skill's value.** Without the plugin, Claude also passes these small cases
  (0.94 against 0.90 on the last run): on a 4–8 PR repository the question itself does the
  skill's job. Its value shows on a real history, which is what the backtest in
  `docs/2026-11-06-review.md` measures. That run takes ~15 minutes and ~240k tokens, so it is
  run on purpose, not as a routine check.
- Two runs per case is a coarse signal. Use `--runs 3` or more before calling a change better.
