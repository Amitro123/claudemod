# inspector evals

Two layers. The first is free and runs in CI; the second costs model calls and is run by hand.

## 1. Free: the collector against known answers (CI)

```bash
python -m pytest plugins/inspector/tests -q        # deterministic tests, no model
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

The offline wrapper also runs `claude plugin validate`; its exit status is nonzero if either
validation or pytest fails. A missing Claude CLI is a validation failure, not a successful
plugin run. You can still run the pytest command above separately.

## 2. Paid: what the skill does with the evidence (6 cases)

Each case builds a 4–8 PR repository with a known answer and asks for an investigation. Each case
has one or two free regex graders on the case file and one or two LLM-judged ones.

| Case | Asks about | The answer |
|---|---|---|
| `sibling-01-copy-left-behind` | PR #2 | `to_docs` still unquoted (the fix covered `to_claude_md`); `to_csv` is not a bug |
| `chain-01-culprit-is-a-fix` | PR #3 | the culprit is #2, itself a fix: a fix-of-fix |
| `sec-01-redaction-sibling` | PR #2 | `--password value` (space) still leaks; `--password=value` is redacted |
| `history-01-whole-history` | the whole history, 8 PRs | `email_body` still unescaped; the chain #6 → #8; CSV and the email subject are not leads |
| `control-01-complete-fix` | PR #2 | nothing left: no reproduced or read lead (false-positive check) |
| `backtest-01-followups-at-50` | `plugins/followups` in this repository as it was at #50, 4 cases | the 13 followups bugs that #51–#72 fixed (graders count 1, 2 and 3 matches, and check precision) |

```bash
cd plugins/inspector
claude plugin eval . --runs 2 -j 4 --max-cost-usd 8 --ablation with-without \
  --scaffold --no-publish --trust-plugin --json evals/results/out.json --allow-tools Bash Write
```

The skill needs git, so the cases grant Bash. The eval runs Bash only inside a sandbox: on Linux,
`apt install bubblewrap socat` first. A full run (5 cases × 2 arms × 2 runs) took 3 minutes and
cost $2.28.

The prompts don't name the skill: it has to trigger on its own (`skill-fired`), and the arm without
the plugin gets a question it can answer, not a request for a skill it doesn't have.

`backtest-01` clones this repository from GitHub (the scaffold runs outside the sandbox), resets it
to #50 and deletes everything after it. It is the one case that measures value.

### First backtest-01 run (2 runs per arm, before the prompts stopped naming the skill)

| Arm | Score | Bugs from the key found | Cost |
|---|---|---|---|
| with | 1.00, 0.62 | K1, K2, K8; K12 | $0.34, $0.33 (~2 min) |
| without | 0.00, 0.50 | none (it refused: the prompt named a skill it didn't have); K1, K8 | $0.05, $0.22 |

Four different key bugs with the skill, two without. That is a signal, not a result. One baseline
run was void, and the precision grader then still read the skill's own level labels; both are
fixed. Next: `--case 'backtest-01*' --runs 3`, about $1.50.

### backtest-01, 2026-11-07 (3 runs per arm; prompts no longer name the skill)

| Version | Arm | Mean score | Key bugs found per run | Precision | Calls per run |
|---|---|---|---|---|---|
| 0.2 + dossier tool | with | 0.75 | K1 · K1 · K1 K12 K8 | 3/3 | 15-17 |
| (same run) | without | 0.67 | K12 K11 · 2-3 per the judge · 2 | 1/3 | 6-7 |
| + triage and dossiers by the collector | with | 0.85 | K12 K2 K1 K8 · K1 · K1 K12 K2 | 3/3 | 14-21 |

| + case readers (Sonnet), cards, cross-check | with | 0.74 | K1 · K1 K12 · K1, and three real bugs not in the key then (now K15-K17) | 3/3 | 9-11 (main), 4 readers each |

The last row, measured: the readers started in every run, 4 in parallel. The main context fell
from 400-640k cached tokens to 88-284k, at the same time (about 2 minutes). The cost per run rose
from $0.27-0.41 to $0.52-0.57. On 4 cases, then, the readers don't pay; the skill now uses them
from a budget of 6. They kept finding three bugs the key didn't have. Checked on main, all three
are real, so they were added (K15-K17), and earlier runs' scores understate the skill.

Before the readers could start, two sandbox findings had to be fixed:
- the eval gives each Bash command its own `/tmp` and lets no command write anywhere (not `.git`,
  not the tree);
- so nothing in the skill may need a writable folder: dossiers come from a command, cards come
  back in the readers' replies, and the cross-check reads them on stdin.

### Who reads the diffs: measured on one ruler (2026-11-07)

`backtest-01` now scores by regex, one grader per key bug, anchored to the case file's Open leads
section (`key-K1` ... `key-K17`). It is deterministic and free, and it can't fail on a quota, as
the LLM judges did when the account hit its 5-hour limit mid-run. Only precision is still judged.
Every earlier run's case file was scored again with the same patterns:

| Who did the reading | Runs | Key bugs per run (avg) | Cost per run |
|---|---|---|---|
| the main conversation, by itself (4 versions) | 12 | 1.0-1.7, one 3.7 | $0.28-0.37 |
| Sonnet in a clean context: 4 case readers | 3 | 4.0 | $0.54 |
| Sonnet in a clean context: model-router's routed-worker | 3 | 4.3 | $0.60 |
| Sonnet in a clean context: the investigator, with model-router | 3 | 4.0 | $0.67 |
| Sonnet in a clean context: the investigator, alone | 3 | 3.0 | $0.43 |

Handing the reading to Sonnet in a clean context finds about 2.5 times as many of the bugs that
were fixed later, at 50-100% more cost. The skill does that natively now (the investigator, or
case readers past 6 cases). Beside model-router there is no conflict: the skill hands off within
the router's 2 main-conversation calls, so the router denied nothing, and it never rewrites the
inspector's own agents. `evals/run-with-router.sh <model-router folder>` runs the comparison.

- The skill triggered by itself in every run.
- On this narrow question a direct read of the code finds about as many key bugs as the skill.
  What the skill adds is consistency (K1, reproduced, in every run) and precision (no lead
  without an input and a promise).
- The agents didn't call `--show` on their own (0 of 48 calls); written dossiers were read in 1
  run of 3. The list now opens the summary.

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
