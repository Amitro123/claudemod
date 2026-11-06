# The skeptic's eval

Real findings from this repository's reviews: known false positives the skeptic should set aside
(DESIGN, UNVERIFIED or REFUTED), and real bugs it must keep (STANDS, or DOWNGRADED and kept as minor).
Each case runs the skeptic's role and prompt, read from `hooks/flow.ts`, on a git worktree of the
commit before the fix (`hud-token.patch` recreates a solo build's version). Results and the reasons
behind them: `docs/bench/2026-11-07-skeptic.md`.

```bash
node plugins/factory/evals/skeptic/run.mjs          # every case, 2 runs each
node plugins/factory/evals/skeptic/run.mjs 3 fp-design-other tp-goal-replan
```
It needs `claude` on PATH and a model to call (it runs Sonnet, as the factory's skeptic does). The
worktrees go under the system temp folder; `git worktree prune` after deleting it.
